# S12 W2 publication demo + docs development report — 2026-10-15

Worker dispatch `task_2ac7e3cc328d` (dispatch `ctx_4789b9492b00`) on
worktree branch `WayJ/s12-publication-demo`. Baseline asserted exactly at
the task's named carrier commit: `git rev-parse HEAD ==
05264d4b21520493aaf3f0b992cd2f2e0ac08854` == `WayJ/sprint-s12-sop-publication`,
tree clean before any write. Scope: wave 2 only — stories 5–6
(`publication-demo` + installer stage, bilingual README, docs wave incl.
the stale-CLI repair and the IR-F5 count correction) — exactly per master
ratification D54–D66 and the W2 stable API of
[the W1 integration review](2026-10-15-S12-core-integration-review.md).
No W1 product file touched.

## Master authorization on record (Orca ask, this dispatch)

The dispatch's design §12 obligation ("printed inspect command verbatim")
collided with its enumerated cli.py scope (narrow subcommand only): a probe
run on baseline `05264d4` showed **no existing `inspect --policy` choice can
read a sop-publish-family database** — both the expense default and
`content-publish` fail closed with
`CommandError: Load the policy version bound to this Work; migration is not implicit`
(`SopPublicationPolicy.version` is `"demo-1"`, so the version branch is
entered and the id/goal check rejects). The master authorized (verbatim
decision): add `sop-publish` to `inspect --policy` choices wired to
`SopPublicationPolicy` plus the publication demo grants, strictly additive
~4 lines mirroring the per-family pattern, no change to any existing
choice, flag or default; pin the choice with a test that inspects the demo
database end-to-end through the real CLI; keep the cli.py diff to the
choice wiring plus the narrow subcommand; record the authorization and the
motivating probe here. Implemented exactly so (`work_runtime/cli.py`:
subparser + dispatch + one inspect branch + import; pinned by
`test_printed_inspect_command_runs_verbatim`, which re-runs the printed
command through the real CLI and asserts exit 0 with
`"outcome": "succeeded"`, and re-run verbatim by installer stage 21).

## Commits (this dispatch)

| commit | subject |
|---|---|
| `a2b8f5e` | docs: S12 W2 publication demo scoped implementation plan (committed before code) |
| `b21ab0c` | feat: publication-demo harness, CLI entry point and sop-authoring publication docs (S12 D64) |
| `e4242a5` | feat: installed publication-demo proof stage and verification coverage (S12 D64/D65) |
| (this commit) | docs: S12 W2 bilingual publication-demo entries and demo report |

## What was built

- `work_runtime/publication_demo.py` (new, 377 lines): deterministic
  no-credentials `run_publication_demo(directory=None)` driving the frozen
  W1 core through its public API on one fresh store
  (`publication/runtime.sqlite` + `publication/store/`): lint prologue
  (dirty fixture card — a deepcopy of the packaged card with a whitespace
  goal and an unknown root field, exactly 2 diagnostics, first
  `EMPTY_VALUE` at `/policy/goal`; packaged `publishing.json` lint-clean
  with the pinned digest) → work created (card = document) → blocked
  proposal (S02) → tampered approval `EVIDENCE_AUTHENTICATION_FAILED`
  zero intake writes → valid signed `{digest, policy_version}` approval →
  intent accepted (business key = publication key) → response-loss
  dispatch commits exactly one hash-named artifact → restart reconcile
  one attempt `confirmed_succeeded` → runtime-written accepted proof
  (`sop-store`, `event_id` = operation id) → completion closed/succeeded →
  doctored same-version card: `REQUIREMENT_UNSATISFIED` first (D66 order),
  `OPERATION_CONTENT_CONFLICT` after its own approval, winner bytes
  unchanged → loader fail-closed (matching digest returns the card; absent
  version vs tampered scratch-copy file distinguishable) → approver-key
  rotation: fresh old-key envelope refused `EVIDENCE_KEY_RETIRED`, six
  tables + artifact bytes untouched → closing counts line. Approver keys
  are ephemeral `secrets.token_bytes(32)` keyring entries, never printed
  (only key ids); fixed clock `T0=2000000000`, grace 300.
- `work_runtime/cli.py`: narrow `publication-demo` subcommand
  (`--directory` like existing demos) + the master-authorized additive
  `inspect --policy sop-publish` choice (mirrors the `content-publish`
  branch incl. its `--policy-versions` parser.error guard).
- `scripts/verify_install.py`: stages 21/22 — module and console
  `publication-demo` outside the checkout, each verified by
  `require_publication_proof(stdout, source)` independently of stdout:
  artifact directory enumerated (exactly one hash-named `.json`, zero
  `.stage`), artifact parsed stdlib-only (exact keys, `artifact_version`
  1, bare packaged card identity, recomputed content digest, accepted
  `FILE-` receipt, digest-based publication key, `sha256(key)` file name),
  runtime store read directly (pub-1 closed/succeeded, pub-2 active, one
  `confirmed_succeeded` operation with one attempt and matching business
  key, three evidence rows incl. the runtime-written `sop-store` accepted
  proof bound to the receipt's `external_id`, the conflict approval bound
  to different content than the winner, 11 pinned command rows with the
  D66 conflict code and both blocked codes, events 11, schema 1), printed
  absent/tampered loader lines distinguishable; module run re-runs the
  printed inspect command verbatim. Docstring stages 21/22 and the final
  `=== PASS ===` summary extended. No skip path; no new global gate (D64);
  rehearsal set untouched.
- `tests/test_publication_demo.py` (new, 25 tests):
  `PublicationDemoTests` (12 — artifact/evidence/command/work pins
  recomputed locally with the canonical-JSON digest, verbatim inspect
  through the real CLI, printed artifact path, loader lines, pinned table
  counts works/commands/evidence/operations/events = 2/11/3/1/11),
  `PublicationDemoHygieneTests` (4 — sentinel survival, fresh folders,
  cwd outside the repo, planted-marker secret hygiene: patched key
  generator, neither marker bytes nor hex nor a locally computed envelope
  signature reach the output), `PublicationDemoCliTests` (2),
  `VerifyInstallPublicationProofTests` (7 — proof passes on real output;
  rejections for missing final line, flipped accepted status, deleted
  evidence row, tampered artifact bytes, forged duplicate command row,
  rewritten conflict receipt; fresh demo run per test so each rejection
  attributes to its own mutation).
- Docs: `docs/sop-authoring.md` (same commit as `publication_demo.py` per
  doc_sync_map — publication-demo demonstration subsection, trust limits,
  and the stale lines 25–26 repair: `lint-sop` shipped with S4, governed
  publication exists since S12); `docs/verification.md` (S12 section
  retitled core+demo waves with two new coverage bullets; IR-F5 count
  correction at the S4 section — file-adapter is **57 loader-counted
  tests: 51 in-file + 6 inherited conformance**; the stale RFC-002 §6
  "not implemented" sentence and the out-of-scope "Policy/SOP
  publication"/"no authority approval" phrasing repaired to the truthful
  current state); `README.md` + `README.zh-CN.md` (eighth-demo sections
  with truthful limits — trusted-local principals not authentication,
  config-only trust, no withdrawal this slice, no tenant auth/TLS/KMS/
  network, published cards never execute; feature bullets; verify-section
  clauses incl. the deliberate not-a-gate note; stale "policy publishing"/
  "规范发布" out-of-scope wording repaired).

## TDD evidence (RED → GREEN per task)

- **Task 1 (demo + CLI + sop-authoring.md):** RED
  `python3 -m unittest tests.test_publication_demo -v` → `ModuleNotFoundError:
  No module named 'work_runtime.publication_demo'` (`FAILED (errors=1)`,
  module absent); GREEN after the module + CLI wiring → `Ran 18 tests … OK`.
  One test-side fix during the cycle: the planted-marker patch needed two
  DISTINCT marker byte strings (the keyring validation rejects identical
  key material within a source). Full discover at the commit: **937 OK
  (skipped=3)** = 919 + 18.
- **Task 2 (verifier stage + verification.md):** RED
  `python3 -m unittest tests.test_publication_demo.VerifyInstallPublicationProofTests -v`
  → `AttributeError: module 'verify_install' has no attribute
  'require_publication_proof'` (`FAILED (errors=7)`); GREEN after the stage
  → `Ran 25 tests … OK`. Two ordering fixes during the cycle (both
  test-harness correctness, found by the failing rejection tests): proof
  fixtures switched from `setUpClass` to per-test `setUp` (fresh demo run
  per test — the rotation precedent — so mutations cannot bleed across
  tests), and the generic evidence/command count checks moved AFTER the
  per-event/per-id checks so each rejection names its own mutation. Full
  discover at the commit: **944 OK (skipped=3)** = 919 + 25.

## Verification battery (fresh, on the final tree)

| check | command | result |
|---|---|---|
| contracts | `python3 scripts/check_docs.py` | `checked 104 markdown files, 492 local links, 0 broken` — mi-1 caveat: the working-tree count includes the untracked, git-ignored historical `上一次建议.md`; the committed tree counts one fewer |
| tests | `python3 -m unittest discover -s tests -v` | `Ran 944 tests … OK (skipped=3)` (941 ok + 3 skips) |
| demo | `python3 -m work_runtime demo` | exit 0 |
| syntax | `python3 -m compileall -q work_runtime tests scripts` | exit 0 |
| site | `python3 scripts/check_site.py` | `checked 2 pages, 0 findings` |
| demos (eight explicit) | `demo`, `publish-demo`, `intervention-demo`, `adoption-demo`, `revocation-demo`, `compensation-demo`, `rotation-demo`, `publication-demo` | each exit 0 |
| rehearsals | `python3 -m unittest discover -s examples/rehearsal` | `Ran 15 tests … OK (skipped=1)` (pre-existing skip, unchanged) |
| installed verifier | `python3 scripts/verify_install.py` (serial) | `=== PASS ===`, exit 0, **zero SKIPPED stages**, unchanged prior stage set + new stages 21/22 with their independent publication proofs |

Exact skip names in the 944-run (identical to the baseline's three):
`test_opted_in_action_context_replay_returns_identical_receipt`
(`test_file_adapter.FilePublisherConformanceTests`) and the same-named
test in `test_publishing.FakePublisherConformanceTests` (both `adapter
does not opt into action/link execution context`), and
`test_absent_backend_is_a_bounded_startup_error`
(`test_ui_cli.AbsentBackendTests`) (`backend assembled: absent-install
path unreachable`).

## Scope and doc-sync audit

- `git diff --name-status 05264d4..HEAD` touches exactly the owned set:
  `work_runtime/publication_demo.py` (new), `work_runtime/cli.py`,
  `scripts/verify_install.py`, `tests/test_publication_demo.py` (new),
  `docs/sop-authoring.md`, `docs/verification.md`, the scoped plan, the
  two READMEs, this report. **Protected paths byte-identical** (explicit
  `git diff` over `runtime.py`, `ingress.py`, `authoring.py`, `policy.py`,
  `adapters.py`, `publication.py`, `file_adapter.py`, every other
  `*_demo.py`/`demo.py`, `ui_server.py`, `ui_demo.py`, `inspection.py`,
  `__init__.py`, `__main__.py`, `adapter_contract.py`,
  `scripts/check_docs.py`, `scripts/check_site.py`, `pyproject.toml`,
  AGENTS.md, roadmap, sprint files, `website/`, `examples/`): empty diff.
- Same-commit doc pairing per doc_sync_map: `b21ab0c` (creates
  `publication_demo.py`) also rewrites `docs/sop-authoring.md`;
  `e4242a5` (`verify_install.py` + tests) pairs with `docs/verification.md`.
  IR-F5 correction delivered as owed (57 = 51 + 6).

## Rulings (ledgered during execution)

- Plan-file relative-link fix rode in `b21ab0c`: the committed plan
  `a2b8f5e` had one broken relative link (`docs/sop-authoring.md` path),
  caught by the contracts gate; one-line fix, disclosed in the commit body.
- `publication-demo` was NOT added to the verification.md how-to-verify
  command block (plan Step 5 said to add it): matches the S10/S11
  precedent (compensation/rotation deliberately absent; "the first nine
  commands are the gates" stays true). Documented in the S12 coverage
  section and both READMEs instead.
- Report written after the battery (plan listed it before) so every figure
  quotes observed output.

## Honest remaining risks and boundaries

- Trust model unchanged: approvers/publishers are configured local
  principal names with shared-key HMAC signatures — config-only trust, no
  tenant authentication, TLS, KMS, non-repudiation or network; a
  configuration rollback revives a retired approver key. Cross-database
  store sharing remains operator discipline (MD-4).
- No withdrawal exists (D63); approval revocation after publication leaves
  the artifact standing. Published cards never execute (D62); the
  loader/pin accept `str` directories only (mi-3 minor, carried unchanged).
- The tampered-file loader refusal surfaces the adapter-level message
  ("committed artifact digest does not match its document")
  rather than the loader's own digest-mismatch text — bounded,
  distinguishable from absence, and pinned as such.
- `publication-demo`'s artifact `external_id`s embed random uuid4 (store
  receipt discipline) — DB bytes are not run-to-run identical, only the
  printed narrative and counts are deterministic; nothing printed depends
  on them.
- Owed next (not this dispatch): independent final acceptance, then the
  integration-owned ordinary main merge/non-force push. No merge, push,
  sprint state flip or release claim made here.
