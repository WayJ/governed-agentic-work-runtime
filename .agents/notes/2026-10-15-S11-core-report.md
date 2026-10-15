# S11 W1 core development — configured source signing-key rotation — report

Worker: S11 INGRESS CORE DEVELOPMENT (this checkout `s11-source-key-core`,
carrier `WayJ/sprint-s11-source-key-rotation` tip `331172f` asserted exact and
clean at start, fresh baseline recorded; dev branch `WayJ/s11-source-key-core`).
Date: 2026-10-15. Scope honored: `work_runtime/ingress.py`,
`tests/test_key_rotation.py` (new), `docs/signed-evidence.md` (same commit as
every ingress change, per the AGENTS `doc_sync_map` ingress row), current
`docs/verification.md` coverage, scoped plan
`docs/superpowers/plans/2026-10-15-s11-core.md`, this report.
`tests/test_ingress.py` untouched (legacy 40-test pin incl. KAT); no
runtime/policy/adapters/CLI/demo/install/package-exports/README/UI/AGENTS/
roadmap/sprint/acceptance changes; schema stays `1`; Python ≥3.9 stdlib only;
no merge, no push, no full-S11-release claim. `rotation-demo` and the
installer stage are W2 (next master dispatch); the five AGENTS gates are
unchanged.

Plan: `docs/superpowers/plans/2026-10-15-s11-core.md`, committed `a60fc18`
**before** code as the dispatch requires, executed inline with superpowers
executing-plans + TDD (no subagents — dispatch forbids extra agents; the
executing-plans workspace was deleted after the clean final review per that
skill, rulings and findings carried here and in git history).

## Commits

| commit | subject |
|---|---|
| `a60fc18` | docs: scoped S11 W1 ingress core implementation plan |
| `f04cb99` | feat: per-source SourceKey rings with exact validation and immutable copy (S11 D49/D50) |
| `e7cd1c7` | feat: optional signed key_id selector with strict per-ring selection (S11 D49/D51) |
| `59b21e6` | feat: single finite clock sample and inclusive key validity windows (S11 D51) |
| `82b5e54` | test: rotation replay, cache-first and history-preservation pins (S11 D52) |
| `8e322cd` | fix: pin rotated-direction legacy rejection and scope the config-copy claim (S11 review) |
| (this commit) | docs: S11 W1 core development report |

Every commit touching `work_runtime/ingress.py` (`f04cb99`, `e7cd1c7`,
`59b21e6`, `8e322cd`) also touches `docs/signed-evidence.md` in the same
commit; each test-adding commit also updates `docs/verification.md` — no S10
style doc arrears.

## What was implemented (D49–D53, F1–F4/M1–M4 folded)

- **D50 rings**: `SourceKey(NamedTuple)` (`key_id`, `secret`, `current`,
  `not_before`, `not_after`); `keys` stays a dict, per source either legacy
  `bytes` (validation unchanged) or a nonempty list/tuple of `SourceKey` only
  (str/bytes/generator/set/set-dict values are shape `ValueError`s, never
  iterated); exact entry types (`key_id` exact nonempty str, `secret` exact
  bytes ≥32, `current` exact bool — 1/0 rejected, windows each `None` or
  exact int — bool traps rejected); `not_before <= not_after`; unique ids per
  ring; exactly one `current`; secret material distinct across the **entire**
  configuration (legacy and every ring entry, any source). Normalized to
  immutable per-source tuples in fresh dicts — caller outer-dict and
  inner-list mutation after construction changes nothing. Documented honestly
  as copying caller-supplied config, not a protection boundary against
  mutating gateway internals.
- **D49 selector**: optional `key_id` inside the signed canonical bytes
  (`SIGNED_FIELDS` and the published KAT unchanged; envelopes are exactly the
  seven legacy fields or those seven plus `key_id`). Selection before HMAC,
  deterministic, no try-all, no fallback: cited `key_id` → that entry else
  `EVIDENCE_AUTHENTICATION_FAILED`; keyring without `key_id` → `current`
  entry only (both directions pinned: non-current key under old config, and
  retained old key under a rotated config, fail HMAC against the current
  key); legacy bytes source + `key_id` envelope → `EVIDENCE_AUTHENTICATION_FAILED`.
