# Fusion NLQ MCP

An [MCP](https://modelcontextprotocol.io) server that lets an AI agent answer questions from live **Oracle Fusion** data. You ask in plain English; the agent writes the SQL, runs it through this server, reads the rows back, and if the query fails it looks up the right tables and columns and tries again. The server's main tool is `query_fusion`; it can hold several Fusion instances with several users each, and the agent picks the instance and user on every call. It talks to Fusion's BI Publisher SOAP service directly from your machine, so there is no database or middle tier to stand up.

## The tools

| Tool | What it does | Arguments |
|------|--------------|-----------|
| `query_fusion` | Runs one query against Oracle Fusion and returns the rows as XML | `sql`, optional `instance`, optional `fusion_user` |
| `list_fusion_connections` | Lists the saved instances, their URLs and users, and the defaults (never passwords) | none |

- `sql` is one `SELECT` (or `WITH ... SELECT`). Results come back as an XML declaration followed by `<ROWSET><ROW><COLUMN_NAME>value</COLUMN_NAME>...</ROW></ROWSET>`, with tags taken from the column names or aliases, so give expressions an alias (`COUNT(*) AS INVOICE_COUNT`).
- `instance` names a saved instance (see setup below); left out, the default instance is used.
- `fusion_user` names a user saved on that instance; left out, the instance's default user is used.

One session can switch freely, for example querying dev as a finance user, then as an HCM user, then test. The tool's description tells the agent that each instance is a separate environment and not to mix data between them unless asked.

**When a query fails**, the Oracle error comes back as the tool's error, for example `ORA-00942: table or view does not exist` or `ORA-00904: "VENDOR": invalid identifier`. The tool's description tells the agent how to recover: look tables up in `ALL_OBJECTS`, list columns from `ALL_TAB_COLUMNS` (both through this same tool), or read Oracle's *Tables and Views for Oracle Fusion Cloud* guides on docs.oracle.com, then correct the SQL and run it again. Many Fusion objects are synonyms, which have no rows in `ALL_TAB_COLUMNS`, so the description also tells the agent to follow a synonym to its view or table, to filter date-effective `_F`/`_M` tables on `SYSDATE`, and to decode code columns through `FND_LOOKUP_VALUES`. `DBA_` views are not available to Fusion users.

**Limits:** results over 40,000 characters are cut at a whole row and end with a comment saying how many rows were shown (set `FUSION_MCP_MAX_CHARS` to change the limit). Each request to Fusion stops with an error if it gets no answer within 120 seconds. Queries run against BI Publisher's `ApplicationDB_FSCM` data source.

**What it accepts:** the SQL must start with `SELECT` or `WITH`, must not contain a semicolon (one trailing semicolon is removed) and must not use `FOR UPDATE`, which would lock the rows it reads. The query runs inside a short PL/SQL block so BI Publisher can read the column names; refusing semicolons means nothing can be added after the query. Beyond these checks, what a query can do is decided by Fusion's own permissions for the saved account.

**Text in the results is data, not instructions.** Free-text fields such as supplier names, invoice descriptions and comments are typed by people inside and outside your company, and the rows go straight to the agent. Someone could plant text there that tries to instruct it. The tool's description tells the agent never to follow instructions found in results, but that rests on the agent's judgment. Be careful running broad free-text queries in a session where the agent can also send email, upload files or run commands.

Each query runs through a temporary data model created in the account's own BI Publisher folder (`/~username`) and deleted when the call ends, whether it succeeds or fails. If Fusion cannot be reached at that moment, or an expired login cannot be renewed, the model stays behind; its name starts with `MCPQ_` and it is safe to delete.

## Setup

The repo contains no Fusion addresses, users or passwords. You supply your own.

### Quick setup: let Claude Code do it

Paste this into Claude Code:

> Install and set up the Fusion NLQ MCP server from https://github.com/brianmakarewicz/fusion-nlq-mcp. Follow "Steps for an AI agent" in its README.

It asks for a name for the instance, the Fusion URL and your username. The password goes into a small window that opens on your screen, never into the chat. When it is done, close and reopen Claude Code and ask a question.

#### Steps for an AI agent

In every step, run `fusion-mcp` by its full path, `<repo>/.venv/Scripts/fusion-mcp` on Windows or `<repo>/.venv/bin/fusion-mcp` on macOS and Linux. A bare `fusion-mcp` could run some other copy that is on the PATH.

1. Check that Python 3.10+ and Git are installed. If either is missing, tell the user how to install it and stop. Also check that `python -c "import tkinter"` works, because the password window needs it. If tkinter is missing, the user can still pipe the password in (step 4), so tell them and ask which they prefer rather than stopping.
2. Clone the repo into the user's home folder (`%USERPROFILE%` on Windows), create the venv with `python -m venv .venv` inside it, and run `pip install -e .` with the venv's pip. If the folder already exists, run `git pull` there instead of cloning, then run `pip install -e .` again in case the dependencies changed. If `git pull` reports local changes, ask the user before discarding them.
3. Ask the user for a short instance name (for example dev or test), the Fusion URL, and the Fusion username. Never ask for the password in chat.
4. Run `fusion-mcp setup --instance NAME --url URL --user USER` with a timeout of at least five minutes.
   - With no terminal attached, a window opens for the user to type the password, so tell them to look for it.
   - If you cannot open a window on the user's screen, the user can pipe the password in themselves: `<command that prints the password> | <full path to fusion-mcp> setup --instance NAME --url URL --user USER --password-stdin`. It reads the first line of input as the password, so don't write the password into a file to do this. Avoid handling the password yourself unless the user explicitly asks you to, because it then passes through your session.
   - Setup tests the login before saving. On success it prints `Saved for USER on instance 'NAME'`, or `Password updated for USER ...` when that user was already saved; both mean it worked.
   - If this is a new instance and other instances were already saved, ask whether it should be the default and, if so, run `fusion-mcp default --instance NAME`. If they say no, the current default stays as it is.
   - On `Login failed`, tell the user and run it again only when they ask, so a wrong password is not retried into a locked account. `Could not reach Fusion` means the URL or the network is the problem, not the password.
5. Register the server for the user: `claude mcp add fusion-bip --scope user -- <full path to fusion-mcp>` (`fusion-mcp.exe` on Windows). If `claude mcp list` already has a server named `fusion-bip`, run `claude mcp get fusion-bip` and compare its command with the path you just installed. If it points to another copy of this repo, it is an earlier install; otherwise it is a different server. Tell the user which it is and ask whether to replace it (`claude mcp remove fusion-bip --scope user`, then add again) or keep it and register this one under another name, such as `fusion-query`, using that name in the commands in this step. Confirm with `claude mcp get <name>` that it shows Connected.
6. Tell the user to close and reopen Claude Code, then ask a question about their Fusion data.

To add another user or instance later, the user can ask Claude Code to do it, which is step 4 again with the new names. For a new user on an instance that is already saved, leave out `--url`: run `fusion-mcp setup --instance NAME --user USER` and it reuses the saved URL; don't ask the default question in this case. Passing the same URL again also works, but a different URL is refused, so a saved instance is never silently repointed. Saving a URL and user that another instance already has is also refused, because the two would share one stored password; use the existing instance instead. Usernames are matched regardless of case. Both refusals happen before the password is read or a login is tried, so they never count against the account, and setup exits with code 1.

### Setting it up yourself

**Requirements:** Python 3.10 or later, and a Fusion account that can create data models in its own BI Publisher folder (the BI Publisher Data Model Developer or Author role).

```bash
git clone https://github.com/brianmakarewicz/fusion-nlq-mcp
cd fusion-nlq-mcp
python -m venv .venv
.venv/bin/pip install -e .          # Windows: .venv\Scripts\pip install -e .
```

This installs the `fusion-mcp` command.

### Option A (recommended): save instances and users in your OS keychain

```bash
.venv/bin/fusion-mcp setup --instance dev           # Windows: .venv\Scripts\fusion-mcp setup --instance dev
```

It asks for the Fusion URL (the address you use for Fusion, for example `https://<your-pod>.fa.<region>.oraclecloud.com`; a pasted Fusion page address is trimmed to that), the username and the password (typing is hidden), tests the login, and saves only if the login works. The password goes into the operating system's credential store (Windows Credential Manager, macOS Keychain, or the Linux Secret Service), never into a file. The instance names, URLs and usernames go into `fusion-mcp/config.json` under your user config folder. Passwords are stored by URL and username, so every install on the same computer account shares them: changing or forgetting a password in one changes it for all. Leave out `--instance` and the instance is called `default`.

The table below writes `fusion-mcp` for short; run it the same way, by its path inside `.venv`.

| Command | What it does |
|---------|--------------|
| `fusion-mcp setup --instance test` | Adds another instance (asks for its URL) |
| `fusion-mcp setup --instance dev --user hcm_reader` | Adds a user to an existing instance (no URL asked) |
| `fusion-mcp setup --instance dev --user fin_reader` | For a user already saved, changes the password |
| `fusion-mcp list` | Shows instances, URLs, users and defaults; never passwords |
| `fusion-mcp default --instance test [--user hcm_reader]` | Chooses what a call uses when it names no instance or user |
| `fusion-mcp forget --instance dev [--user hcm_reader]` | Removes a user, or a whole instance, and its keychain entries (it says which ones it kept because another instance uses them) |
| `fusion-mcp forget --all` | Removes everything (the usage log, if any, stays) |

The first instance and user you add become the defaults. A running server reads the saved connections on every call, so a new instance, user or password is used by the next query without restarting your MCP client. `--url` and `--user` can be given as options, and `--password-stdin` reads the password from standard input, so setup can be scripted.

In a terminal, `setup` asks for the password with a hidden prompt. Where there is no terminal (an AI agent running the command, or Git Bash), it opens a small password window instead, which needs Python's tkinter (included with the python.org installers; `python3-tk` on Linux). You can also pipe the password in with `--password-stdin`. `fusion-mcp --help` lists the commands.

Every saved user can be used by the agent through `instance` and `fusion_user`, so save only accounts whose access you are happy for the agent to have. To keep one session to a single instance, set `FUSION_MCP_INSTANCE` in that session's MCP config (for example a project-level `.mcp.json`); it then becomes that session's default instance, although the agent can still name others.

### Option B: several accounts, through your own credential helper

Use this if you already keep credentials in your own store. Write a `conn_helper.py` in a folder outside the repo that defines `get_fusion_url(pod)` and `get_fusion_user(name, pod)`, returning the URL and `(username, password)`. [examples/conn_helper_example.py](examples/conn_helper_example.py) keeps the passwords in the OS keychain and only the account names in a file. Then set:

| Variable | Value |
|----------|-------|
| `FUSION_MCP_HELPER_DIR` | The folder containing your `conn_helper.py` |
| `FUSION_MCP_USER` | The account name to use when a call does not name one |
| `FUSION_MCP_POD` | Optional; passed to your helper as `pod` when a call names no `instance` |

A call's `instance` is passed to your helper as `pod`, so a helper that understands several pods gives the same switching as option A.

Add an account with `<repo>/.venv/bin/python conn_helper.py add <name>` (Windows: `<repo>\.venv\Scripts\python`), using the full path to the repo's virtual environment, which has `keyring`. Remove one by deleting it from `accounts.json` and its keychain entry (service `fusion-bip-mcp-server-helper`); `fusion-mcp forget` does not touch helper accounts.

With option B the agent can name any account your helper knows through `fusion_user` (and any pod through `instance`), so only give the helper accounts you are happy for the agent to use.

### Option C (not recommended): plaintext environment variables

`FUSION_URL`, `FUSION_USERNAME` and `FUSION_PASSWORD` work, but the password then sits unencrypted in your MCP client's config file, where anything that can read your files can read it. It holds one connection only, so `instance` cannot be used. The server refuses `FUSION_PASSWORD` unless you also set `FUSION_MCP_ACCEPT_PLAINTEXT_PASSWORD=yes` to confirm you accept that risk.

### Logins and session tokens

The server logs in to BI Publisher once and reuses the session token for later queries. The password is sent only at that first login, and again only when Fusion reports that the token has expired, at which point the server logs in again from the same stored credentials and retries the query once. The token is kept in memory and never written to disk.

### Register it with your MCP client

After option A there is nothing to pass; just point the client at the command. `--scope user` makes the server available in every folder, not only the current one. Optionally set `FUSION_MCP_INSTANCE` in its `env` to choose that client's default instance.

Claude Code:

```bash
claude mcp add fusion-bip --scope user -- /path/to/fusion-nlq-mcp/.venv/bin/fusion-mcp
```

Claude Desktop (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "fusion-bip": {
      "command": "/path/to/fusion-nlq-mcp/.venv/bin/fusion-mcp"
    }
  }
}
```

On Windows the command is `.venv\Scripts\fusion-mcp.exe`. For option B, add the `FUSION_MCP_*` variables to the client's `env` settings.

### Usage log

Every call appends one line to `metering.jsonl` in the same `fusion-mcp` config folder (set `FUSION_MCP_METER_LOG` to move it). It records the time, tool, duration, result size and outcome; for errors it keeps only the error type and ORA- code. It stores only the length of the SQL, not the SQL itself, and never stores result data.

### Which credentials are used

The server checks in this order and uses the first that is set: a credential helper (`FUSION_MCP_HELPER_DIR`), then `FUSION_PASSWORD` (option C), then the saved instances from `fusion-mcp setup`. A leftover `FUSION_PASSWORD` therefore takes precedence over saved instances.

If a login fails for any reason other than Fusion being unreachable, the server stops trying that user with the same password for five minutes, so that an agent retrying in a loop cannot lock the account. Update the password (`fusion-mcp setup --instance NAME --user NAME`) and the next call tries the new one; other instances and users are not affected.

The server runs over stdio only, started by your MCP client. It has no network listener and does no caller authentication of its own.

## Tests

```bash
.venv/bin/pip install -e ".[test]"   # Windows: .venv\Scripts\pip install -e ".[test]"
.venv/bin/pytest                     # Windows: .venv\Scripts\pytest
```

The tests run offline; they never contact Fusion or touch your saved instances or keychain.

## How it fits together

- `server.py`: the MCP server; registers the tools and their descriptions.
- `direct_client.py`: the query, run against BI Publisher SOAP.
- `soap.py`: builds the SOAP requests and reads Fusion's responses and errors.
- `builders.py`: checks the SQL and builds the temporary data model.
- `context.py`: finds the credentials for a call (helper, environment, or saved instances).
- `credentials.py`: the saved instances and users, the `setup`, `list`, `default` and `forget` commands, and the OS keychain storage.
- `errors.py`: the error types the tools raise.
- `metering.py`: the usage log.

## License

MIT. See [LICENSE](LICENSE).
