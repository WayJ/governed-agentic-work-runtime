# S11 W2 demo development — rotation-demo, CLI, installed verification — report

Worker: S11 DEMO/INSTALL DEVELOPMENT (this checkout `s11-rotation-demo`,
branch `WayJ/s11-rotation-demo`). Date: 2026-10-15. Baseline asserted exact
and clean at start: carrier tip `d40636e36586658c6a229444461732baecab9263`
(the S11 core integration review's assembled note). Must-reads read before
coding: the core integration review (W2 stable API section) and the core
report; AGENTS `doc_sync_map` (no row owed by any file I touched); the S11
sprint, E11 roadmap, RFC-003 §3 D16, and the full design spec §7/§8/§9 with
the MASTER ratification D49–D53 over DRAFT. Scope honored: new
`work_runtime/rotation_demo.py`; narrow `rotation-demo` subcommand in
`work_runtime/cli.py` (existing `--directory` demo pattern); one new
module+console proof stage in `scripts/verify_install.py`; new
`tests/test_rotation_demo.py` (demo, CLI and installer-proof classes);
bilingual README entries; additive `docs/verification.md` coverage riding the
same commits as the tests it names; scoped plan; this report.
`work_runtime/ingress.py` and every other protected path byte-identical
(`git diff d40636e..HEAD` over the protected set is empty); no merge, no
push, no sprint state flip, no acceptance record, no roadmap/ledger change.
Python ≥3.9 stdlib only, schema stays `1`, zero dependencies.

Plan: `docs/superpowers/plans/2026-10-15-s11-demo.md`, committed `ca26c7c`
**before** code, executed inline with superpowers executing-plans + TDD (no
subagents — the dispatch forbids extra agents; the sprint independently
schedules the fresh final acceptance, so this is not the last pair of eyes on
the branch).

## Commits

| commit | subject |
|---|---|
| `ca26c7c` | docs: scoped S11 W2 rotation-demo implementation plan |
| `0228ff5` | feat: S11 rotation-demo — dual-key window, grace boundary, retired refusal, verbatim cache, history digest (S11 demo wave) |
| `bd3a229` | feat: rotation-demo CLI subcommand (S11 demo wave) |
| `d3e75fd` | feat: independent installed rotation-demo proof, module and console stages (S11 demo wave) |
| (this commit) | docs: S11 W2 demo development report |

`bd3a229` is an amend of a first `a1a1282` that had landed the CLI test
without its `docs/verification.md` sentence (an edit anchor mismatched); the
amend restores the same-commit doc pairing the design §8 rule requires — the
ledger records the ruling. Every test-adding commit carries its verification
paragraph update in the same commit.

## What was implemented (design §7 SKR-10, D53)

- **`work_runtime/rotation_demo.py`** — no-credentials
  `python3 -m work_runtime rotation-demo`, deterministic through an injected
  mutable-holder clock (`T0 = 2000000000`, `grace = 300 == max_age`) and
  ephemeral in-memory keys (`secrets.token_bytes(32)` — only key ids
  `finance-2026-08`/`finance-2026-10` are ever printed). Fresh
  `mkdtemp("governed-rotation-")` store per run, work `rotate`, evidence-only
  (no dispatch). The frozen W1 core is used exactly through the stable API
  the integration review documents: `SourceKey`, `SignedEvidenceGateway`,
  `sign_evidence`, `SIGNED_FIELDS`, `OPTIONAL_KEY_FIELD`, `CODE_KEY_RETIRED`;
  rings are lists with exactly one `current`; one clock per record (the
  core's single post-HMAC sample) drives window and freshness together.
  Narrative, every step asserted in-module: dual-key window accept (K1-cited
  and K2-cited approvals both accepted) → `verify_pending` (last legitimate
  writes; both `verified`) → **rotate** (fresh gateway over the rotated ring;
  reconstruction writes nothing) with the clock **at** the inclusive grace
  boundary where the key-window edge and the original envelope's freshness
  edge coincide → the **original** envelope replay returns the **original
  cached receipt verbatim**, zero writes → one second past grace the same
  envelope is refused the exact minimal
  `{"decision": "rejected", "code": EVIDENCE_KEY_RETIRED}` (window precedes
  freshness; the cached receipt is unreachable behind authentication), zero
  writes → re-sign under the new key with the **same command id** and same
  business payload (fresh timestamp) returns the original cached receipt
  byte-verbatim, no new command row, zero writes → **new command id**, same
  event: accepted with the **current** status (`verified`), exactly
  `commands +1`, no new evidence row → six-table digest after all steps.
  Closing line (asserted by tests, the CLI and the installer):
  `1 scenario; dual-key accepts: 2; retired refusals: 1 (zero writes); cached
  receipts verbatim: 2; new commands: 1; history rewritten: 0`, then the
  usual `inspect --db … --work rotate` line.
- **`work_runtime/cli.py`** — narrow `rotation-demo` subcommand
  (`--directory` only), nothing else changed; unknown subcommands still exit 2.
- **`scripts/verify_install.py`** — `require_rotation_proof(stdout, source)`
  plus stages 19–20 (module then console, outside the checkout), part of the
  **existing installer evidence, not a new global gate**. The proof never
  trusts stdout for state: it requires the exact final line, the printed
  before/after digests and one printed store, then reads the real SQLite
  store — six-table digest **recomputed locally** (stdlib sqlite3+json+
  hashlib, same canonicalization) and matched against the printed digest
  (and differing from the before-rotation digest), exactly two verified
  approval rows with locally recomputed source-event fingerprints and
  document digest, exactly 6 command rows with each rotation command id
  exactly once by `finance`, the `cmd-rotation-k1` stored receipt still the
  **original** `accepted`/`pending_verification` receipt citing the
  `evt-rotation-1` evidence id, zero operations, 4 events, metadata exactly
  `('schema_version','1')` — and re-runs the printed inspect command
  verbatim expecting `"status": "active"`. Docstring stage list renumbered
  (19/20) and the PASS summary extended.
- **`tests/test_rotation_demo.py`** — 15 tests: `RotationDemoTests` (7,
  store-reading: fresh store, evidence rows/statuses/fingerprints/document
  digest recomputed locally, exact command rows with the original cached
  receipt, table counts and work state, printed-final-digest equality,
  narrative pins incl. **no 64-hex token anywhere in the output**, run
  repeatability), `RotationDemoCliTests` (1: module CLI exit 0 + final line),
  `VerifyInstallRotationProofTests` (7: pass-on-real-output; negatives —
  missing final line, flipped evidence status, deleted evidence row, forged
  duplicate command row, tampered cached receipt, digest-only store
  mutation).
- **`README.md` / `README.zh-CN.md`** — bilingual `rotation-demo` sections
  (command, prose, full transcript, per-store count assertions), truthful
  limitations (config-only trust; no persisted revocation memory or rotation
  audit — which key admitted a proof is never recorded; pre-rotation config
  rollback revives the old key; retired key-id reuse is operator discipline;
  a compromised current key stays forgeable until rotation lands and grace
  expires; wall-clock trust is the operator's; **no tenant authentication,
  TLS, KMS, distributed revocation or security-certification claim**), the
  "what works today"/capability clauses extended, the seventh demonstration
  named explicit S11 validation deliberately not one of the gates, and the
  `verify_install.py` descriptions extended with the rotation stages. Gate
  list unchanged.
- **`docs/verification.md`** — "Updated" header + new "S11 demo wave"
  subsection naming every test as it was added (same commits as the tests),
  including the installer-proof invariants and rejection paths.

## The six-table digest claim, stated exactly

The brief's narrative compresses "six-table digest byte-identical before
rotation and after all steps". Arithmetically the new-command branch writes
one `commands` row, so the demo prints and asserts the exact decomposition:
the six-table digest is byte-identical from before rotation through **every
zero-write rotation act** (the grace-boundary cached-receipt replay, the
retired refusal, the same-command re-sign — asserted after each step), and
after the new command **five tables are byte-identical with `commands` =
before + exactly 1 row**. The closing line's `history rewritten: 0` is that
fact. The README transcripts and the installer proof state the same
decomposition; nothing anywhere claims the commands table is byte-frozen
across the disclosed +1.

## RED/GREEN evidence (TDD, per task)

Fresh baseline before code: `python3 -m unittest discover -s tests` →
**`Ran 859 tests … OK (skipped=3)`** (recorded at task start, this tree).

- **Task 1 (demo module)** — RED: `python3 -m unittest tests.test_rotation_demo
  -v` → `ImportError: cannot import name 'rotation_demo'` (7 errors, module
  absent — the documented §6-style RED). GREEN: 7/7 OK; frozen core
  `tests.test_ingress tests.test_key_rotation` → 40+50 = **90 OK**;
  full discover `Ran 866 tests … OK (skipped=3)`.
- **Task 2 (CLI)** — RED: subprocess exit 2
  `invalid choice: 'rotation-demo'`. GREEN: focused file 8/8 OK;
  `python3 -m work_runtime rotation-demo` exit 0.
- **Task 3 (installer proof)** — RED: `AttributeError: module 'verify_install'
  has no attribute 'require_rotation_proof'` (7 errors). GREEN: 15/15 OK;
  full discover `Ran 874 tests … OK (skipped=3)`; `compileall` clean.
  Test-side fixes during RED, both ledgered: the exact-duplicate command-row
  mutation is impossible by schema (`UNIQUE(actor, id)` — the schema itself
  guarantees one row per command identity), so the negative forges the
  duplicate under a different actor and asserts the count branch message;
  and that forged row trips the 7-rows count check before the per-id check,
  so the test asserts the count-branch message.
- **Task 4 (docs)** — `check_docs` 0 broken after each edit (98 files/435
  links final); zh/en parity by mirrored structure.

Tests that cannot go RED on a pre-feature tree by construction: none new —
every Task 1–3 test failed first for the right reason (module absent /
subcommand absent / proof function absent).

## Verification battery (final)

- Five AGENTS gates, verbatim: contracts `checked 98 markdown files, 435
  local links, 0 broken`; tests `Ran 874 tests in 37.954s / OK (skipped=3)`;
  `demo` OK (exit 0); `python3 -m compileall -q work_runtime tests scripts`
  clean; site `checked 2 pages, 0 findings`. The gate commands and their
  list are unchanged; `rotation-demo` is not a gate.
- **Seven demos each exit 0**: `demo`, `publish-demo`, `intervention-demo`,
  `adoption-demo`, `revocation-demo`, `compensation-demo`, `rotation-demo`.
- Rehearsals `python3 -m unittest discover -s examples/rehearsal` →
  **`Ran 15 tests … OK (skipped=1)`** (the pre-existing opt-in
  action/link-context skip).
- Test counts: 859/3 baseline → **874/3** (15 new in
  `tests/test_rotation_demo.py`; `tests/test_ingress.py` 40 and
  `tests/test_key_rotation.py` 50 untouched — frozen core verified 90 OK).
  Skips, all pre-existing with exact names: 2×
  `adapter does not opt into action/link execution context`
  (`tests/adapter_conformance.py`) and
  `test_ui_cli.AbsentBackendTests.test_absent_backend_is_a_bounded_startup_error`
  (`backend assembled: absent-install path unreachable`).
- Installed verifier `python3 scripts/verify_install.py` run **serially with
  nothing else running**: **`=== PASS ===`, exit 0, zero SKIPPED stages**
  (the script's own summary discloses any skip; none printed; the installed
  UI stages ran over real HTTP). The two new rotation stages ran module and
  console entry points outside the checkout with the independent store proof
  and the verbatim printed inspect command (`"status": "active"`).
- `check_docs` on the committed tree: **0 broken links** (98/435).
- Protected-scope check: `git diff --name-only d40636e..HEAD` = exactly
  `work_runtime/rotation_demo.py`, `work_runtime/cli.py`,
  `scripts/verify_install.py`, `tests/test_rotation_demo.py`, `README.md`,
  `README.zh-CN.md`, `docs/verification.md`,
  `docs/superpowers/plans/2026-10-15-s11-demo.md` (+ this report).
  `ingress.py`, runtime core, policy, adapters, UI/site/assets, AGENTS,
  roadmap/sprint/acceptance/debt/pyproject all byte-identical (empty diff).

## Docs owed and paid

`docs/verification.md`: "Updated" header + the S11 demo-wave subsection
(every named test, the digest-decomposition claim, the installer-proof
invariants and rejection paths) — added in the same commits as the tests it
names. README/README.zh-CN: bilingual demo sections + truthful limitation
paragraphs + seventh-demo gate note + verifier descriptions (design §8: the
demo list entry rides with the demo wave). No `doc_sync_map` row is owed by
any file in scope. `docs/roadmap.md` 0.2 note and any ledger flip remain
master-owned close acts, untouched.

## Final review disclosure

Executing-plans' whole-branch review ran as a **self-review** (the dispatch
forbids extra agents; the sprint independently schedules the fresh final
acceptance before any merge, so this is not the last pair of eyes on the
branch). Reviewed the full diff against the plan's Review Focus: the digest
decomposition (no overstatement), store-derived proofs (no stdout trust),
the verbatim-cache pin (original receipt vs current status), secret
discipline (HEX64 pin, key ids only) and the retired-refusal semantics
(exact minimal receipt, window-precedence truthfully printed). Findings:
0 Critical, 0 Important. Deferred minors: the demo never exercises the
legacy no-selector path against a keyring (pinned by the core's 50 tests;
the demo makes no claim about it); `ROTATION_EVENT_IDS`/`ROTATION_TABLES`
exist only for the installer proof's locality (house style).

## Remaining risks and what is left

Carried unchanged from the ratification and the core review (Option A
boundary, restated truthfully in the READMEs and the demo docstring): no
persistent key revocation memory or rotation audit — config rollback
revives an old key; which key admitted a proof is never recorded; a
compromised current key stays forgeable until rotation lands and grace
expires; wall-clock trust is the operator's; nothing here is tenant
authentication, TLS, an external KMS, distributed revocation or any security
certification. Demo-specific: the six-table digest prefixes are 16 hex chars
(long enough to catch every tested mutation class; the tests and proof
recompute the full digest internally and compare the prefix).

Left to later waves (not this dispatch): the independent final acceptance;
the integration session's ordinary main merge, non-force push and remote CI
check; the master-owned roadmap 0.2 note and ledger flip. This worker now
idles per the dispatch.
