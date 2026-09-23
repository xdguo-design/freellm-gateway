import json
import threading
from datetime import datetime, timezone
from pathlib import Path


class ConnectionLogger:
    """Append safe, one-record-per-attempt connection diagnostics as JSONL."""

    _SAFE_FIELDS = frozenset({
        "request_id", "requested_model", "capability", "stream", "attempt",
        "tenant_id", "application_id", "route_id", "provider_id", "remote_model",
        "status", "elapsed_ms", "usage", "error_kind",
    })

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._lock = threading.Lock()

    def append(self, entry: dict) -> None:
        record = {"timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds")}
        record.update({key: entry[key] for key in self._SAFE_FIELDS if key in entry})
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
        with self._lock, self.path.open("a", encoding="utf-8") as handle:
            handle.write(line)

    def read(self, limit: int = 100) -> list[dict]:
        if not self.path.exists():
            return []
        records = []
        for line in self.path.read_text(encoding="utf-8").splitlines()[-limit:]:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict):
                records.append(record)
        return list(reversed(records))
