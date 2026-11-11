"""Low-level BIP v2 SOAP client, direct from this host to Fusion.

BIP SOAP is token-based, not Basic Auth: SecurityService returns a session token
from a login envelope, and every catalog and report call carries that token.

Every value placed in an envelope is XML-escaped, and every response body is
gunzipped when Fusion compresses it, so faults are always readable.
"""

from __future__ import annotations

import base64
import gzip
import html
import re
import ssl
import urllib.error
import urllib.request
from xml.sax.saxutils import escape as _esc

from .errors import FusionToolError, FusionUnreachable, SessionExpired

_NS = ('xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" '
       'xmlns:v2="http://xmlns.oracle.com/oxp/service/v2"')
_ACT = "http://xmlns.oracle.com/oxp/service/v2"
_CTX = ssl.create_default_context()
GZIP_MAGIC = bytes((0x1F, 0x8B))


def _post(base_url: str, service: str, action: str, body: str) -> str:
    url = f"{base_url.rstrip('/')}/xmlpserver/services/v2/{service}"
    req = urllib.request.Request(
        url, data=body.encode("utf-8"), method="POST",
        headers={"Content-Type": "text/xml; charset=utf-8", "SOAPAction": action})
    try:
        with urllib.request.urlopen(req, timeout=120, context=_CTX) as r:
            raw = r.read()
    except urllib.error.HTTPError as e:
        # Fusion returns SOAP faults as HTTP 500, often gzip-compressed.
        resp = _text(e.read())
        if "Fault" in resp:
            return resp
        if e.code >= 500 or e.code == 429:  # maintenance or overload, not a bad password
            raise FusionUnreachable(f"Fusion returned HTTP {e.code} for the {service} call. "
                                    "It may be down for maintenance; try again later.") from e
        raise FusionToolError(f"Fusion returned HTTP {e.code} for the {service} call. "
                              "Check that the instance URL is right.") from e
    except Exception as e:  # network/DNS/TLS/timeout
        if isinstance(e, TimeoutError) or isinstance(getattr(e, "reason", None), TimeoutError):
            hint = (" For a slow query, add a filter or select fewer rows."
                    if service == "ReportService" else "")
            raise FusionUnreachable(f"Fusion did not answer the {service} call within "
                                    f"120 seconds.{hint}") from e
        raise FusionUnreachable(f"Fusion unreachable: {e}") from e
    return _text(raw)


def _text(raw: bytes) -> str:
    """Decode a response body, gunzipping it first if it is compressed."""
    if raw[:2] == GZIP_MAGIC:
        raw = gzip.decompress(raw)
    return raw.decode("utf-8", "replace")


def _fault(resp: str) -> str | None:
    """Return the fault message, shortened to the Oracle error when there is one."""
    m = re.search(r"faultstring>(.*?)</faultstring>", resp, re.S)
    if not m:
        return None
    text = html.unescape(m.group(1)).strip()
    # BIP wraps database errors in a long chain of Java exception names; the
    # ORA- error is the part an agent (or a person) can act on.
    # The query runs inside a PL/SQL block, so skip the block's wrapper codes
    # (ORA-06550 position, ORA-06512 stack) and return the first real error.
    oras = re.findall(r"ORA-\d{5}:[^\n]*", text)
    real = [o for o in oras if not o.startswith(("ORA-06550", "ORA-06512"))]
    if real or oras:
        return re.sub(r"\s+https?://\S+", "", (real or oras)[0]).strip()
    # Otherwise keep only the innermost exception's message.
    return re.split(r"[\w.]+Exception:\s*", text)[-1].strip() or text


def _raise_if_fault(resp: str, what: str) -> str:
    f = _fault(resp)
    if f and "invalid BIPSessionToken" in f:
        raise SessionExpired("BI Publisher session token is no longer valid")
    if f or "soapenv:Fault" in resp or "soap:Fault" in resp:
        raise FusionToolError(f or f"{what}: SOAP fault: {resp[:300]}")
    return resp


def _b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode()


def decode_report_bytes(resp: str) -> str:
    """Decode the base64 <reportBytes> in a runDataModel response."""
    m = re.search(r"<reportBytes>(.*?)</reportBytes>", resp, re.S)
    if not m:
        raise FusionToolError(f"No report data in the BI Publisher response: {resp[:300]}")
    return _text(base64.b64decode(m.group(1)))


def login(base_url: str, user: str, pw: str) -> str:
    env = (f'<soapenv:Envelope {_NS}><soapenv:Body><v2:login>'
           f'<v2:userID>{_esc(user)}</v2:userID><v2:password>{_esc(pw)}</v2:password>'
           f'</v2:login></soapenv:Body></soapenv:Envelope>')
    resp = _post(base_url, "SecurityService", f"{_ACT}/SecurityService/loginRequest", env)
    m = re.search(r"loginReturn>(.*?)</", resp, re.S)
    if not m:
        raise FusionToolError(_fault(resp) or "login returned no session token")
    return html.unescape(m.group(1))


def create_object(base_url: str, token: str, folder: str, name: str,
                  otype: str, xml: str) -> None:
    env = (f'<soapenv:Envelope {_NS}><soapenv:Body><v2:createObjectInSession>'
           f'<v2:folderAbsolutePathURL>{_esc(folder)}</v2:folderAbsolutePathURL>'
           f'<v2:objectName>{_esc(name)}</v2:objectName><v2:objectType>{_esc(otype)}</v2:objectType>'
           f'<v2:bipSessionToken>{_esc(token)}</v2:bipSessionToken>'
           f'<v2:objectData>{_b64(xml)}</v2:objectData>'
           f'</v2:createObjectInSession></soapenv:Body></soapenv:Envelope>')
    _raise_if_fault(
        _post(base_url, "CatalogService",
              f"{_ACT}/CatalogService/createObjectInSessionRequest", env),
        f"create {otype} {folder}/{name}")


def delete_object(base_url: str, token: str, path: str) -> None:
    env = (f'<soapenv:Envelope {_NS}><soapenv:Body><v2:deleteObjectInSession>'
           f'<v2:objectAbsolutePath>{_esc(path)}</v2:objectAbsolutePath>'
           f'<v2:bipSessionToken>{_esc(token)}</v2:bipSessionToken>'
           f'</v2:deleteObjectInSession></soapenv:Body></soapenv:Envelope>')
    _raise_if_fault(
        _post(base_url, "CatalogService",
              f"{_ACT}/CatalogService/deleteObjectInSessionRequest", env),
        f"delete {path}")


def run_data_model_in_session(base_url: str, token: str, dm_path: str) -> str:
    env = (f'<soapenv:Envelope {_NS}><soapenv:Body><v2:runDataModelInSession>'
           f'<v2:reportRequest><v2:reportAbsolutePath>{_esc(dm_path)}</v2:reportAbsolutePath>'
           f'<v2:sizeOfDataChunkDownload>-1</v2:sizeOfDataChunkDownload></v2:reportRequest>'
           f'<v2:bipSessionToken>{_esc(token)}</v2:bipSessionToken>'
           f'</v2:runDataModelInSession></soapenv:Body></soapenv:Envelope>')
    return _raise_if_fault(
        _post(base_url, "ReportService",
              f"{_ACT}/ReportService/runDataModelInSessionRequest", env),
        f"run data model {dm_path}")
