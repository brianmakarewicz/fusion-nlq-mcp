import io
import json

import pytest

from fusion_mcp import credentials, soap
from fusion_mcp.errors import FusionToolError

URL = "https://pod.fa.example.oraclecloud.com"


def _setup(monkeypatch, instance, user, pw="pw", url=URL):
    monkeypatch.setattr("sys.stdin", io.StringIO(pw + "\n"))
    return credentials.setup(instance, url, user, password_stdin=True)


@pytest.fixture
def logins(monkeypatch):
    seen = []
    monkeypatch.setattr(soap, "login", lambda url, user, pw: seen.append(user) or "token")
    return seen


def test_setup_saves_url_and_user_but_not_the_password(monkeypatch, logins, isolated):
    assert _setup(monkeypatch, "dev", "fin_reader", "s3cret") == 0
    cfg = json.loads(credentials.config_path().read_text())
    assert cfg["instances"]["dev"]["users"] == ["fin_reader"]
    assert "s3cret" not in credentials.config_path().read_text()
    assert "s3cret" in isolated.store.values()


def test_same_url_and_user_under_another_instance_is_refused_before_login(monkeypatch, logins):
    assert _setup(monkeypatch, "dev", "fin_reader") == 0
    with pytest.raises(FusionToolError, match="already saved under instance 'dev'"):
        _setup(monkeypatch, "test", "FIN_READER")
    assert logins == ["fin_reader"]  # the refused setup never tried to log in


def test_failed_login_saves_nothing(monkeypatch, isolated):
    def reject(url, user, pw):
        raise FusionToolError("invalid username or password")
    monkeypatch.setattr(soap, "login", reject)
    assert _setup(monkeypatch, "dev", "fin_reader") == 1
    assert not credentials.config_path().exists()
    assert isolated.store == {}


def test_forget_one_user_keeps_the_other_users_password(monkeypatch, logins, isolated):
    assert _setup(monkeypatch, "dev", "fin_reader") == 0
    assert _setup(monkeypatch, "dev", "hcm_reader") == 0
    assert credentials.forget("dev", "hcm_reader", False) == 0
    assert credentials.load_config()["instances"]["dev"]["users"] == ["fin_reader"]
    assert len(isolated.store) == 1


def test_a_damaged_config_file_gives_a_clear_error(isolated):
    path = credentials.config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(FusionToolError, match="is damaged"):
        credentials.load_config()
