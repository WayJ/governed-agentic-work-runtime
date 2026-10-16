# Local operations GUI

Updated: 2026-10-16 (layout & usability enhancements) · The read-only HTTP API the GUI consumes is documented by the backend owner in `docs/gui-api.md`.

An offline, dependency-free browser interface over the durable records of an existing store. It displays what the runtime actually recorded — states, obligations, evidence, decisions, operations and events — and never writes to the store. There is no CDN, framework, build step or network access: the HTML/CSS/JS assets ship inside the package and are served from the same loopback origin as the API.

## Visual contract (S7)

The viewer applies the project design reference through centralized CSS custom properties defined once in `work_runtime/web/app.css` (`--color-*`, `--radius-*`, `--space-*`, `--font-*`, `--tracking-*`, `--content-max`); components reference tokens, never repeated literals. The applied grammar: warm cream canvas `#f7f7f4`, warm ink `#26251e`, body text `#5a5852`, white cards with 1px `#e6e5e0` hairlines and no drop shadows, 8px control / 12px card radii, a 4px spacing scale, tile values 26px and work titles 22px at weight 400 with negative tracking in Latin scripts only (Chinese tracking is forced to zero via `:lang(zh)`), labels 16px/600, body 14–16px, and code/raw JSON at 13px in locally available JetBrains Mono with a system monospace fallback — nothing is bundled or fetched.

The single brand orange `#f54e00` is deliberately a scarce **non-text** accent: the brand mark and the 2px keyboard-focus ring (3.52:1 against white cards, ≥3:1 non-text). The primary refresh control uses ink on cream (14.33:1); orange is never used for text or control labels (white/orange is only 3.52:1, ink/orange 4.37:1 — both below 4.5:1).

Measured adaptations for an operations tool (documented deviations from the reference):

- **Semantic status colors are measured adaptations.** Success `#146c4e` (≥5.58:1 on its tint; the reference `#1f8a65` measures 4.30:1 on white and was darkened), warn `#8a5400` (5.55:1 on its tint) and error `#b32449` (5.45:1 on its tint; reference `#cf2d56` drops to 4.27:1 there) — every status/error text pair measures ≥4.5:1 on its actual rendered surface, and status meaning always stays in the text itself, independent of color. Chips have a neutral base (`#eceae4` with ink, 12.78:1), so status classes the stylesheet never anticipated — statuses are stored, dynamically discovered strings — always render legibly.
- **No AI-timeline pastels.** This store records real operations and events; no thinking/grep/read/edit stages exist, and the reference's timeline palette is not used for statuses.
- **Operations density instead of marketing rhythm.** Compact 4–24px panel spacing, no hero typography or 80px section bands; the top dashboard summary band sits above a two-pane operations view (list + detail) that collapses to one column below 1024px with content capped at 1200px.
- **Touch targets ≥44px** on every actionable control — buttons, tabs, work items, inputs and raw-data disclosures (the reference CTA is 40px).
- **No document-level overflow hiding.** Long identifiers and raw payloads wrap (`overflow-wrap: anywhere`) or scroll inside their own surfaces (`.table-wrap`); the page itself never conceals horizontal overflow, verified at 390px and 320px.

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

- **Top dashboard summary band** (`#tiles` + `#counts` above `.layout`): five metric tiles across the top (open works; closed·succeeded; closed·cancelled; uncertain operations; pending evidence) with their definitions, paired with a compact durable-table inventory bar (`works`, `events`, `operations`, `evidence`, `commands`, `attempts`). Lifting the summary band above the two-pane workbench aligns the work list and detail inspector at the same vertical top and keeps all five seeded works in frame at 1280×900.
- **Work list**: framed in a dedicated navigator card with search by id or owner, status filter, bilingual scenario summaries for the five seeded `ui-demo` works, and keyboard navigation (`↑`/`↓` to move, `Enter` to select; `/` focuses search). When no work is selected yet, the right pane displays an interactive store quick-start guide (`#placeholder-guide`) so operators can jump into any work with one click.
- **Detail sections**: overview (with a clickable four-card KPI summary strip jumping to Requirements, Evidence, Operations, and Decisions, plus two-column structured cards for Lifecycle & ownership and Contract & revisions, followed by Waits and Cancellation), current requirements, evidence, operations with attempts, persisted command decisions, the event timeline (keyset-paginated with *load more*), and the exact stored documents as text.
- **Revoked-evidence notice** (S8): when a **closed** work currently has revoked evidence, a neutral bilingual notice appears under the detail header. It keeps the two truths separate: the historical closure and its outcome stay exactly as recorded (nothing is reopened or rewritten), while the revoked evidence only changes *current* status — it no longer counts as valid proof for current requirements. When the completion record actually cited now-revoked proof ids, the notice shows that derived count and the exact ids; a cancelled closure acknowledged operations instead and never shows an invented citation count. Its two buttons jump to the Evidence and Events tabs, where the revoked chip renders the stored status text on the measured error tokens.
- **Language**: English/Chinese with the browser language as default and an explicit toggle.
- **Refresh**: manual refresh always works; automatic polling every 5 seconds can be paused and resumed. The header shows the store basename, schema version and the sampling time — when the page last read the store, which is an observation time, never a business-event time.
- **States**: loading, empty, error and disconnected are shown explicitly; after a disconnect the viewer keeps retrying.

## What the GUI deliberately does not do

- **It never interprets stored payloads for you.** Document, plan, completion, evidence-data, event-body and receipt fields are shown as the exact stored JSON text. The page renders them as text only (no `innerHTML`, no re-parsing of raw payload strings), so stored content can never execute and integers beyond the JavaScript safe range survive exactly.
- **It never confuses current obligations with history.** The requirements section shows the *current* contract requirements; the decisions section shows *persisted command receipts* — admissions of decisions at their time, not external effects — including their historical blockers. External ids are displayed as text, never as clickable links.
- **It never parses the closure record to count citations.** The revoked-evidence notice reads only the API's derived `revoked_evidence` / `completion_revoked_evidence_ids` fields; `completion_raw` stays exact stored text on the Documents tab.
- **It never claims cancellation reverses anything.** A cancelled closure shows the acknowledged external effects that remain in place.
- **It is a local trust tool, not a service.** Binding to loopback is convenience, not authentication; there is no tenant model, no write API and no remote hosting. The server opens the store read-only.

## Verification

`scripts/verify_install.py` asserts the web assets ship inside a fresh install and — when the read-only backend module is assembled into that install — drives the installed module and console `ui-demo`/`ui` entry points as real subprocesses outside the checkout: real HTTP fetches of the assets and API endpoints, byte-equality with the packaged assets, the five seeded works, store tables byte-identical before and after serving, and a clean exit on interrupt. When the backend is not part of the build the stage prints an explicit SKIPPED line and the final summary discloses it. Interactive browser behavior (layout, keyboard, bilingual toggle, stored-XSS and precision fixtures in a real browser) is verified against the assembled backend by independent integration, not by this slice's unit tests.

## Related

- [Verification coverage](verification.md) — what is verified and what is not.
- [README](../README.md) · [Contributing](../CONTRIBUTING.md)
