# Local operations GUI

Updated: 2026-10-14 (S5 frontend/CLI slice) · The read-only HTTP API the GUI consumes is documented by the backend owner in `docs/gui-api.md`.

An offline, dependency-free browser interface over the durable records of an existing store. It displays what the runtime actually recorded — states, obligations, evidence, decisions, operations and events — and never writes to the store. There is no CDN, framework, build step or network access: the HTML/CSS/JS assets ship inside the package and are served from the same loopback origin as the API.

## Start it

```bash
python3 -m work_runtime ui-demo                 # seed a five-work sample store, then serve it
python3 -m work_runtime ui --db <existing.sqlite> [--port N]   # serve an existing store
work-runtime ui-demo / work-runtime ui ...      # console entry points behave the same
```

The command prints the actual local URL (for example `http://127.0.0.1:51736/`) as soon as the server binds — an ephemeral port unless `--port` is given (0–65535) — and serves until interrupted; `Ctrl-C` shuts it down cleanly. Startup failures (missing database, port out of range, unreadable store) exit 2 with a bounded message and never touch the store. The read-only backend is a separate module; in an install without it the `ui` commands report that honestly and exit 2, and every other CLI command keeps working.

## The sample store

`ui-demo` seeds one fresh expense-family store through real commands and the real persistent FakeOA — no direct SQL state writes, no fabricated fields — with five works on distinct invoices:

| Work | Final state | What it shows |
|---|---|---|
| `wait-1` | waiting | A durable wait on the approval rule; the submitted approval evidence is still pending verification; an earlier proposal persists as a rejected decision |
| `uncertain-1` | needs_attention | The external service accepted, the response was lost, and an unavailable lookup escalates to `NO_AUTHORITATIVE_RESULT` — the effect stays in the external store |
| `transfer-1` | active, owner `delegate` | Ownership transfer invalidated the prepared intent; the new owner's proposal readmitted the same operation, which then succeeded |
| `succeed-1` | closed, succeeded | Evidence-backed completion after a confirmed external acceptance |
| `cancel-1` | closed, cancelled | Cancellation that first reconciles the uncertain effect, then acknowledges the exact confirmed external effect — recorded, not reversed |

Every run seeds a brand-new folder under `--directory` (or the system temporary directory); existing data is never modified or deleted. The seeded external store holds exactly four accepted applications and zero reversed effects.

## Reading the screen

- **Metric tiles** (with their definitions shown under each): open works; closed·succeeded; closed·cancelled; uncertain operations (dispatched + outcome-unknown); pending evidence. The chip row below lists raw record counts (works, events, operations, evidence, commands, attempts) straight from the summary.
- **Work list**: search by id or owner, filter by status, and select with the keyboard (`↑`/`↓` to move, `Enter` to select; `/` focuses search).
- **Detail sections**: overview (status, contract, waits, cancellation), current requirements, evidence, operations with attempts, persisted command decisions, the event timeline (keyset-paginated with *load more*), and the exact stored documents as text.
- **Language**: English/Chinese with the browser language as default and an explicit toggle.
- **Refresh**: manual refresh always works; automatic polling every 5 seconds can be paused and resumed. The header shows the store basename, schema version and the sampling time — when the page last read the store, which is an observation time, never a business-event time.
- **States**: loading, empty, error and disconnected are shown explicitly; after a disconnect the viewer keeps retrying.

## What the GUI deliberately does not do

- **It never interprets stored payloads for you.** Document, plan, completion, evidence-data, event-body and receipt fields are shown as the exact stored JSON text. The page renders them as text only (no `innerHTML`, no re-parsing of raw payload strings), so stored content can never execute and integers beyond the JavaScript safe range survive exactly.
- **It never confuses current obligations with history.** The requirements section shows the *current* contract requirements; the decisions section shows *persisted command receipts* — admissions of decisions at their time, not external effects — including their historical blockers. External ids are displayed as text, never as clickable links.
- **It never claims cancellation reverses anything.** A cancelled closure shows the acknowledged external effects that remain in place.
- **It is a local trust tool, not a service.** Binding to loopback is convenience, not authentication; there is no tenant model, no write API and no remote hosting. The server opens the store read-only.

## Verification

`scripts/verify_install.py` asserts the web assets ship inside a fresh install and — when the read-only backend module is assembled into that install — drives the installed module and console `ui-demo`/`ui` entry points as real subprocesses outside the checkout: real HTTP fetches of the assets and API endpoints, byte-equality with the packaged assets, the five seeded works, store tables byte-identical before and after serving, and a clean exit on interrupt. When the backend is not part of the build the stage prints an explicit SKIPPED line and the final summary discloses it. Interactive browser behavior (layout, keyboard, bilingual toggle, stored-XSS and precision fixtures in a real browser) is verified against the assembled backend by independent integration, not by this slice's unit tests.

## Related

- [Verification coverage](verification.md) — what is verified and what is not.
- [README](../README.md) · [Contributing](../CONTRIBUTING.md)