- **D51 time**: one clock sample per record, taken only after successful HMAC
  and shared by window + freshness; sample must be exact int/float (not bool)
  and finite (floats only through `isfinite` — huge ints never converted, so
  no `OverflowError` exposure); non-finite/wrong type/raising clock → minimal
  `{"decision":"rejected","code":"EVIDENCE_CLOCK_INVALID"}`, zero runtime
  calls/writes, no retry, no second sample, ordinary `Exception` only
  (`BaseException` propagates — pinned with `KeyboardInterrupt`). Key window
  (inclusive, current verification time never `issued_at` — no backdating)
  before freshness before reserved kind before `runtime.command`. New codes
  `EVIDENCE_KEY_NOT_YET_VALID` / `EVIDENCE_KEY_RETIRED`, minimal, post-HMAC
  only (no stranger oracle — pinned). Dropped key → `EVIDENCE_AUTHENTICATION_FAILED`
  vs retained expired → `EVIDENCE_KEY_RETIRED` (distinct, both pinned).
  Legacy `max_age` semantics preserved (±`max_age` inclusive re-pinned); the
  legacy NaN-sample freshness fail-open is intentionally fixed by the clock
  gate. Freshness is the exact comparison form `issued_at - max_age <= now <=
  issued_at + max_age` (equivalent to the old `abs` form, boundary-identical;
  no float/int subtraction anywhere in the time path).
- **D52 replay/history**: authentication precedes the command cache (retired
  replay of an accepted original → `EVIDENCE_KEY_RETIRED`, six tables
  byte-identical); same-`command_id` re-sign under a new valid key → original
  cached receipt **verbatim** (zero writes, also after trusted-local
  revocation, and grant loss converts it to fresh unpersisted
  `AUTHORITY_DENIED` with the stored receipt intact); new-`command_id` same
  event/content → same evidence id + **current** status (`revoked` after
  revocation), exactly `commands +1`, no new evidence row; changed content →
  `SOURCE_EVENT_CONFLICT` (persisted) unchanged; per-act history scope (M1):
  pure reconstruction + every denial class byte-equal across **all six**
  tables incl. metadata, legitimate new ingress prefix-equal on the four
  append-only tables with `works`/`metadata` untouched by a pending
  insertion — no universal works-prefix claim. Deterministic same-config/
  same-clock restart decisions pinned. `key_id`/`issued_at`/`signature`
  never forwarded, persisted, or fingerprinted (body purity pinned); rotation
  never withdraws proofs, effects, closure or compensation.

## RED/GREEN evidence (TDD, per task)

Baseline before code: `python3 -m unittest discover -s tests` → **`Ran 809
tests … OK (skipped=3)`** (fresh, this tree, 2026-10-15).

- **Task 1 (rings)** — RED: `python3 -m unittest tests.test_key_rotation -v`
  → `ImportError: cannot import name 'SourceKey'` (the design §6 documented
  RED; 1 test errored). GREEN after minimal implementation: 11/11 OK;
  `tests.test_ingress` 40 OK; full discover `Ran 820 tests … OK (skipped=3)`.
- **Task 2 (selector/signer)** — RED: 8 errors + 1 failure (signer
  `ValueError: message requires exactly the signed fields` on `key_id`
  messages; legacy-format envelope against a ring source rejected — selection
  unwired). GREEN: 23/23 OK; legacy 40 OK; full `Ran 832 tests … OK
  (skipped=3)`. (The GREEN iteration caught one real implementation slip — a
  set-logic bug in `_message_problem` that broke all legacy signing — via the
  untouched legacy suite; fixed, suites re-run green.)
- **Task 3 (clock/windows)** — RED: 12 of 15 new tests failed for the right
  reasons (missing codes; NaN clock still fail-open-accepting). GREEN: 38/38
  OK; legacy 40 OK; full `Ran 847 tests … OK (skipped=3)`.
- **Task 4 (pins)** — 11/12 GREEN immediately on the probe-verified
  machinery; the grant-loss pin initially failed through my own fixture using
  `demo_grants()` (which still grants `finance`) — fixed to grants actually
  omitting the source → fresh unpersisted `AUTHORITY_DENIED` GREEN. Full
  `Ran 859 tests … OK (skipped=3)`; rehearsals `Ran 15 tests … OK
  (skipped=1)`.
- **Final review fix pass** — one Important finding (missing literal pin of
  the rotated-direction legacy rejection, D51/§4.5 step 3): pin added and
  passes against the already-correct behavior (coverage gap, no production
  change); suite stays `Ran 859 tests … OK (skipped=3)`.

