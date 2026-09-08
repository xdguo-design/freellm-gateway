from urllib.parse import quote, unquote, urlparse

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
