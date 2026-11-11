"""Saved connections: named Fusion instances, each with one or more users.

The URLs and usernames go in a small config file; every password goes into the
operating system's own credential store (Windows Credential Manager, macOS
Keychain, or the Linux Secret Service) through the `keyring` package. No
password is ever written to a file by this server.

    fusion-mcp setup [--instance NAME] [--url URL] [--user NAME] [--password-stdin]
        add an instance, add a user to one, or change a user's password
    fusion-mcp list                     show saved instances and users (never passwords)
    fusion-mcp default --instance NAME [--user NAME]
        choose the instance (and its user) used when a call names none
    fusion-mcp forget --instance NAME [--user NAME] | --all
        remove a user, an instance, or everything

config.json looks like this:

    {"default_instance": "dev",
     "instances": {"dev": {"url": "https://...", "default_user": "fin_reader",
                               "users": ["fin_reader", "hcm_reader"]}}}
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

from .errors import FusionToolError, FusionUnreachable

SERVICE = "fusion-bip-mcp-server"
DEFAULT_INSTANCE = "default"
_NAME = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,39}$")


def config_path() -> Path:
    base = os.environ.get("APPDATA") if os.name == "nt" else None
    base = base or os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return Path(base) / "fusion-mcp" / "config.json"


def _keyring():
    try:
        import keyring
        from keyring.backends import fail
    except ImportError as e:
        raise FusionToolError("The keyring package is not installed; reinstall with pip install -e .") from e
    if isinstance(keyring.get_keyring(), fail.Keyring):
        raise FusionToolError(
            "No OS keychain is available on this machine, so the password cannot be stored safely. "
            "Use a credential helper (FUSION_MCP_HELPER_DIR) or the plaintext environment variables "
            "described in the README.")
    return keyring


def normalize_url(url: str) -> str:
    """Keep only scheme and host, so a pasted Fusion page address still works."""
    parts = urlsplit(url.strip())
    if parts.scheme.lower() != "https" or not parts.hostname:
        raise FusionToolError("The Fusion URL must start with https://, for example "
                              "https://<your-pod>.fa.<region>.oraclecloud.com")
    if parts.username or parts.password:
        raise FusionToolError("The Fusion URL must not contain a username or password")
    try:
        port = parts.port
    except ValueError as e:
        raise FusionToolError(f"The Fusion URL has an invalid port: {e}") from e
    # hostname is already lowercase, so two spellings of one URL give the same result.
    return f"https://{parts.hostname}" + (f":{port}" if port not in (None, 443) else "")


def normalize_instance(name: str) -> str:
    n = name.strip().lower()
    if not _NAME.match(n):
        raise FusionToolError(f"Instance name {name!r} is not valid: use up to 40 letters, digits, "
                              "'_', '.' or '-', starting with a letter or digit.")
    return n


def _key(url: str, user: str) -> str:
    return f"{url.rstrip('/')}|{user.lower()}"


# ---------------------------------------------------------------- config file

def load_config() -> dict:
    """Return the saved config, or an empty one if nothing is saved yet."""
    p = config_path()
    if not p.exists():
        return {"default_instance": None, "instances": {}}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except ValueError as e:
        raise FusionToolError(f"{p} is damaged ({e}). Fix it, or delete it and run "
                              "`fusion-mcp setup` again.") from e


def save_config(cfg: dict) -> None:
    p = config_path()
    if not cfg["instances"]:
        p.unlink(missing_ok=True)
        try:
            p.parent.rmdir()  # only succeeds if nothing else (e.g. the usage log) is left in it
        except OSError:
            pass
        return
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")  # write then rename, so a running server never reads half a file
    tmp.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    os.replace(tmp, p)


def _find_user(inst: dict, user: str) -> str | None:
    return next((u for u in inst["users"] if u.lower() == user.lower()), None)


def _available(cfg: dict) -> str:
    if not cfg["instances"]:
        return "none saved"
    return "; ".join(f"{n} (users: {', '.join(i['users'])})" for n, i in sorted(cfg["instances"].items()))


def resolve(instance: str | None = None, user: str | None = None) -> tuple[str, str, str, str] | None:
    """Return (instance, url, username, password) for a call, or None if nothing is saved.

    With no instance named, FUSION_MCP_INSTANCE, then the saved default, then the
    only saved instance is used. With no user named, the instance's default user.
    """
    cfg = load_config()
    if not cfg["instances"]:
        return None
    name = instance or os.environ.get("FUSION_MCP_INSTANCE") or cfg.get("default_instance")
    if not name and len(cfg["instances"]) == 1:
        name = next(iter(cfg["instances"]))
    if not name:
        raise FusionToolError(f"Several instances are saved and none is the default; name one. "
                              f"Saved: {_available(cfg)}.")
    inst = cfg["instances"].get(name.strip().lower())
    if inst is None:
        raise FusionToolError(f"No saved instance named {name!r}. Saved: {_available(cfg)}.")
    name = name.strip().lower()
    if user:
        found = _find_user(inst, user)
        if not found:
            raise FusionToolError(f"Instance {name!r} has no saved user {user!r}. "
                                  f"Its users: {', '.join(inst['users'])}.")
    else:
        found = inst.get("default_user") or inst["users"][0]
    pw = _keyring().get_password(SERVICE, _key(inst["url"], found))
    if not pw:
        raise FusionToolError(f"No password in the OS keychain for {found} on instance {name!r}; run "
                              f"`fusion-mcp setup --instance {name} --user {found}` again.")
    return name, inst["url"], found, pw


def describe() -> dict:
    """Saved instances and users for the list tool and command. Never includes passwords."""
    cfg = load_config()
    env_default = os.environ.get("FUSION_MCP_INSTANCE")
    return {
        "default_instance": (env_default or cfg.get("default_instance") or
                             (next(iter(cfg["instances"])) if len(cfg["instances"]) == 1 else None)),
        "instances": {n: {"url": i["url"], "default_user": i.get("default_user") or i["users"][0],
                          "users": list(i["users"])}
                      for n, i in sorted(cfg["instances"].items())},
    }


# ---------------------------------------------------------------- commands

def _ask(prompt: str) -> str:
    try:
        return input(prompt).strip()
    except EOFError:
        raise FusionToolError("No input. Run this in a console, or pass the values as options "
                              "(--url, --user) and pipe the password with --password-stdin.")


def _password_window(instance: str, user: str) -> str | None:
    """Ask for the password in a small window. Returns "" on Cancel, None if no window can open."""
    try:
        import tkinter as tk
        root = tk.Tk()
    except Exception:
        return None
    result = {"pw": ""}

    def ok(_=None):
        result["pw"] = entry.get()
        root.destroy()

    root.title("Fusion NLQ MCP setup")
    root.attributes("-topmost", True)
    root.resizable(False, False)
    tk.Label(root, justify="left", padx=16, pady=12, text=(
        f"Enter the Fusion password for {user}\n(instance '{instance}').\n\n"
        "It is tested, then saved in your computer's credential store.")).pack(anchor="w")
    entry = tk.Entry(root, show="*", width=40)
    entry.pack(padx=16, fill="x")
    buttons = tk.Frame(root, pady=12)
    buttons.pack()
    tk.Button(buttons, text="Save", width=10, command=ok).pack(side="left", padx=4)
    tk.Button(buttons, text="Cancel", width=10, command=root.destroy).pack(side="left", padx=4)
    root.bind("<Return>", ok)
    root.bind("<Escape>", lambda _: root.destroy())
    root.after(100, lambda: (root.focus_force(), entry.focus_set()))
    root.mainloop()
    return result["pw"]


def setup(instance: str | None, url: str | None, user: str | None, password_stdin: bool) -> int:
    """Add an instance, add a user to an instance, or change a saved user's password."""
    from . import soap  # local import: soap is not needed to load credentials

    kr = _keyring()
    cfg = load_config()
    name = normalize_instance(instance or DEFAULT_INSTANCE)
    inst = cfg["instances"].get(name)
    if password_stdin and not (user and (inst or url)):
        raise FusionToolError("--password-stdin reads only the password, so also pass --user, "
                              "and --url when the instance is new.")
    if inst:
        if url and normalize_url(url) != normalize_url(inst["url"]):
            raise FusionToolError(f"Instance '{name}' already points to {inst['url']}. Use another "
                                  f"instance name, or remove it first with "
                                  f"`fusion-mcp forget --instance {name}`.")
        url = inst["url"]
    else:
        url = normalize_url(url or _ask("Fusion URL (e.g. https://<your-pod>.fa.<region>.oraclecloud.com): "))
    user = (user or _ask("Fusion username: ")).strip()
    for other, i in cfg["instances"].items():
        # Passwords are stored per URL and user, so a second instance with the same pair would
        # silently overwrite the first one's password.
        saved = _find_user(i, user) if other != name and normalize_url(i["url"]) == url else None
        if saved:
            raise FusionToolError(f"User {saved} on {url} is already saved under instance '{other}'. "
                                  f"Use that instance, or change its password with "
                                  f"`fusion-mcp setup --instance {other} --user {saved}`.")
    print(f"Fusion NLQ MCP setup for instance '{name}' ({url}). "
          "The password is stored in your OS keychain, not in a file.", flush=True)
    if password_stdin:
        pw = sys.stdin.readline().rstrip("\r\n")
    elif not (sys.stdin.isatty() and sys.stdout.isatty()):
        # No console (an AI agent ran this, or Git Bash): ask for the password in a small window.
        # stdout is checked too because on Windows a NUL stdin also reports isatty().
        pw = _password_window(name, user)
        if pw is None:
            print("No interactive console and no password window could be opened. Run setup from "
                  "PowerShell, cmd or Terminal, or use --password-stdin.")
            return 1
        if not pw:
            print("Cancelled. Nothing saved.")
            return 1
    else:
        pw = getpass.getpass(f"Password for {user} (hidden): ")
    if not (user and pw):
        print("Username and password are required. Nothing saved.")
        return 1
    print("Testing the login...")
    try:
        soap.login(url, user, pw)
    except FusionUnreachable as e:
        print(f"{e}\nCould not reach Fusion, so nothing was saved.")
        return 1
    except FusionToolError as e:
        print(f"Login failed: {e}\nNothing saved.")
        return 1
    kr.set_password(SERVICE, _key(url, user), pw)
    if inst is None:
        inst = cfg["instances"][name] = {"url": url, "default_user": user, "users": []}
    existing = _find_user(inst, user)
    if not existing:
        inst["users"].append(user)
    if not cfg.get("default_instance"):
        cfg["default_instance"] = name
    save_config(cfg)
    what = "Password updated" if existing else "Saved"
    print(f"{what} for {user} on instance '{name}'. URL and usernames: {config_path()}. "
          f"Password: OS keychain, service '{SERVICE}'.")
    return 0


