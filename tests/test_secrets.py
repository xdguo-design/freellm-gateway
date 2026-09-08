from freellm_gateway.secrets import SecretStore


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
