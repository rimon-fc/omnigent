# omni-keel-test — Voyager

A **multi-agent SUBSTRATE** travel concierge that drives the **co-consult KEEL
MCP server**. This is the "build with KEEL, run in SUBSTRATE" pattern from
`../DIFF_KEEL_OMNI.MD §8` made concrete: KEEL supplies the governed travel
tool surface (real Sabre / Expedia / SerpAPI / LIVN search flows); SUBSTRATE
supplies the brains, the orchestration, and the multi-agent fan-out.

## Architecture

One specialist per **upstream provider family** (Sabre / EAN / LIVN / Serp):

```
              ┌───────────────────────────────────────────┐
 you ───────▶ │  voyager  (orchestrator · claude-sdk)      │
              │  parses brief · creates trip record ·      │
              │  fans out · merges · assembles proposal    │
              └──┬────────────┬────────────┬───────────┬───┘
   sys_session_  │            │            │           │
        send  ┌──▼──────┐ ┌───▼────┐ ┌─────▼──────┐ ┌──▼──────┐
              │ flights │ │ stays  │ │experiences │ │ context │
              │claude   │ │claude  │ │codex       │ │ claude  │
              │-sdk     │ │-sdk    │ │-native (xv)│ │ -sdk    │
              └────┬────┘ └───┬────┘ └─────┬──────┘ └────┬────┘
                   │ type: mcp│            │             │
                   └──────────┴────────────┴─────────────┘
                                  │ stdio (bash co-consult/run.sh)
                       ┌──────────▼───────────────────────────┐
                       │  co-consult KEEL server               │
                       │  Sabre  → search_flights              │
                       │  EAN    → resolve_region, search_hotels│
                       │  LIVN   → search_activities           │
                       │  Serp   → fare_insights,              │
                       │           destination/map/web/reviews_context
                       │  + run_flow · build_proposal ·        │
                       │    create_trip / get_trip / update_trip│
                       └───────────────────────────────────────┘
```

- **`voyager`** (`config.yaml`) — orchestrator. Holds the full `co_consult`
  surface for trip-record CRUD and final `build_proposal` assembly; delegates
  every search to a specialist; never searches itself.
- **`flights`** (`agents/flights/`) — **Sabre**: `search_flights`.
- **`stays`** (`agents/stays/`) — **Expedia/EAN**: two-step `resolve_region` →
  `search_hotels`.
- **`experiences`** (`agents/experiences/`) — **LIVN**: `search_activities`.
  Runs on **codex-native** (your authenticated `codex` CLI) for a cross-vendor
  perspective — no OpenAI API key needed.
- **`context`** (`agents/context/`) — **Serp/Google**, all five enrichment
  flows: `fare_insights`, `destination_context`, `map_context`, `web_context`,
  `reviews_context`. Advisory only.

Because fares come from Serp (not Sabre), `flights` returns itineraries and
`context` returns the fare trend for the route — **voyager merges the two** when
presenting flights.

Each specialist declares the **same** co-consult MCP server (narrowed to its
provider's tool list) and launches it as its own stdio process, so each gets
its own isolated KEEL session state.

## How the KEEL server is wired in

SUBSTRATE declares the KEEL server as a standard MCP tool — no code, just spec.
These specs use the **HTTP** transport: start one co-consult server, and all
five specs point at it:

```yaml
tools:
  co_consult:
    type: mcp
    url: http://127.0.0.1:8000/mcp
    tools: [search_flights]    # specialists narrow; voyager omits to get all
```

`co-consult/run.sh http` sets `PYTHONPATH` to the keel + LAP source, loads
`co-consult/.env`, mints a Sabre OAuth token, then serves
`http://127.0.0.1:8000/mcp`.

> **Prefer zero setup?** Swap `url: http://127.0.0.1:8000/mcp` for
> `command: bash` + `args: [<abs path>/co-consult/run.sh]` and substrate
> auto-launches a stdio keel server per agent — no separate server to start.
> The HTTP form here trades that for a single shared server.

## Prerequisites

1. **SUBSTRATE installed** with credentials configured (`substrate setup`).
   **No API keys required** — this system runs on subscriptions / authenticated
   CLIs:
   - `voyager`, `flights`, `stays`, `context` → `claude-sdk`, backed by your
     **Claude Pro/Max subscription** (the logged-in `claude` CLI).
   - `experiences` → `codex-native`, backed by your authenticated **`codex`
     CLI** (ChatGPT/Codex subscription).

   In `substrate setup`, add a **🎟️ Subscription** credential for each (it picks
   up your already-logged-in `claude` / `codex` CLIs). To run everything on the
   Claude subscription, change `experiences`'s harness to `claude-sdk`.
2. **co-consult credentials**: fill in
   `../keel-usage-tests-etc/co-consult/.env` (copy from `.env.example`). The
   KEEL server's tools load even without keys, but live searches need real
   Sabre / Expedia / SerpAPI / LIVN credentials.
3. **co-consult runtime deps** as used by its `run.sh`: `python3` on PATH with
   the keel + LAP source present (they are, two levels up at `mcp-world/keel`
   and `mcp-world/LAP-main`), and `node`/`npx` for the LIVN `mcp-remote` bridge.

## Run

**Step 1 — start the co-consult KEEL server** (separate terminal, leave it running):
```bash
cd ../keel-usage-tests-etc/co-consult && ./run.sh http   # → http://127.0.0.1:8000/mcp
```

**Step 2 — start Voyager:**
```bash
cd ../../omni-keel-test     # back to this folder
./run.sh                    # interactive REPL  (or: substrate run .)
./run.sh server             # web UI → http://localhost:6767
```

Then ask, e.g.:

> Plan a 6-night trip from Brisbane to Bali for 2 adults, 12–18 July, economy.

Voyager parses the brief, creates a trip record, dispatches `flights`, `stays`,
`experiences`, and `context` in parallel, collects their results via the inbox,
and assembles a proposal with `build_proposal`.

## Notes & gotchas

- **Two governance layers (by design).** KEEL enforces its own guardrails
  (injection blocker, PII redaction, stage gating) server-side; SUBSTRATE adds
  runtime guardrails here (`spawn_bounds` caps fan-out at 4/turn — one per
  specialist). See `../DIFF_KEEL_OMNI.MD §8.6`.
- **Shared HTTP server.** All five specs point at the one
  `http://127.0.0.1:8000/mcp` you start in Step 1 — so it must be running before
  `substrate run`, and the agents share that keel server (each MCP connection
  still negotiates its own `Mcp-Session-Id`, so per-session state stays
  separate). For a per-agent process with zero manual startup instead, use the
  stdio form (see the callout under "How the KEEL server is wired in").
- **Endpoint, not path.** The specs reference the URL
  `http://127.0.0.1:8000/mcp`. If you serve co-consult on a different host/port,
  update the `url:` in all five config files.
- **Faithful to co-consult.** Tool names and call shapes (IATA codes, leg
  arrays, EAN occupancy, two-step hotel resolve) mirror co-consult's own
  `agent.yaml` instructions.