def list_cmd() -> int:
    d = describe()
    if not d["instances"]:
        print("No saved instances. Run `fusion-mcp setup --instance NAME`.")
        return 0
    for n, i in d["instances"].items():
        mark = " (default)" if n == d["default_instance"] else ""
        print(f"{n}{mark}  {i['url']}")
        for u in i["users"]:
            print(f"    {u}{' (default)' if u == i['default_user'] else ''}")
    return 0


def default_cmd(instance: str, user: str | None) -> int:
    cfg = load_config()
    name = normalize_instance(instance)
    inst = cfg["instances"].get(name)
    if inst is None:
        raise FusionToolError(f"No saved instance named {name!r}. Saved: {_available(cfg)}.")
    if user:
        found = _find_user(inst, user)
        if not found:
            raise FusionToolError(f"Instance {name!r} has no saved user {user!r}.")
        inst["default_user"] = found
    cfg["default_instance"] = name
    save_config(cfg)
    print(f"Default: instance '{name}', user {inst['default_user']}.")
    return 0


def _drop_password(cfg: dict, url: str, user: str) -> str | None:
    """Delete a keychain entry unless another saved instance still uses the same URL and user.

    Returns the name of the instance that still uses it, or None when it was deleted."""
    for n, i in cfg["instances"].items():
        if i["url"] == url and _find_user(i, user):
            return n
    try:
        _keyring().delete_password(SERVICE, _key(url, user))
    except Exception:
        pass  # already gone from the keychain
    return None


