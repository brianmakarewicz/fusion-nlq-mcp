"""URL handling, login back-off, HTTP errors, the credential helper and the usage log."""

import io
import json
import urllib.error

import pytest

from fusion_mcp import credentials, direct_client, metering, soap
from fusion_mcp.context import FusionContext
from fusion_mcp.errors import FusionToolError, FusionUnreachable

URL = "https://pod.fa.example.oraclecloud.com"


@pytest.mark.parametrize("raw, expected", [
    ("https://POD.fa.Example.oraclecloud.com", URL),
    ("https://pod.fa.example.oraclecloud.com:443/fscmUI/faces/FuseWelcome", URL),
    ("https://pod.fa.example.oraclecloud.com:8443", URL + ":8443"),
])
def test_urls_are_normalized(raw, expected):
    assert credentials.normalize_url(raw) == expected


@pytest.mark.parametrize("raw", [
    "http://pod.fa.example.oraclecloud.com",
    "https://user:secret@pod.fa.example.oraclecloud.com",
    "pod.fa.example.oraclecloud.com",
])
def test_bad_urls_are_refused(raw):
    with pytest.raises(FusionToolError):
        credentials.normalize_url(raw)


def test_the_same_url_spelled_differently_is_still_a_duplicate(monkeypatch):
    monkeypatch.setattr(soap, "login", lambda url, user, pw: "token")
    monkeypatch.setattr("sys.stdin", io.StringIO("pw\n"))
    assert credentials.setup("dev", URL, "fin_reader", password_stdin=True) == 0
    with pytest.raises(FusionToolError, match="already saved under instance 'dev'"):
        credentials.setup("test", "https://POD.fa.example.oraclecloud.com:443", "fin_reader",
                          password_stdin=True)


@pytest.fixture
def one_account(monkeypatch):
    direct_client._tokens.clear()
    direct_client._failed.clear()
    monkeypatch.setattr(FusionContext, "fusion_login", lambda self: (URL, "fin_reader", "pw"))


def test_any_rejected_login_backs_off(one_account, monkeypatch):
    attempts = []

    def reject(url, user, pw):
        attempts.append(user)
        raise FusionToolError("The account is locked")
    monkeypatch.setattr(soap, "login", reject)
    with pytest.raises(FusionToolError, match="locked"):
        direct_client._token(FusionContext())
    with pytest.raises(FusionToolError, match="Not retrying"):
        direct_client._token(FusionContext())
    assert attempts == ["fin_reader"]  # the second call never tried to log in


def test_an_unreachable_fusion_does_not_back_off(one_account, monkeypatch):
    attempts = []

    def down(url, user, pw):
        attempts.append(user)
        raise FusionUnreachable("Fusion unreachable: timed out")
    monkeypatch.setattr(soap, "login", down)
    for _ in range(2):
        with pytest.raises(FusionUnreachable):
            direct_client._token(FusionContext())
    assert len(attempts) == 2


class _Http404(urllib.error.HTTPError):
    def __init__(self):
        super().__init__("https://x", 404, "Not Found", {}, io.BytesIO(b"<html>Not Found</html>"))


def test_an_http_error_page_is_reported_not_treated_as_success(monkeypatch):
    def fail(*args, **kwargs):
        raise _Http404()
    monkeypatch.setattr(soap.urllib.request, "urlopen", fail)
    with pytest.raises(FusionToolError, match="HTTP 404"):
        soap._post(URL, "CatalogService", "action", "<x/>")


class _Http503(urllib.error.HTTPError):
    def __init__(self):
        super().__init__("https://x", 503, "Service Unavailable", {}, io.BytesIO(b"<html>Down</html>"))


def test_a_server_error_counts_as_unreachable_not_a_bad_password(monkeypatch):
    def fail(*args, **kwargs):
        raise _Http503()
    monkeypatch.setattr(soap.urllib.request, "urlopen", fail)
    with pytest.raises(FusionUnreachable, match="HTTP 503"):
        soap._post(URL, "SecurityService", "action", "<x/>")


def test_a_credential_helper_url_must_be_https(tmp_path, monkeypatch):
    (tmp_path / "conn_helper.py").write_text(
        "def get_fusion_url(pod): return 'http://pod.fa.example.oraclecloud.com'\n"
        "def get_fusion_user(name, pod): return (name, 'pw')\n")
    monkeypatch.setenv("FUSION_MCP_HELPER_DIR", str(tmp_path))
    with pytest.raises(FusionToolError, match="https"):
        FusionContext(fusion_user="fin_reader").fusion_login()


def test_a_failing_helper_reports_only_the_error_type(tmp_path, monkeypatch):
    (tmp_path / "conn_helper.py").write_text(
        "def get_fusion_url(pod): return 'https://pod.fa.example.oraclecloud.com'\n"
        "def get_fusion_user(name, pod): raise KeyError('secret-value')\n")
    monkeypatch.setenv("FUSION_MCP_HELPER_DIR", str(tmp_path))
    with pytest.raises(FusionToolError) as e:
        FusionContext(fusion_user="fin_reader").fusion_login()
    assert "KeyError" in str(e.value) and "secret-value" not in str(e.value)


def test_the_usage_log_keeps_lengths_only(tmp_path, monkeypatch):
    log = tmp_path / "usage.jsonl"
    monkeypatch.setenv("FUSION_MCP_METER_LOG", str(log))
    with metering.Meter("query_fusion", {"sql": "SELECT ssn FROM x WHERE ssn = '123-45-6789'"}):
        pass
    rec = json.loads(log.read_text())
    assert rec["inputs"] == {"sql": {"len": 43}}
    assert "123-45-6789" not in log.read_text()


def test_password_stdin_needs_the_user_and_a_url_for_a_new_instance():
    with pytest.raises(FusionToolError, match="--password-stdin"):
        credentials.setup("dev", "https://pod.fa.example.oraclecloud.com", None, True)
    with pytest.raises(FusionToolError, match="--password-stdin"):
        credentials.setup("dev", None, "fin_reader", True)
