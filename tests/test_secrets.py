from cryptography.fernet import Fernet
import pytest

from freellm_gateway.secrets import EncryptedFileSecretStore, SecretStore, secret_store_from_env


class FakeKeyring:
    def __init__(self):
        self.values = {}

    def set_password(self, service, username, password):
        self.values[(service, username)] = password

    def get_password(self, service, username):
        return self.values.get((service, username))

    def delete_password(self, service, username):
        self.values.pop((service, username), None)


def test_secret_store_round_trips_secret_without_exposing_it_in_reference():
    store = SecretStore(FakeKeyring(), service="freellm-gateway-test")

    reference = store.save("route-1", "super-secret")

    assert reference == "keyring://freellm-gateway-test/route-1"
    assert store.get(reference) == "super-secret"
    assert "super-secret" not in reference


def test_secret_store_returns_none_after_delete():
    store = SecretStore(FakeKeyring(), service="freellm-gateway-test")
    reference = store.save("route-1", "super-secret")

    store.delete(reference)

    assert store.get(reference) is None


def test_encrypted_file_secret_store_persists_ciphertext_only(tmp_path):
    path = tmp_path / "secrets.json"
    key = Fernet.generate_key().decode("ascii")
    store = EncryptedFileSecretStore(path, key)

    reference = store.save("route/one", "cloud-secret")

    assert reference == "encrypted-file:///route%2Fone"
    assert "cloud-secret" not in path.read_text(encoding="utf-8")
    assert EncryptedFileSecretStore(path, key).get(reference) == "cloud-secret"

    store.delete(reference)
    assert store.get(reference) is None


def test_encrypted_file_secret_store_rejects_wrong_key(tmp_path):
    path = tmp_path / "secrets.json"
    first = EncryptedFileSecretStore(path, Fernet.generate_key().decode("ascii"))
    reference = first.save("route", "secret")
    second = EncryptedFileSecretStore(path, Fernet.generate_key().decode("ascii"))

    with pytest.raises(RuntimeError, match="decrypt"):
        second.get(reference)


def test_secret_store_from_env_requires_file_and_key_together(monkeypatch, tmp_path):
    monkeypatch.setenv("FREELLM_GATEWAY_SECRETS_FILE", str(tmp_path / "secrets.json"))
    monkeypatch.delenv("FREELLM_GATEWAY_SECRET_KEY", raising=False)

    with pytest.raises(RuntimeError, match="must be set together"):
        secret_store_from_env()


def test_encrypted_file_secret_store_readiness_checks_volume(tmp_path):
    path = tmp_path / "nested" / "provider-secrets.json"
    store = EncryptedFileSecretStore(path, Fernet.generate_key().decode("ascii"))

    store.check_ready()

    assert path.parent.is_dir()
    assert list(path.parent.glob(".freellm-secret-ready-*")) == []
