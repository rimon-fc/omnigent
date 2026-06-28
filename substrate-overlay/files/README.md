# Substrate

Substrate is an open-source AI agent framework and meta-harness: one common
layer for running coding agents — Claude Code, Codex, Cursor, Pi, and your own
YAML-defined agents — on your own machine, with policies and sandboxing.

This README covers **local install and getting started**.

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) and `git`
- *(optional)* Node.js 22+ — for the Claude / Codex / Pi harnesses
- *(optional)* `tmux` — for the native `substrate claude` / `substrate codex` terminals
- *(optional, Linux only)* `bubblewrap` (`bwrap`) — sandbox for native terminals
  (macOS uses its built-in sandbox)

## Install (local)

From a clone of this repository:

```bash
cd substrate
uv tool install .            # or for development:  uv pip install -e .   (or  pip install -e .)
```

This puts the `substrate` command on your PATH.

## Get started

Pick a model/provider once — credentials are stored locally under `~/.substrate`:

```bash
substrate setup
```

Start a session in your terminal. This also opens a local web UI at
http://localhost:6767 showing the same session:

```bash
substrate
```

Launch a specific harness, or your own agent:

```bash
substrate claude                   # Claude Code
substrate codex                    # Codex
substrate run path/to/agent.yaml   # your own agent
```

Two example agents ship with the repo:

```bash
substrate run examples/polly/      # multi-agent coding orchestrator
substrate run examples/debby/      # two-headed (Claude + GPT) brainstorming partner
```

Prefer the browser? Run the local server and register your machine as a host:

```bash
substrate server start             # local server + web UI, in the background
substrate host                     # (separate terminal) register this machine
```

Stop everything with `substrate stop`.

## Configuration

All per-user state lives under `~/.substrate` (config, credentials, logs).
Environment variables use the `SUBSTRATE_` prefix.

## License

Apache-2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).
