"""Keep every test away from the real config file, keychain and Fusion."""

import pytest

from fusion_mcp import credentials, soap


class FakeKeyring:
    def __init__(self):
        self.store = {}

    def set_password(self, service, key, pw):
        self.store[(service, key)] = pw

    def get_password(self, service, key):
        return self.store.get((service, key))

    def delete_password(self, service, key):
        self.store.pop((service, key), None)


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    for var in ("FUSION_MCP_HELPER_DIR", "FUSION_URL", "FUSION_USERNAME", "FUSION_PASSWORD",
                "FUSION_MCP_INSTANCE"):
        monkeypatch.delenv(var, raising=False)
    kr = FakeKeyring()
    monkeypatch.setattr(credentials, "_keyring", lambda: kr)

    def no_network(*args, **kwargs):
        raise AssertionError("a test tried to reach Fusion")
    for name in ("login", "create_object", "delete_object", "run_data_model_in_session"):
        monkeypatch.setattr(soap, name, no_network)
    return kr
