import json
import os
from pathlib import Path
from threading import Lock
from urllib.parse import quote, unquote, urlparse

from cryptography.fernet import Fernet, InvalidToken

try:
    import keyring as _keyring
except ModuleNotFoundError:  # pragma: no cover - dependency is installed in production
    _keyring = None


class SecretStore:
    def __init__(self, backend=None, service: str = "freellm-gateway"):
        self.backend = backend or _keyring
        if self.backend is None:
            raise RuntimeError("keyring is required for the default secret store")
        self.service = service

    def save(self, name: str, value: str) -> str:
        self.backend.set_password(self.service, name, value)
        return f"keyring://{quote(self.service, safe='')}/{quote(name, safe='')}"

    def get(self, reference: str) -> str | None:
        service, name = self._parse(reference)
        return self.backend.get_password(service, name)

    def delete(self, reference: str) -> None:
        service, name = self._parse(reference)
        self.backend.delete_password(service, name)

    @staticmethod
    def _parse(reference: str) -> tuple[str, str]:
        parsed = urlparse(reference)
        if parsed.scheme != "keyring" or not parsed.netloc or not parsed.path.strip("/"):
            raise ValueError("invalid keyring reference")
        return unquote(parsed.netloc), unquote(parsed.path.strip("/"))


class EncryptedFileSecretStore:
    """Small single-instance secret store for container deployments.

    Values are encrypted with Fernet. The encryption key is never written to
    disk; only encrypted tokens are stored in the persistent file.
    """

    def __init__(self, path: str | Path, key: str):
        self.path = Path(path)
        try:
            self.cipher = Fernet(key.encode("ascii"))
        except (ValueError, UnicodeEncodeError) as error:
            raise RuntimeError(
                "FREELLM_GATEWAY_SECRET_KEY must be a valid Fernet key"
            ) from error
        self._lock = Lock()

    def save(self, name: str, value: str) -> str:
        token = self.cipher.encrypt(value.encode("utf-8")).decode("ascii")
        with self._lock:
            data = self._load()
            data[name] = token
            self._write(data)
        return f"encrypted-file:///{quote(name, safe='')}"

    def get(self, reference: str) -> str | None:
        name = self._parse(reference)
        with self._lock:
            token = self._load().get(name)
        if token is None:
            return None
        try:
            return self.cipher.decrypt(token.encode("ascii")).decode("utf-8")
        except (InvalidToken, UnicodeDecodeError) as error:
            raise RuntimeError("unable to decrypt stored provider credential") from error

    def delete(self, reference: str) -> None:
        name = self._parse(reference)
        with self._lock:
            data = self._load()
            if name in data:
                data.pop(name)
                self._write(data)

    def _load(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise RuntimeError(f"unable to read encrypted secret store: {self.path}") from error
        if not isinstance(payload, dict) or any(
            not isinstance(name, str) or not isinstance(token, str)
            for name, token in payload.items()
        ):
            raise RuntimeError("encrypted secret store has an invalid format")
        return payload

    def _write(self, data: dict[str, str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(self.path.name + ".tmp")
        temporary.write_text(
            json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        try:
            os.chmod(temporary, 0o600)
        except OSError:
            pass
        temporary.replace(self.path)

    @staticmethod
    def _parse(reference: str) -> str:
        parsed = urlparse(reference)
        if parsed.scheme != "encrypted-file" or not parsed.path.strip("/"):
            raise ValueError("invalid encrypted-file reference")
        return unquote(parsed.path.strip("/"))


def secret_store_from_env():
    path = os.getenv("FREELLM_GATEWAY_SECRETS_FILE")
    key = os.getenv("FREELLM_GATEWAY_SECRET_KEY")
    if path or key:
        if not path or not key:
            raise RuntimeError(
                "FREELLM_GATEWAY_SECRETS_FILE and FREELLM_GATEWAY_SECRET_KEY must be set together"
            )
        return EncryptedFileSecretStore(path, key)
    return SecretStore()
