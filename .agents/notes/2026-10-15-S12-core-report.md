# S12 W1 publication core development report — 2026-10-15

Worker dispatch `task_8a8c7626bde6` on carrier `WayJ/s12-publication-core`
(local branch name; HEAD asserted exactly at the task's named carrier commit
`24dd14c5b9270a0e00ca1c0413eaa011017644be`, tree clean before any write).
Scope: wave 1 only — store/read surface, loader/pin, governed flow,
rotation interaction — exactly per master ratification D54–D66. Wave 2
(`publication-demo`, installer stage, README, docs rewrite incl. the
stale-CLI repair and IR-F5 count correction) is untouched and owed to the
next dispatch.

## Commits (this dispatch)

| commit | subject |
|---|---|
| `2b487a9` | docs: S12 W1 publication core scoped implementation plan (committed before code) |
| `460bbc8` | feat: FilePublisher.read_validated additive validated read surface (S12 D61) |
| `e95884d` | feat: digest-based publication key and SopPublicationStore wrapper (S12 D55/D56/D60) |
| `c7dc3d0` | feat: fail-closed published-card loader and pin functions (S12 D62) |
| `0ea9a99` | feat: governed SopPublicationPolicy with signed card approvals (S12 D54/D57-D59/D66) |
| `3f559b0` | test: publication approver-key rotation battery on S11 semantics (S12 wave 1) |
| `ae801a1` | test: drop dead conditional in governed-flow clock lambda (review cleanup) |
| (this commit) | docs: S12 W1 core development report |

## What was built

- `work_runtime/file_adapter.py`: one narrow additive public method
  `read_validated(key)` (D61/IR-F4) — same key gate and bounded corruption
  matrix as `lookup`, `None` on absent (mirroring `lookup`, keeping absence
  distinguishable from corruption), full validated artifact on hit. No other
  line of the pinned adapter changed.
- `work_runtime/publication.py` (new, 263 lines): `publication_key` /
  `_identity_key` (`"sop-pub:" + digest([policy_id, policy_version])`, D56 —
  the digest form; delimiter-joined form rejected per IR-P16);
  `SopPublicationStore` (thin wrapper over an unchanged `FilePublisher`,
  contract `actions=("sop.publish",)`, `uniqueness=("publication.key",)`,
  D55/D60); `load_published_card` / `pinned_card` / `published_card_matches`
  (fail-closed read path, no Runtime wiring, no card→policy compilation,
  D62); `SopPublicationPolicy` (`sop-publish`/`demo-1`/`sop.published`,
  sources `card_approval→sop-owner`, `accepted→sop-store`; admission lint
  via `sop_digest` D57; version-bound `{digest, policy_version}`
  `card_approval` validation D58; S02/S03 requirements mirroring C02/C04;
  `operation_key` = the publication key D66). No withdrawal (D63).
- Tests: `tests/test_publication.py` (33 tests), new
  `tests/test_publication_rotation.py` (6 tests), narrow additive
  `ReadValidatedTests` in `tests/test_file_adapter.py` (6 cases, 51→57
  in-file cases with the inherited conformance cases unchanged).
- Docs, same-commit paired per doc_sync_map: `docs/file-adapter.md`
  (`read_validated` subsection), `docs/sop-authoring.md` (full publication
  section: what a publication is, the store, loader/pin, the governed flow
  with the D66 pinned order and the IR-F2 card-immutability framing,
  rotation), `docs/verification.md` (S12 core coverage section, additive).

## TDD evidence (RED → GREEN per task)

- **Task 1 (read_validated):** RED
  `python3 -m unittest tests.test_file_adapter.ReadValidatedTests -v` →
  `FAILED (errors=6)`, every case `AttributeError: 'FilePublisher' object
  has no attribute 'read_validated'`; GREEN after the 14-line method →
  `Ran 57 tests … OK (skipped=1)` for the file; full discover 880 OK
  (skipped=3).
- **Task 2 (key + store):** RED `python3 -m unittest tests.test_publication
  -v` → `ModuleNotFoundError: No module named 'work_runtime.publication'`;
  GREEN → `Ran 9 tests … OK`; full discover 889 OK (skipped=3).
- **Task 3 (loader/pin):** RED
  `ImportError: cannot import name 'load_published_card'`; GREEN →
  `Ran 19 tests … OK`; full discover 899 OK (skipped=3). Two test-side
  fixes during the cycle (missing `FilePublisher` import for the doctored
  store fixtures).
- **Task 4 (governed flow):** RED
  `ImportError: cannot import name 'SopPublicationPolicy'`; GREEN →
  `Ran 33 tests … OK`; full discover 913 OK (skipped=3). Two test-side
  fixes (missing `table_counts` helper; an `or`-short-circuit assertion).
