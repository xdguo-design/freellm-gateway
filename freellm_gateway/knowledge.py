"""Knowledge pipeline: extract, chunk, embed, Hybrid (BM25 + vector) search.

Embedding strategy (no extra pip deps required):
1. Local hashed bag-of-n-grams embedding (always available, deterministic).
2. Optional remote OpenAI-compatible embeddings when a callable is provided.

Vectors stored as JSON float arrays on chunks for SQLite MVP (Qdrant later).
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from collections.abc import Awaitable, Callable
from typing import Sequence


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def extract_text(raw: bytes | str, content_type: str = "text/plain", filename: str | None = None) -> str:
    if isinstance(raw, str):
        text = raw
    else:
        if raw.startswith(b"\xef\xbb\xbf"):
            raw = raw[3:]
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("utf-8", errors="replace")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if content_type in ("text/markdown", "text/x-markdown") or (filename or "").endswith((".md", ".markdown")):
        text = re.sub(r"^```[^\n]*\n", "", text, flags=re.MULTILINE)
        text = text.replace("```", "")
    return text.strip()


def chunk_text(text: str, chunk_size: int = 800, overlap: int = 120) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]

    paragraphs = re.split(r"\n\s*\n", text)
    units: list[str] = []
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        if len(para) <= chunk_size:
            units.append(para)
        else:
            start = 0
            while start < len(para):
                end = min(start + chunk_size, len(para))
                units.append(para[start:end].strip())
                if end >= len(para):
                    break
                start = max(end - overlap, start + 1)

    chunks: list[str] = []
    buf = ""
    for unit in units:
        if not buf:
            buf = unit
            continue
        if len(buf) + 2 + len(unit) <= chunk_size:
            buf = buf + "\n\n" + unit
        else:
            chunks.append(buf)
            if overlap > 0 and len(buf) > overlap:
                tail = buf[-overlap:]
                buf = tail + "\n\n" + unit
            else:
                buf = unit
    if buf:
        chunks.append(buf)
    return [c for c in chunks if c.strip()]


_TOKEN_RE = re.compile(r"[\w\u4e00-\u9fff]+", re.UNICODE)


def tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text) if t.strip()]


def estimate_tokens(text: str) -> int:
    return max(1, len(tokenize(text)))


# ── Local embedding (hashing trick / feature hashing) ─────────

DEFAULT_EMBED_DIM = 256


def local_embed(text: str, dim: int = DEFAULT_EMBED_DIM) -> list[float]:
    """Deterministic sparse-ish dense vector via feature hashing of unigrams + bigrams."""
    tokens = tokenize(text)
    if not tokens:
        return [0.0] * dim
    vec = [0.0] * dim
    grams = list(tokens)
    grams += [f"{tokens[i]}_{tokens[i+1]}" for i in range(len(tokens) - 1)]
    for g in grams:
        h = int(hashlib.md5(g.encode("utf-8")).hexdigest(), 16)
        idx = h % dim
        sign = 1.0 if (h >> 8) & 1 else -1.0
        vec[idx] += sign
    # L2 normalize
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


def embed_to_json(vec: list[float]) -> str:
    return json.dumps(vec)


def embed_from_json(raw: str | None) -> list[float] | None:
    if not raw:
        return None
    try:
        data = json.loads(raw)
        if isinstance(data, list) and data and all(isinstance(x, (int, float)) for x in data):
            return [float(x) for x in data]
    except (json.JSONDecodeError, TypeError):
        return None
    return None


async def embed_texts(
    texts: list[str],
    *,
    remote_embed: Callable[[list[str]], Awaitable[list[list[float]]]] | None = None,
) -> list[list[float]]:
    """Prefer remote embedding when provided; otherwise local hashing embed."""
    if remote_embed is not None and texts:
        try:
            vectors = await remote_embed(texts)
            if len(vectors) == len(texts):
                return vectors
        except Exception:
            pass
    return [local_embed(t) for t in texts]


# ── BM25 ──────────────────────────────────────────────────────

def bm25_search(
    query: str,
    corpus: list[tuple[str, str]],
    *,
    top_k: int = 5,
    k1: float = 1.5,
    b: float = 0.75,
) -> list[tuple[str, float, str]]:
    if not query.strip() or not corpus:
        return []
    q_tokens = tokenize(query)
    if not q_tokens:
        return []

    docs_tokens = [tokenize(content) for _, content in corpus]
    N = len(docs_tokens)
    avgdl = sum(len(d) for d in docs_tokens) / max(N, 1)

    df: Counter[str] = Counter()
    for tokens in docs_tokens:
        for t in set(tokens):
            df[t] += 1

    scores: list[tuple[str, float, str]] = []
    for (chunk_id, content), tokens in zip(corpus, docs_tokens):
        if not tokens:
            continue
        tf = Counter(tokens)
        dl = len(tokens)
        score = 0.0
        for term in q_tokens:
            if term not in tf:
                continue
            n_qi = df.get(term, 0)
            idf = math.log(1 + (N - n_qi + 0.5) / (n_qi + 0.5))
            freq = tf[term]
            denom = freq + k1 * (1 - b + b * dl / avgdl)
            score += idf * (freq * (k1 + 1) / denom)
        if score > 0:
            scores.append((chunk_id, score, content))

    scores.sort(key=lambda x: x[1], reverse=True)
    return scores[:top_k]


def _normalize_scores(pairs: list[tuple[str, float]]) -> dict[str, float]:
    if not pairs:
        return {}
    vals = [s for _, s in pairs]
    lo, hi = min(vals), max(vals)
    if hi - lo < 1e-12:
        return {cid: 1.0 for cid, _ in pairs}
    return {cid: (s - lo) / (hi - lo) for cid, s in pairs}


def hybrid_search(
    query: str,
    corpus: list[tuple[str, str, list[float] | None]],
    *,
    top_k: int = 5,
    alpha: float = 0.4,
    query_embedding: list[float] | None = None,
) -> list[tuple[str, float, str, dict]]:
    """
    corpus items: (chunk_id, content, embedding_or_none)
    alpha: weight of vector score; (1-alpha) for BM25.
    Returns (chunk_id, hybrid_score, content, detail).
    """
    text_corpus = [(cid, content) for cid, content, _ in corpus]
    bm25_hits = bm25_search(query, text_corpus, top_k=max(top_k * 4, 20))
    bm25_map = _normalize_scores([(cid, s) for cid, s, _ in bm25_hits])

    # vector scores
    q_vec = query_embedding or local_embed(query)
    vec_pairs: list[tuple[str, float]] = []
    content_map = {cid: content for cid, content, _ in corpus}
    for cid, content, emb in corpus:
        if emb is None:
            emb = local_embed(content)
        score = cosine(q_vec, emb)
        if score > 0:
            vec_pairs.append((cid, score))
    vec_map = _normalize_scores(vec_pairs)

    all_ids = set(bm25_map) | set(vec_map)
    fused: list[tuple[str, float, str, dict]] = []
    for cid in all_ids:
        b_s = bm25_map.get(cid, 0.0)
        v_s = vec_map.get(cid, 0.0)
        hybrid = (1.0 - alpha) * b_s + alpha * v_s
        fused.append(
            (
                cid,
                hybrid,
                content_map.get(cid, ""),
                {"bm25": round(b_s, 4), "vector": round(v_s, 4), "alpha": alpha},
            )
        )
    fused.sort(key=lambda x: x[1], reverse=True)
    return fused[:top_k]
