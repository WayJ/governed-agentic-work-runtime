# Acceptance record — sprint S11, 2026-10-15

Independent Orca final acceptance of the assembled S11 configured source
signing-key rotation release. Baseline asserted exact before anything ran:
carrier `WayJ/sprint-s11-source-key-rotation` at
`d40636e36586658c6a229444461732baecab9263` (worktree clean), W2 accepted demo
source `WayJ/s11-rotation-demo` at `ced368dd640436db35607f8e697f7d6733040316`
(tip, verified exactly **6 commits** on `d40636e`, merge-base `d40636e`,
worktree clean). Assembly performed by this review as an ordinary `--no-ff`
merge of `ced368d` onto `d40636e` in the acceptance worktree branch
`WayJ/s11-final-accept`: merge commit
`5a2d3bf6935eb6e6507f0f3bac058d63577b7da4`, no conflict (by construction —
9 files, +1047/−7, all W2-owned), tree clean after. **Before any scenario
ran**, both the carrier `WayJ/sprint-s11-source-key-rotation` and the control
`WayJ/s11-release-control` were fast-forwarded `d40636e → 5a2d3bf`
(`--ff-only`, no force anywhere); `git rev-parse` of carrier, control and the
acceptance HEAD all equal `5a2d3bf`, and the carrier tree hash equals this
checkout's (`98fa911ddcc3fab1cbcec9e1575d1c5e46c91677`) — every scenario below
ran fresh in this actual assembled carrier tree, not a tmp or stale tree. No
main merge, no push, no force, no extra agents. Base main
`b594d757ca5a680d3656b89df45a606d13254011` (S10 close; the roadmap 0.2 note
and any ledger flip are master-owned close acts, not this acceptance). Python
3.9.6 (system `python3`); zero runtime dependencies (re-verified by fresh venv
install); runtime store schema stays `1`. Review inputs read in full: AGENTS.md
(incl. the supervibe gates and the new `doc_sync_map` ingress row), the
ratified design spec with **MASTER D49–D53**
([§1–§13](../specs/2026-10-15-source-key-rotation-design.md)), the [E11
roadmap](../roadmaps/2026-10-15-source-signing-key-rotation.md), the active
[S11 sprint plan](../sprints/2026-10-15-S11-plan.md), the scoped W1/W2 plans,
the [W1 core report](../../../.agents/notes/2026-10-15-S11-core-report.md),
the [W1 core integration review](../../../.agents/notes/2026-10-15-S11-core-integration-review.md)
and the [W2 demo report](../../../.agents/notes/2026-10-15-S11-demo-report.md).

## Verdict

**pass** — all four scenarios green on fresh runs in the actual assembled
carrier tree (`5a2d3bf`, carrier and control verified at that SHA before the
runs); every DoD item checked with evidence (including independent RED replays
of both waves on their parent trees); the doc-drift audit over the full sprint
range `b594d75..5a2d3bf` shows the single triggered row
(`work_runtime/ingress.py → docs/signed-evidence.md`) paid with the same-commit
pairing independently re-verified and the mapped doc's content current — no
unpaid drift on any triggered row. This record and the sprint-doc state flip
are written in one same-commit act and precede the integration-owned ordinary
main merge/non-force push; final remote equality and exact-SHA CI are the close
act's items per the S7–S10 precedent.

## Scenario Results