Tests that cannot go RED on a pre-feature tree by construction (documented,
not forced): the M2c bad-`key_id`-shape pin (old exact-field-set rule already
yields the same `EVIDENCE_ENVELOPE_INVALID`), and three WindowClockTests that
pin already-true behavior (BaseException propagation, clock-after-HMAC
ordering, legacy freshness boundaries).

## Verification battery (final, after `8e322cd`)

- Five AGENTS gates, verbatim: contracts `checked 101 markdown files, 423
  local links, 0 broken`; tests `Ran 859 tests in 40.213s / OK (skipped=3)`;
  `demo` OK (exit 0); `python3 -m compileall -q work_runtime tests scripts`
  clean; site `checked 2 pages, 0 findings`.
- Six existing demos each exit 0: `demo`, `publish-demo`,
  `intervention-demo`, `adoption-demo`, `revocation-demo`,
  `compensation-demo`. **No new rotation-demo command exists** (that is W2).
- Rehearsals `python3 -m unittest discover -s examples/rehearsal` → `Ran 15
  tests … OK (skipped=1)` (skip: the generic opt-in action/link conformance
  case — the queue adapter does not opt in; pre-existing).
- Installed verifier `python3 scripts/verify_install.py` run **serially,
  nothing concurrent**: `=== PASS ===`, **zero SKIPPED stages**.
- Test counts: 809/3 baseline → **859/3** (50 new in
  `tests/test_key_rotation.py`; `tests/test_ingress.py` 40/40 untouched).
  Skips, all pre-existing: the opt-in action/link-context conformance cases
  in `tests/adapter_conformance.py` (×2, "adapter does not opt into
  action/link execution context") and
  `tests/test_ui_cli.AbsentBackendTests.test_absent_backend_is_a_bounded_startup_error`
  ("backend assembled: absent-install path unreachable").
- Protected-scope check: `git diff --name-only 331172f..HEAD` = exactly
  `work_runtime/ingress.py`, `tests/test_key_rotation.py`,
  `docs/signed-evidence.md`, `docs/verification.md`,
  `docs/superpowers/plans/2026-10-15-s11-core.md` (+ this report). Runtime
  core, policy, adapters, CLI, demos, install, package exports, UI, assets,
  AGENTS, roadmap/sprint/acceptance diffs all empty.

## Docs owed and paid

`docs/signed-evidence.md`: envelope table + optional signed `key_id` and
canonicalization rules; keyring configuration (exact types, exactly-one
current, windows, global distinct material, immutable copy and its honest
scope, rollover ladder incl. drop-vs-retain trade-off); gateway check order
(selector step, single finite clock step with `EVIDENCE_CLOCK_INVALID`
semantics, inclusive window step with both codes, window-before-freshness);
rotation replay/cache/history semantics; truthful limitations (no persisted
key identity or rotation audit, config-rollback revival, compromised current
key forgeable until rotation, operator wall-clock trust, no tenant auth/TLS/
KMS/distributed revocation/security certification); tests section.
`docs/verification.md`: "Updated" header + full S11 coverage section with
every named test. No secrets or key material appear in any doc or test
output; the only signature value shown is the published non-secret KAT.

## Final review disclosure

Executing-plans' whole-branch review ran as a **self-review** (the dispatch
forbids extra agents; the sprint independently schedules a fresh core
review/assembly session before the demo wave, so this is not the last pair of
eyes on the branch). Findings: 0 Critical; 1 Important (the rotated-direction
coverage gap, fixed `8e322cd`); 2 minors fixed in the same commit (unused
import; explicit D50 copy-claim scoping). Rulings: legacy NaN fail-closed is
the ratified intentional change; cannot-go-RED pins documented above;
O(ring) selector scans are config-sized by ratified design (no cap).

## Remaining risks and what is left

Honest limits carried from the ratification: no persistent key revocation
memory — a pre-rotation config rollback revives the old secret for future
envelopes; a compromised *current* key stays forgeable until rotation lands
and grace expires; which key admitted a proof is never recorded (no rotation
audit rows); wall-clock trust is the operator's. None of these are new
exposures — they are the documented Option A boundary.

Left to later waves (not this dispatch): independent core review + assembly;
`rotation-demo` module/CLI/README + installer stage (W2); final independent
acceptance; integration-owned ordinary main merge and push. This worker now
idles per the dispatch.