- **Task 5 (rotation battery):** pins observed GREEN on first run —
  expected, per plan: the S11 machinery is probe-verified (IR-P19a–d) and
  no production code was required; the pins compose it with the publication
  family. `Ran 6 tests … OK`; full discover 919 OK (skipped=3).

## Verification battery (Task 6, fresh tree at the final commits)

| check | command | result |
|---|---|---|
| contracts | `python3 scripts/check_docs.py` | `checked 103 markdown files, 486 local links, 0 broken` |
| tests | `python3 -m unittest discover -s tests -v` | `Ran 919 tests … OK (skipped=3)` |
| demo | `python3 -m work_runtime demo` | exit 0 |
| syntax | `python3 -m compileall -q work_runtime tests scripts` | exit 0 |
| site | `python3 scripts/check_site.py` | `checked 2 pages, 0 findings` |
| demos | all seven subcommands | `demo`, `publish-demo`, `intervention-demo`, `adoption-demo`, `revocation-demo`, `compensation-demo`, `rotation-demo` each exit 0. The dispatch said "six existing demos"; the honest count is **seven** — `rotation-demo` shipped with S11 W2 after that text. `publication-demo` correctly absent (exit 2 unknown command) until W2. |
| rehearsals | `python3 -m unittest discover -s examples/rehearsal` | `Ran 15 tests … OK (skipped=1)` (pre-existing skip) |
| installed verifier | `python3 scripts/verify_install.py` (serial) | `=== PASS ===`, zero SKIPPED stages, unchanged stage set |

Exact skip names in the 919-run: `test_opted_in_action_context_replay_returns_identical_receipt
(test_file_adapter.FilePublisherConformanceTests)` and the same-named test
in `test_publishing.FakePublisherConformanceTests` (both
`adapter does not opt into action/link execution context`) and
`test_absent_backend_is_a_bounded_startup_error
(test_ui_cli.AbsentBackendTests)` (`backend assembled: absent-install path
unreachable`) — all three pre-existing at the baseline.

Protected scope: `git diff --stat 24dd14c..HEAD` touches exactly the nine
owned files (plan, `work_runtime/publication.py`, `work_runtime/file_adapter.py`
+15 lines, three test files, `docs/file-adapter.md`, `docs/sop-authoring.md`,
`docs/verification.md`). Zero changes to `runtime.py`, `ingress.py`,
`authoring.py`, `policy.py`, `adapters.py`, `cli.py`, demos, install,
`verify_install.py`, README, UI, site, AGENTS.md, roadmap, sprint files,
`__init__.py` exports; schema stays `1`; zero dependencies; Python ≥3.9.

## Independent-review pins honored (IR-F1–F7)

- IR-F1/D56: digest key; `test_delimiter_hostile_ids_do_not_collide` proves
  the IR-P16 pair (`("collide:one","v1")` vs `("collide","one:v1")`) stays
  distinct.
- IR-F2: no `revise_document` test exists; the docs state card-immutability
  within a work (content changes enter as new works; D66 conflict after the
  second work's own approval).
- IR-F3/D66: both conflict tests pin the order — `REQUIREMENT_UNSATISFIED`
  first, `OPERATION_CONTENT_CONFLICT` only after the second work's own
  verified approval, winner bytes unchanged.
- IR-F4/D61: `read_validated` None-on-absent; loader converts absence into
  its own bounded error (corrupt vs absent distinguishable, pinned).
- IR-F5: left to W2 story 6 per MD-3 (verification.md line 76's "50" and the
  51-count correction); this report records the current honest file counts.
- IR-F6: rotation tests assert configuration-bound behavior only
  (retained-with-window vs dropped rings).
- IR-F7/MD-4: recorded as the accepted operator-discipline boundary
  (cross-database store sharing fails closed; the loader likewise refuses
  foreign content under a publication key — pinned by the two
  raw-FilePublisher doctored-store tests).

## Honest remaining risks and boundaries

- **Deferred minor (self-review):** `load_published_card`/`pinned_card`
  accept a `str` directory only; a `Path` argument fails with the
  absent-version message (bounded, fail-closed, but potentially misleading
  to an operator). One-line `os.PathLike` acceptance + one test if wanted.
- Cross-database store sharing remains operator discipline (MD-4): the
  loader and reconcile both fail closed, but nothing prevents two databases
  pointing at one directory.
- Trust model unchanged: approvers are configured local names with
  shared-key signatures; config-only trust, config-rollback key revival,
  and the absence of any TLS/KMS/tenant-authentication or distributed
  exactly-once claim carry over from S11/file-adapter boundaries verbatim.
- No withdrawal exists (D63); approval revocation after publication leaves
  the artifact standing (S8 revocation withdraws proof validity only).
- W2 owes: `publication-demo` + installer stage + bilingual README mention,
  the docs wave (sop-authoring.md lines 25–26 stale-CLI repair, the IR-F5
  51-count correction, verification.md consolidation), then independent
  review/assembly before integration-owned merge/push.
