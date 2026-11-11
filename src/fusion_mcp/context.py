"""Execution context: where credentials are resolved.

Nothing is built in: no pod, no user, no password. The person who installs the
server supplies them in one of three ways, checked in this order:

1. A credential helper of your own. Set FUSION_MCP_HELPER_DIR to the folder
   holding conn_helper.py, which defines
       get_fusion_url(pod) -> str
       get_fusion_user(name, pod) -> (username, password)
   The call's instance (or FUSION_MCP_POD) is passed as `pod`; FUSION_MCP_USER
   names the default account.
2. Plaintext environment variables FUSION_URL, FUSION_USERNAME, FUSION_PASSWORD.
   These sit unencrypted in your MCP client's config, so the server refuses them
   unless FUSION_MCP_ACCEPT_PLAINTEXT_PASSWORD=yes confirms you accept that risk.
3. Saved connections from `fusion-mcp setup` (recommended): named instances with
   their URLs and usernames in a config file, passwords in the OS keychain.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from . import credentials
from .errors import FusionToolError

_SETUP_HINT = ("Run `fusion-mcp setup --instance NAME` to save a connection (password kept in "
               "the OS keychain), or see the README for the other options.")


def source() -> str:
    """Which of the three credential sources is in effect: helper, env or saved."""
    if os.environ.get("FUSION_MCP_HELPER_DIR"):
        return "helper"
    if os.environ.get("FUSION_PASSWORD"):
        return "env"
    return "saved"


def _load_helper(helper_dir: str):
    """Load conn_helper.py straight from its file.

    Loading it by path, instead of putting helper_dir first on sys.path, means another
    file in that folder (a stray json.py, say) can never replace a real module.
    """
    import importlib.util
    path = os.path.join(helper_dir, "conn_helper.py")
    try:
        spec = importlib.util.spec_from_file_location("conn_helper", path)
        if spec is None or spec.loader is None:
            raise ImportError(f"no conn_helper.py in {helper_dir}")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.get_fusion_url, mod.get_fusion_user
    except (ImportError, OSError, AttributeError) as e:
        raise FusionToolError(f"Could not load conn_helper from {helper_dir}: {e}") from e


@dataclass(frozen=True)
class FusionContext:
    """Resolved targets for one tool call."""

    instance: str | None = None      # saved instance name; None means the default
    fusion_user: str | None = None   # account name; None means the instance's default

    def fusion_login(self):
        """Return (base_url, username, password) for this call."""
        src = source()
        if src == "helper":
            helper_dir = os.environ["FUSION_MCP_HELPER_DIR"]
            get_fusion_url, get_fusion_user = _load_helper(helper_dir)
            name = self.fusion_user or os.environ.get("FUSION_MCP_USER")
            if not name:
                raise FusionToolError("No Fusion account named: set FUSION_MCP_USER "
                                      "or pass fusion_user on the call.")
            pod = self.instance or os.environ.get("FUSION_MCP_POD")
            try:
                user, pwd = get_fusion_user(name, pod)
                raw_url = get_fusion_url(pod)
            except Exception as e:  # name the error type only; its text could hold helper data
                raise FusionToolError(f"Credential helper failed for account {name!r}: "
                                      f"{type(e).__name__}") from e
            return credentials.normalize_url(raw_url), user, pwd

        if src == "env":
            url = os.environ.get("FUSION_URL")
            user = os.environ.get("FUSION_USERNAME")
            pwd = os.environ["FUSION_PASSWORD"]
            if os.environ.get("FUSION_MCP_ACCEPT_PLAINTEXT_PASSWORD", "").lower() != "yes":
                raise FusionToolError(
                    "FUSION_PASSWORD is set, but a plaintext password in your MCP config is unsafe. "
                    "Run `fusion-mcp setup` to store it in the OS keychain instead, or set "
                    "FUSION_MCP_ACCEPT_PLAINTEXT_PASSWORD=yes to confirm you accept the risk.")
            if not (url and user):
                raise FusionToolError("FUSION_PASSWORD is set but FUSION_URL or FUSION_USERNAME is missing.")
            if self.instance:
                raise FusionToolError("The server is configured with environment variables, which hold "
                                      f"one connection only; instance={self.instance!r} is not available.")
            if self.fusion_user and self.fusion_user.lower() != user.lower():
                raise FusionToolError(
                    f"Only the configured account is available ({user}); "
                    f"fusion_user={self.fusion_user!r} was requested.")
            return credentials.normalize_url(url), user, pwd

        saved = credentials.resolve(self.instance, self.fusion_user)
        if not saved:
            raise FusionToolError("Fusion connection is not configured. " + _SETUP_HINT)
        _, url, user, pwd = saved
        return url, user, pwd


def default_context(instance: str | None = None, fusion_user: str | None = None) -> FusionContext:
    """Resolve the context for a call, with an optional per-call instance and account."""
    return FusionContext(instance=instance or None, fusion_user=fusion_user or None)
