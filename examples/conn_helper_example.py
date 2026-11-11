"""Example credential helper for several Fusion accounts (FUSION_MCP_HELPER_DIR).

It serves one Fusion instance; the instance named on a call is ignored. Copy this
file to a folder outside the repo as conn_helper.py and set
FUSION_MCP_HELPER_DIR to that folder. Passwords live in the OS keychain; the only
file is accounts.json next to this script, which holds the URL and account names
and no passwords:

    {"url": "https://<your-pod>.fa.<region>.oraclecloud.com",
     "accounts": ["report_reader", "gl_reader"]}

Add an account (the password prompt is hidden and goes straight to the keychain):

    python conn_helper.py add report_reader

Every account you add here can be used by the agent through `fusion_user`, so add
only accounts whose access you are happy for the agent to have.
"""
import getpass
import json
import sys
from pathlib import Path

import keyring

SERVICE = "fusion-bip-mcp-server-helper"
ACCOUNTS = Path(__file__).with_name("accounts.json")


def _cfg():
    return json.loads(ACCOUNTS.read_text(encoding="utf-8"))


def get_fusion_url(pod=None):
    return _cfg()["url"]


def get_fusion_user(name, pod=None):
    if name not in _cfg()["accounts"]:
        raise KeyError(f"No Fusion account named {name!r} in accounts.json")
    pw = keyring.get_password(SERVICE, name)
    if pw is None:
        raise KeyError(f"No keychain password for {name!r}; run: python conn_helper.py add {name}")
    return name, pw


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != "add":
        sys.exit("Usage: python conn_helper.py add <account name>")
    name = sys.argv[2]
    cfg = _cfg() if ACCOUNTS.exists() else {"url": input("Fusion URL: ").strip(), "accounts": []}
    pw = getpass.getpass(f"Password for {name} (hidden): ")
    if not pw:
        sys.exit("No password entered. Nothing saved.")
    keyring.set_password(SERVICE, name, pw)
    if name not in cfg["accounts"]:
        cfg["accounts"].append(name)
    ACCOUNTS.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    print(f"Saved {name}: password in the OS keychain, account name in {ACCOUNTS}")