| id | command | expected | actual | pass |
|---|---|---|---|---|
| S1 | `python3 -m unittest tests.test_ingress -v`; KAT verbatim `python3 -m unittest tests.test_ingress.SignEvidenceTests.test_known_answer_vector_pins_hmac_sha256 -v`; ring/selector battery `python3 -m unittest tests.test_key_rotation.KeyringConfigTests tests.test_key_rotation.KeySelectionTests tests.test_key_rotation.SignerKeyFieldTests tests.test_key_rotation.LegacyCompatTests -v` | Legacy bytes behavior unchanged (40 tests incl. published KAT); one authenticated key selected, no unsigned downgrade; ring list/tuple, current, unique, material, type, copy ("deepcopy") and signed-selector pins | **Ran 40 tests … OK** — `tests/test_ingress.py` byte-untouched legacy pin. KAT **ok** standalone: signature equals `84ba6259ac240cab06a5f9df89b8525be99ecb20605b975d76ee6e7f0c04ec08` (also re-pinned by `LegacyCompatTests.test_known_answer_vector_unchanged`). Battery **Ran 25 tests … OK**: rings accept list/tuple only (`test_ring_must_be_list_or_tuple`), nonempty, `SourceKey`-only entries with exact field types (`test_ring_entry_field_types_are_exact`), unique ids per ring, **exactly one** `current`, global material distinctness across the entire config, window order; construction copy/immutability — normalized per-source tuples in fresh dicts, caller inner-list and outer-map mutation changes nothing and a removed-from-caller-map legacy source still records (`test_configuration_is_copied_at_construction`, `test_ring_configuration_mutations_cannot_reach_verification`); signed selector inside HMAC bytes (`test_key_id_is_signed_content_and_tampering_fails`), unknown `key_id` → `EVIDENCE_AUTHENTICATION_FAILED`, keyring legacy envelopes authenticate against the `current` entry only (both directions), legacy bytes source rejects `key_id` envelopes, cross-source material cannot impersonate; signer round-trip with optional `key_id` and bad-value `ValueError`s | yes |
| S2 | `python3 -m unittest tests.test_key_rotation.WindowClockTests -v` | Exact minimal codes post-HMAC; `EVIDENCE_CLOCK_INVALID` fail-closed with zero writes; inclusive edges; single finite clock sample shared by window and freshness | **Ran 15 tests … OK**: bounds inclusive at both edges on both formats (`test_window_bounds_inclusive_at_edges`); `EVIDENCE_KEY_RETIRED` / `EVIDENCE_KEY_NOT_YET_VALID` post-HMAC only — garbage signature + closed window stays `EVIDENCE_AUTHENTICATION_FAILED` (no stranger oracle); dropped key `EVIDENCE_AUTHENTICATION_FAILED` vs retained-expired `EVIDENCE_KEY_RETIRED` distinct; window precedes freshness (retired+stale reports the window code); window uses verification time, never `issued_at` (no backdating); `EVIDENCE_CLOCK_INVALID` fail-closed — for samples `nan/±inf/"2000000000"/True/False/None/[now]` on both ring and legacy paths and for a clock raising ordinary `Exception`, the receipt is exactly `{"decision": "rejected", "code": "EVIDENCE_CLOCK_INVALID"}` with `table_counts()` unchanged (zero runtime writes; asserted per sample), no retry, no second sample; `BaseException` (`KeyboardInterrupt`) propagates; huge-int samples (±10**400) safe (no overflow path) and decided by exact comparison; **one** clock sample per record shared by window and freshness (`test_single_clock_sample_shared_by_window_and_freshness`, `test_clock_not_sampled_until_hmac_succeeds` — zero calls across denials); legacy `±max_age` freshness semantics unchanged | yes |
| S3 | `python3 -m unittest tests.test_key_rotation.ReplayHistoryTests -v` | Auth ahead of cache and source authority; same-command re-sign returns original receipts verbatim; new-command resend dedupes to current proof status; revoked proof, grant loss, conflict and **six-table** byte-equality preserved | **Ran 10 tests … OK**: retired-key replay of an *accepted original* cannot reach the cached receipt — `EVIDENCE_KEY_RETIRED` behind authentication (`test_retired_key_replay_cannot_reach_cached_receipt`); same-`command_id` re-sign under the new valid key returns the **original cached receipt verbatim** with `table_dump()` equality (zero writes; `test_resign_same_command_under_new_key_returns_original_receipt`), also after trusted-local revocation; **new** `command_id` same event → same `evidence_id`, **current** status (`verified`; `revoked` after revocation), exactly `commands + 1`, `evidence` count unchanged (`test_resign_same_event_new_command_under_new_key_dedupes`, `test_revoked_evidence_preserves_original_receipt_and_reports_status`); grant loss (store reopened without the source's grants) → fresh **unpersisted** `AUTHORITY_DENIED`, stored receipt intact; changed content same event → persisted `SOURCE_EVENT_CONFLICT` unchanged; **six tables** (`works`, `commands`, `evidence`, `operations`, `events`, `metadata`) byte-identical (ordered rowid dumps) across pure reconstruction and every denial class (`test_history_six_tables_preserved_across_rotation_acts`); deterministic same-config/same-clock restart; every new-code receipt exactly `{decision, code}` — no key echo; reserved `accepted` and mapping-denied `withdrawn` kinds unchanged for keyring sources | yes |
| S4 | `python3 -m work_runtime rotation-demo`; console outside the checkout via a fresh venv (`python3 -m venv`, `pip install <checkout>`, `work-runtime rotation-demo` with cwd `/tmp`) **and** `python3 scripts/verify_install.py` run serially; five AGENTS gates verbatim; seven demos; `python3 -m unittest discover -s examples/rehearsal`; full suite `python3 -m unittest discover -s tests -v` | Correct scope, no secrets printed; installed module+console proof; exact gate/test/demo/rehearsal counts and skip names; doc-sync audit; independent acceptance before push | Module demo **exit 0** with the pinned closing line `1 scenario; dual-key accepts: 2; retired refusals: 1 (zero writes); cached receipts verbatim: 2; new commands: 1; history rewritten: 0` — only key ids `finance-2026-08`/`finance-2026-10` printed, never secrets (16-hex digests only; no-64-hex pinned by tests). Console: fresh venv installed the checkout as `governed-work-runtime==0.1.0` with **zero third-party dependencies**, `work-runtime rotation-demo` from `/tmp` **exit 0**. Installed verifier, **serial, nothing else running**: **`=== PASS ===`, exit 0, zero SKIPPED lines**, stages 19–20 run module and console rotation-demo **outside the checkout** with the independent store proof (six-table digest recomputed locally and matched, verified evidence fingerprints, the original cached receipt, exactly one command row per rotation command id, `("schema_version","1")`, the printed inspect command replayed with `"status": "active"`). Five gates verbatim: contracts `checked 97 markdown files, 435 local links, 0 broken`; tests **`Ran 874 tests in 37.894s / OK (skipped=3)`**; `demo` exit 0; `python3 -m compileall -q work_runtime tests scripts` clean; site `checked 2 pages, 0 findings` — gate list unchanged, `rotation-demo` deliberately not a gate (README states this). **Seven demos exit 0**: `demo`, `publish-demo`, `intervention-demo`, `adoption-demo`, `revocation-demo`, `compensation-demo`, `rotation-demo`. Rehearsals **`Ran 15 tests … OK (skipped=1)`** — the pre-existing generic opt-in conformance skip. Full-suite skips, exact names: 2× `Opt-in action/link execution: explicit forward context replays.` (`test_opted_in_action_context_replay_returns_identical_receipt` on `FilePublisherConformanceTests` and `FakePublisherConformanceTests`, reason `'adapter does not opt into action/link execution context'`) and `test_absent_backend_is_a_bounded_startup_error` (`test_ui_cli.AbsentBackendTests`, reason `'backend assembled: absent-install path unreachable'`) — all pre-existing. Scope: full-range changed set is exactly the W1/W2 owned files; `runtime.py`, `policy.py`, `adapters.py`, UI/web/site assets, `tests/test_ingress.py` all unchanged (empty diff `b594d75..5a2d3bf`). Doc-sync audit below. This record precedes the merge; final remote==main and exact-SHA CI are recorded at push time in the close note per the S7–S10 precedent | yes |

## Independent RED replays (DoD "meaningful RED/GREEN", fresh this run)

- **W1 RED**: `git archive b594d75 | tar -x -C /tmp/s11-final-accept-red/w1` +
  committed `tests/test_key_rotation.py` → `python3 -m unittest
  tests.test_key_rotation` → `ImportError: cannot import name 'SourceKey'
  from 'work_runtime.ingress'` (the design §6 documented RED; the pre-feature
  tree cannot import the feature). GREEN is the S1–S3 batteries above on the
  assembled tree.
- **W2 RED**: `git archive d40636e | tar -x -C /tmp/s11-final-accept-red/w2` +
  committed `tests/test_rotation_demo.py` → `python3 -m unittest
  tests.test_rotation_demo` → **FAILED (failures=1, errors=14)**, every error
  `ImportError: cannot import name 'rotation_demo' from 'work_runtime'` (the
  CLI test fails as unknown-subcommand) — the W2 report's documented RED,
  independently reproduced. GREEN is S4's demo/CLI/installer evidence above.
- W1-wave RED granularity was independently replayed by the [W1 core
  integration review](../../../.agents/notes/2026-10-15-S11-core-integration-review.md)
  (Task 2: 23 tests, 1F+8E; Task 3: 38 tests, 9F+1E on parent trees) — cited
  on the same core SHAs this release carries (`ce584d3` merged via `71bee01`).

## DoD Checklist

- [x] Optional authenticated key_id and validated copied per-source keyrings preserve legacy seven-field canonical signatures and old source configuration while selecting exactly one verification key without fallback guessing — S1: legacy 40/40 OK with the published KAT reproduced verbatim through the public signer (both `test_ingress.py` and `LegacyCompatTests`); ring battery green (list/tuple-only, nonempty, exact `SourceKey` field types incl. bool/int traps, unique ids, exactly-one `current`, `not_before <= not_after`, global material distinctness, immutable construction copy immune to caller mutation); selector battery green (key_id inside signed bytes, unknown → `EVIDENCE_AUTHENTICATION_FAILED`, no try-all, no fallback: keyring legacy envelopes select the `current` entry only in both directions, legacy bytes sources reject `key_id` envelopes, cross-source material cannot impersonate)
- [x] Inclusive configured validity windows and freshness share one finite verification-time sample; malformed, unknown, bad-signature, inactive, retired and invalid-clock outcomes have pinned minimal codes and zero runtime writes — S2: 15/15 green; inclusive edges; single post-HMAC sample shared by window+freshness (sample-count and ordering pinned); `EVIDENCE_CLOCK_INVALID` exact minimal receipt with `table_counts()` unchanged across non-finite/wrong-type/raising clocks on both formats; both window codes post-HMAC only; drop-vs-retain distinct codes; malformed shapes `EVIDENCE_ENVELOPE_INVALID`; receipts exactly `{decision, code}`
- [x] Authentication remains ahead of cache and source authority; same-command re-sign returns original receipts while new-command resends dedupe current proof status, preserving revoked evidence, identities and historical effects/closure — S3: 10/10 green; retired replay of an accepted original refused behind the cache with zero writes; same-command re-sign returns the original cached receipt byte-verbatim (zero writes, also after revocation; grant loss converts to fresh unpersisted `AUTHORITY_DENIED` with the stored receipt intact); new-command resend → same evidence id + current status with exactly `commands +1`; revoked evidence preserved with current `revoked` status reported; `SOURCE_EVENT_CONFLICT` unchanged; six tables byte-identical across reconstruction and every denial class
- [x] Meaningful real-store RED/GREEN covers both formats, rollover/retirement, copy/type/clock boundaries, replay/grant-loss/conflict and all-table preservation; Python>=3.9/schema1/zero dependencies and existing business/UI behavior remain valid — RED independently replayed fresh this run for both waves (above) plus the W1 review's per-task replays cited; all batteries run on real SQLite stores (`table_counts`/`table_dump` over six tables); Python 3.9.6 system interpreter; fresh venv install with zero third-party packages; installer asserts `("schema_version","1")`; existing behavior valid — full suite 874 OK incl. every pre-existing test, protected paths (runtime/policy/adapters/UI/web/site/legacy tests) byte-identical `b594d75..5a2d3bf`
- [x] Rotation-demo and installed module plus console trials prove actual stored identity/history without printing secrets; full tests, five configured gates, seven demos, existing rehearsal coverage and serial installed verification pass with exact counts/skips — S4: module demo and console (own fresh venv, outside the checkout) both exit 0 with only key ids printed; serial `verify_install.py` `=== PASS ===` with zero SKIPPED and independent store re-verification (recomputed six-table digest, fingerprints, cached receipt, command-row counts); counts exactly 874/3, 97/435/0, 2 pages/0 findings, seven demos exit 0, rehearsals 15/1, skips enumerated by exact name (all pre-existing)
- [x] Independent acceptance precedes integration ordinary main merge/non-force push with same-commit ingress/signed-evidence docs, honest config-only trust/rollback limits and exact final remote equality/CI — this record + the sprint `state: acceptance` flip are one same-commit act written before any merge (no main merge, no push performed by this review); the ingress→signed-evidence same-commit pairing is re-verified over the whole release range (audit below); README/README.zh-CN and `docs/signed-evidence.md` carry the truthful config-only limits verbatim (no persisted key identity or rotation audit, config-rollback revival, compromised-current-key window, operator wall-clock trust, no tenant auth/TLS/KMS/distributed revocation/security certification — re-read this run, bilingual); final remote equality and exact-SHA CI are the close act's items, recorded at push time per the S7–S10 precedent

## Obstacles (verbatim)

- 2026-10-15 — first standalone KAT invocation used the wrong class path:
  `python3 -m unittest
  tests.test_ingress.SignedEvidenceGatewayTests.test_known_answer_vector_pins_hmac_sha256 -v`
  → `AttributeError: type object 'SignedEvidenceGatewayTests' has no attribute
  'test_known_answer_vector_pins_hmac_sha256'` (FAILED, errors=1). Probe-side
  wrong class name — the KAT lives in `SignEvidenceTests`
  (`tests/test_ingress.py:40`); re-run against the correct class → `Ran 1 test
  … OK`. No product issue; the full 40-test module run was green throughout.
- 2026-10-15 — `work-runtime` console script not on the shell PATH
  (`work-runtime not found`). Notes searched first (obstacle protocol): the
  [W2 demo report](../../../.agents/notes/2026-10-15-S11-demo-report.md) and
  `scripts/verify_install.py`'s own docstring (stages 19–20) document the house
  pattern — console proof outside the checkout runs from a fresh venv install.
  Reused that pattern independently:
  `TMPD=$(mktemp -d /tmp/s11-final-accept-venv-XXXX) && python3 -m venv
  "$TMPD/venv" && "$TMPD/venv/bin/pip" install --quiet --no-input <checkout>`
  (exit 0, `governed-work-runtime==0.1.0`, no third-party deps) then
  `cd /tmp && "$TMPD/venv/bin/work-runtime" rotation-demo` → closing narrative,
  `CONSOLE-EXIT:0`. Additionally covered by the serial `verify_install.py` run
  (its own fresh venv, both module and console stages outside the checkout).
- No other blocker, failure or substitution occurred. No evidence item in this
  record is substituted: every scenario ran its specified proving command for
  real on the assembled carrier tree.

## Doc-Drift Audit

Ranges audited: the dispatch-named `d40636e..5a2d3bf` (the W2 wave) and the
full sprint range `b594d75..5a2d3bf` (merge-base with main; subsumes W1).

| map row (change, owes) | matched this sprint | doc state | detail |
|---|---|---|---|
| work_runtime/runtime.py → docs/runtime-boundaries.md | no — unchanged `b594d75..5a2d3bf` (and in `d40636e..5a2d3bf`) | n/a | row owes nothing |
| work_runtime/adapters.py → docs/runtime-boundaries.md | no — unchanged both ranges | n/a | row owes nothing |
| scripts/check_docs.py → CONTRIBUTING.md | no — unchanged both ranges | n/a | row owes nothing |
| scripts/check_site.py → docs/website.md | no — unchanged both ranges | n/a | row owes nothing |
| work_runtime/ingress.py → docs/signed-evidence.md | **yes** — W1 wave (`f04cb99`, `e7cd1c7`, `59b21e6`, `8e322cd`, merged here via `71bee01` into `d40636e`); unchanged in `d40636e..5a2d3bf` | current; same-commit pairing **re-verified** | Per-commit audit over `b594d75..5a2d3bf` (diff-tree per parent): every commit whose diff touches `work_runtime/ingress.py` — exactly `f04cb99`, `e7cd1c7`, `59b21e6`, `8e322cd` plus the core assembly merge `71bee01` — also touches `docs/signed-evidence.md` in the same commit; the W2 assembly merge `5a2d3bf` leaves `ingress.py` identical to both parents (not a trigger). Doc content re-read this run and current: envelope table with the optional authenticated `key_id`, gateway precedence incl. `EVIDENCE_CLOCK_INVALID` and both post-HMAC window codes, the Source keyrings (S11) section with exact D50 validation and the honest copy-scope claim, the rollover ladder incl. drop-vs-retain, replay/cache/history semantics, and the truthful limitations. No S10-style arrears |

Beyond the map (recorded, not enforced): `docs/verification.md` rides in the
same commit as every test-adding commit of both waves (per-commit audit:
`f04cb99`, `e7cd1c7`, `59b21e6`, `82b5e54`, `8e322cd`, `0228ff5`, `bd3a229`,
`d3e75fd`, plus the assembly merges — all paired, design §8 rule); the
bilingual README demo entries rode with the demo wave (design §8);
`AGENTS.md` carries the master-owned `doc_sync_map` ingress row added at
ratification (D53/SKR-9 — the worker never changed the agreement);
`docs/roadmap.md` 0.2 note and any ledger flip are master-owned close acts and
are correctly absent from this acceptance.