def forget(instance: str | None, user: str | None, everything: bool) -> int:
    cfg = load_config()
    if everything:
        targets = list(cfg["instances"])
    elif instance:
        targets = [normalize_instance(instance)]
        if targets[0] not in cfg["instances"]:
            raise FusionToolError(f"No saved instance named {targets[0]!r}. Saved: {_available(cfg)}.")
    else:
        print("Name what to remove: --instance NAME (optionally --user NAME), or --all.")
        return 2
    if user and not everything:
        name = targets[0]
        inst = cfg["instances"][name]
        found = _find_user(inst, user)
        if not found:
            raise FusionToolError(f"Instance {name!r} has no saved user {user!r}.")
        inst["users"].remove(found)
        if not inst["users"]:
            del cfg["instances"][name]
        elif inst.get("default_user") == found:
            inst["default_user"] = inst["users"][0]
        kept = [(found, _drop_password(cfg, inst["url"], found))]
        removed = f"user {found} from instance '{name}'"
    else:
        kept = []
        for name in targets:
            inst = cfg["instances"].pop(name)
            for u in inst["users"]:
                kept.append((u, _drop_password(cfg, inst["url"], u)))
        removed = "all saved instances" if everything else f"instance '{targets[0]}'"
    if cfg.get("default_instance") not in cfg["instances"]:
        cfg["default_instance"] = next(iter(cfg["instances"]), None)
    save_config(cfg)
    kept = [(u, n) for u, n in kept if n]
    if kept:
        notes = "; ".join(f"{u} (still used by instance '{n}')" for u, n in kept)
        print(f"Removed {removed}. Kept the keychain password for {notes}.")
    else:
        print(f"Removed {removed} and its keychain passwords.")
    return 0


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="fusion-mcp", description=(
        "Fusion NLQ MCP server. With no command it starts the server (your MCP client runs this)."))
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("setup", help="add an instance or user, or change a saved password")
    s.add_argument("--instance", help=f"instance name (default: {DEFAULT_INSTANCE})")
    s.add_argument("--url", help="Fusion URL; asked for when the instance is new")
    s.add_argument("--user", help="Fusion username; asked for when left out")
    s.add_argument("--password-stdin", action="store_true",
                   help="read the password from standard input instead of a hidden prompt")
    sub.add_parser("list", help="show saved instances and users (never passwords)")
    d = sub.add_parser("default", help="choose the instance and user used when a call names none")
    d.add_argument("--instance", required=True)
    d.add_argument("--user")
    f = sub.add_parser("forget", help="remove a user, an instance, or everything")
    f.add_argument("--instance")
    f.add_argument("--user")
    f.add_argument("--all", action="store_true", dest="everything")
    return p


def cli(argv: list[str]) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.cmd == "setup":
            return setup(args.instance, args.url, args.user, args.password_stdin)
        if args.cmd == "list":
            return list_cmd()
        if args.cmd == "default":
            return default_cmd(args.instance, args.user)
        return forget(args.instance, args.user, args.everything)
    except FusionToolError as e:
        print(e, file=sys.stderr)
        return 1
