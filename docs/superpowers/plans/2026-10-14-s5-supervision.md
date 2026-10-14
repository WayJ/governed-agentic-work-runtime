# S5 GUI Implementation and Supervision Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement scoped plans task-by-task. Steps use checkbox syntax. Coordinator uses Orca Claude Code workers; no nested agents.

**Goal:** Make durable work history inspectable in a real offline browser.

**Architecture:** Existing SQLite read-only inspector exposes ratified DTO through loopback HTTP. Packaged vanilla assets consume it; CLI and real-command seed supply a reproducible trial. Independent integration validates assembled behavior and owns release.

**Tech Stack:** Python >=3.9 standard library, unittest, vanilla HTML/CSS/JS; zero runtime dependencies.

**Spec:** [D25 design](../specs/2026-10-14-s5-gui-design.md), [S5](../sprints/2026-10-14-S5-plan.md).

## Global Constraints

Do not change Runtime/policies/adapters/core baselines. No new runtime deps or CDN. All behavior changes observed meaningful RED then minimal GREEN, scoped commits with commands/evidence. Existing checkout and ownership only; no nested workers/local approval UI. All merges/pushes belong to integration session.

## Review Focus

- Malformed SQL JSON/types, legacy absent owner and DB lock: backend bounded errors, no writes.
- Opaque Unicode/slash/quote IDs, huge integer/revisions and paged events: backend exact fields and frontend text, no rounding.
- Duplicate Host/Origin/query and unexpected HTTP method/absolute target: backend rejects safely with accurate headers.
- Stored HTML/script/URL strings: frontend actual browser proves no execution or unsafe href.
- Interrupted/disconnected/stale refresh and narrow keyboard use: frontend state behavior tested in actual browser, no stale selected-work race.

## Task 1 — read-only backend

**Files:** inspection.py, ui_server.py; tests/test_inspection.py, tests/test_ui_server.py; docs/gui-api.md; scoped own plan/report.
**Interfaces:** ReadOnlyInspector(path).summary/list_works(limit=100,offset=0)/work_detail(work_id)/events(work_id,after=0,limit=100); GuiReaderError(code,message); make_ui_server(db_path,port=0). API list uses `works` field per builder report; D25 overrides report omissions/precision/raw claims. Routes and error codes exactly design.

- [ ] Write scoped writing-plans plan with exact unittest assertions for each reader/HTTP behavior and Review Focus; include RED/GREEN commands.
- [ ] Observe failing real SQLite/read-only/WAL/precision/pagination tests; implement minimal reader; rerun GREEN and commit.
- [ ] Observe failing real HTTP routing/Host/Origin/method/query/header tests; implement whitelist server; static assets may be unavailable until Task2 (bounded response), never create placeholder assets in backend scope; rerun GREEN and commit.
- [ ] Public API docs settle all DTO fields; compare spec, all core tests and docs/syntax; report immutable tip and evidence.

## Task 2 — interface and trial

**Files:** work_runtime/web/{index.html,app.js,app.css}, cli.py, ui_demo.py; tests/test_ui_demo.py and scoped CLI tests; pyproject.toml, scripts/verify_install.py, CI only if needed; docs/gui.md, README.md, README.zh-CN.md, CONTRIBUTING.md, docs/verification.md; scoped plan/report.
**Interfaces:** Consume Task1 exact reader/server + D25. Produce seed_ui_demo(directory=None)->DB path; ui --db existing --port and ui-demo --directory/--port; five work IDs per design. Do not import missing backend eagerly for prior CLI commands while developing; no backend edits/merges by dev owner.

- [ ] Write scoped plan with exact state/assertion tests and real browser proof commands.
- [ ] Observe RED seed/CLI tests, implement real command seed and bounded lifecycle/server shutdown. Verify GREEN states and retained effects, no direct SQL state fabrication; commit.
- [ ] Implement accessible light bilingual assets against settled DTO with text-only payloads, list/filter/detail/pagination, polling pause and robust refresh selection. Browser behavioral RED/GREEN when assembled; no fake DOM/source keyword tests.
- [ ] Package assets; extend installed verifier using actual module AND console subprocesses outside checkout, assets/API/readonly snapshots and shutdown; report exact completed checks vs pending assembled checks.

## Task 3 — independent integration

**Files:** acceptance/ledger/closing evidence, integration report; product corrections remain original owners.
**Interfaces:** Assemble immutable owner tips into CURRENT carrier preserving docs. Independent review including actual browser desktop/narrow/offline/XSS/precision/errors, all baselines and installed HTTP. Integration alone owns normal merges and non-force push.

- [ ] Source review and actual tests of each owner; route defects to master, do not self-fix product code.
- [ ] Assemble reviewed tips, run all six scenarios, exact five E5 DoD bullets; append acceptance before main merge.
- [ ] Ordered merge gates, capture pre-main tip, main merge, safe carrier teardown, ledger/closing report; ordinary push and actual finalSHA CI/remote equality.
- [ ] Report hashes, actual counts/URLs, browser evidence and preview instructions then worker_done/idle. Master opens usable main preview and continues roadmap.

Self-review: tasks cover every spec section, ownership disjoint, exact signatures from D25, five Review Focus classes allocated. Each owner elaborates its independently testable implementation plan before code.
