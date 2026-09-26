# First recall

For an agent given this repository's URL. After a brief explanation, offer the concrete demo
setup below unless the user asked to stay with a review or discussion. You check prerequisites
and ask the human once. Only after approval do you install into
a folder of its own, register a demo server and make a first recall over a synthetic Git history.
This first connection covers the demo only.

## 1. Check without changing anything

- `git --version`: the demo builds its history with git.
- `python --version` (or `python3`): 3.12 is tested; other versions are untested.
- Your client: `claude --version` for Claude Code, `codex --version` for Codex.
- `claude mcp get recall-demo` or `codex mcp get recall-demo`: if it is already registered,
  tell the human instead of adding a second one.
- The repository is private for now: `git ls-remote https://github.com/cog-astra/memory-happens`
  must succeed. If it fails, tell the human that access is needed, and stop.

## 2. Ask once, before any change

Propose a folder for `<clone>`. Tell the human the following and wait for a yes:

> I will:
> 1. clone memory-happens into `<clone>`;
> 2. create a Python environment in `<clone>/.venv` and install `mcp` and `pydantic` into it,
>    leaving the system Python unchanged;
> 3. register an MCP server `recall-demo`: in Claude Code for this project only (`~/.claude.json`),
>    in Codex for all sessions (`~/.codex/config.toml`).
>
> The demo reads only a Git history that it generates in a temporary folder.
> It does not read your files or sessions, use the network or call a model.
> To undo: `claude mcp remove recall-demo -s local` (or `codex mcp remove recall-demo`), then
> delete `<clone>`. Normal server shutdown removes its temporary history, but a client that
> terminates the server can leave a `recall-demo-*` folder in the temporary directory.

## 3. Install

```sh
git clone https://github.com/cog-astra/memory-happens.git <clone>
cd <clone>
python -m venv .venv
```

The environment's Python is `<clone>/.venv/Scripts/python.exe` on Windows and
`<clone>/.venv/bin/python` elsewhere. Below, `<python>` is its absolute path, written with
forward slashes on Windows. `<server>` is the absolute path of `<clone>/recall-traces/scripts/recall_mcp.py`.

```sh
<python> -m pip install -r recall-traces/requirements.txt
cd recall-traces/scripts
<python> -m unittest test_operations
```

The tests use temporary synthetic repositories. If `venv` is missing
(some Linux distributions package it separately), tell the human which package is needed.
Do not install system packages yourself. Do not start `recall_mcp.py` by hand: it is a stdio
server and waits silently for a client.

## 4. Register

In Claude Code, run this from the folder where the human works:

```sh
claude mcp add recall-demo -- <python> <server> --demo
claude mcp get recall-demo
```

The output should show `Status: ✔ Connected`.

In Codex:

```sh
codex mcp add recall-demo -- <python> <server> --demo
codex mcp get recall-demo
```

## 5. First recall

MCP tools load when a session starts. If `operation_catalog` is not among your tools now, say
so plainly: registration is done, and a new session will have the tools. In Claude Code, start
that session in the same folder. Do not report a recall you could not run.

Use a new session with the same client profile after registration. If its tools are still
unavailable, report that connection problem; an ad hoc SDK script does not verify the client's
MCP connection.

In a session with the tools, ask: *why was the lookup cache removed?* The demo history contains
a cache that was added and later removed. A good answer uses `operation_catalog` and
`operation_invoke` to list the history, select candidates and read the patch. It names the
commit that removed the cache and explains the reason recorded there. It also says what it read.

## Beyond the demo

The experimental `--repo` mode can return more history and patch data than an agent can
practically pass between calls. It is not part of this first-connection path yet.

Recall over session archives, notes and project memory needs more setup; see
[Install and test](README.md#install-and-test).

If a step fails or is unclear, open an issue. Say what you ran and what you saw.
