# S12 W1 core integration review — PASS, assembled — 2026-10-15

Independent Orca review/assembly of the S12 governed SOP rule-card
publication core, distinct from the owner's internal review recorded in
[the core report](2026-10-15-S12-core-report.md). Reviewer checkout:
`s12-release-control` (control branch `WayJ/s12-release-control`, base
`24dd14c` = carrier base, clean at start and before the merge). No product
file was modified by this review; every gate, demo, rehearsal, installer
run, RED replay and independent probe ran from `git archive` extractions of
the accepted source and the baseline into disposable `/tmp` directories,
plus fresh `/tmp` stores. Verdict: **PASS — no material finding**; three
minor observations recorded below (mi-1…mi-3), none blocking, none
requiring a product fix. This review proves the **local S12 W1 core
only** — `publication-demo`, the installer stage, the docs wave, final
acceptance and the main merge are W2+ and remain owed.

## Scope and source

- Accepted source: `WayJ/s12-publication-core` tip
  **`9baa86d826db70f1d3597bbdfc023109feb8c0f1`** (`git rev-parse` verified
  equal to the branch tip), **8 commits** `2b487a9..9baa86d` on base
  `24dd14c` — plan `2b487a9`, `read_validated` `460bbc8`, key+store
  `e95884d`, loader/pin `c7dc3d0`, governed flow `0ea9a99`, rotation
  battery `3f559b0`, test cleanup `ae801a1`, report `9baa86d` — matching
  the dispatch and the owner's commit table exactly.
- Carrier baseline: `WayJ/sprint-s12-sop-publication`
  `24dd14c5b9270a0e00ca1c0413eaa011017644be`, worktree clean (asserted).
- Changed files: **exactly 10** (`git diff --name-status` verified, count
  asserted by the dispatch): `work_runtime/publication.py` (new, 262
  lines), `work_runtime/file_adapter.py` (+15), `tests/test_publication.py`
  (new, 599), `tests/test_publication_rotation.py` (new, 274),
  `tests/test_file_adapter.py` (+68), `docs/sop-authoring.md`,
  `docs/file-adapter.md`, `docs/verification.md`, the core plan, the core
  report.
- **Protected paths byte-identical** `24dd14c..9baa86d`: the changed-file
  list is exhaustive, and an explicit `git diff` over `runtime.py`,
  `ingress.py`, `authoring.py`, `policy.py`, `adapters.py`, `cli.py`,
  `adapter_contract.py`, every `*_demo.py`/`demo.py`, `publishing.py`,
  `ui_server.py`, `inspection.py`, `scripts/verify_install.py`, both
  READMEs, `pyproject.toml`, `work_runtime/__init__.py` and the site/web
  assets is empty. `publication_demo.py` does not exist (W2);
  `publication-demo` correctly exits 2.
- **Same-commit doc pairing (the S10 lesson) holds**: every commit touching
  `work_runtime/publication.py` (`e95884d`, `c7dc3d0`, `0ea9a99`) also
  touches `docs/sop-authoring.md`; the `work_runtime/file_adapter.py`
  commit (`460bbc8`) also touches `docs/file-adapter.md`; the
  `publication_demo.py` row owes nothing yet (file absent). The test-adding
  commits pair with `docs/verification.md`; `ae801a1` (test cleanup only,
  adds no test) touches no doc and no `doc_sync_map` row covers test files —
  no arrears.

## Review against D54–D66 and the IR pins

- **D56/IR-F1/IR-P16 (digest key):** `_identity_key` returns
  `"sop-pub:" + digest([policy_id, policy_version])` with bounded
  identity validation; my probe reproduced the IR-P16 hostile pair
  `("collide:one","v1")` vs `("collide","one:v1")` as a **non-collision**
  (both lint-clean, same delimiter-joined form, different keys, key shape
  `sop-pub:`+64 hex, exact equality against the digest form) and — stronger
  than the unit pin — **published both cards end-to-end** through the
  governed flow: two confirmed operations, two hash-named artifacts, no
  `OPERATION_CONTENT_CONFLICT` anywhere.
- **D55/D60 (thin wrapper):** `SopPublicationStore` delegates
  `execute`/`lookup` verbatim to an unchanged `FilePublisher` and declares
  `actions=("sop.publish",)`, `uniqueness=("publication.key",)`. The
  `file_adapter.py` diff is append-only — the single `read_validated`
  method; `lookup`/`execute` are byte-identical to baseline (pinned by the
  untouched 45-case conformance suite plus the inherited mixin).
- **D61/IR-F4 (additive read):** `read_validated` mirrors `lookup`'s key
  gate and corruption matrix, returns `None` on absent (probed), the full
  validated artifact on hit (probed, detached parse), never rewrites
  corrupt bytes (probed, file bytes unchanged after refusal). The loader
  converts absence into its own bounded error so **corrupt and absent stay
  distinguishable** (probed: messages differ); a missing store directory
  raises the absent error **without creating the directory** (probed).
- **D57 (admission lint):** dirty card → bounded unpersisted `ValueError`
  with zero `works` rows and no store directory (probed); clean card →
  `work["document_digest"] == sop_digest(card) == stored
  content_digest == receipt digest` (probed end-to-end).
- **D58 (version-bound approval):** tampered envelope →
  `EVIDENCE_AUTHENTICATION_FAILED` with **zero intake writes** (probed:
  six-table counts identical); wrong-version → accepted as candidate, turns
  `invalid` at verification, proposal stays blocked (probed);
  wrong-digest → verifies on shape but S02 stays unsatisfied (owner test
  + code read: `has()` binds `data.digest` to the current
  `document_digest`).
- **D59 (bare card + runtime-written proof):** the committed artifact's
  `document` is the bare card (probed); the `accepted` proof is
  runtime-written — `source == "sop-store"` which is **absent from
  grants**, `event_id == operation id`, status `verified`, digest-bound,
  `external_id` FILE-prefixed (probed).
- **D66/IR-F3 (pinned conflict order):** both stages probed on my own flow
  — a second work (same card or doctored same-version content) is first
  refused `REQUIREMENT_UNSATISFIED`, and only after recording and
  verifying **its own** `card_approval` does the persisted
  `OPERATION_CONTENT_CONFLICT` surface, with the winning artifact's bytes
  unchanged and still exactly one `.json` (owner tests pin the same order:
  `test_cross_work_same_card_conflicts_only_after_its_own_approval`,
  `test_doctored_same_version_card_conflicts_after_its_own_approval`).
- **Rotation (S11 semantics):** keyring approver — retained-retired old key
  → `EVIDENCE_KEY_RETIRED`; dropped old key →
  `EVIDENCE_AUTHENTICATION_FAILED` in both selector-less and cited forms;
  **same `command_id` re-signed under the new key replays the original
  receipt verbatim with zero table writes**; new `command_id` on the same
  `(source, event_id)` reports current status with exactly `commands +1`,
  `evidence` unchanged; after a completed publication every refusal leaves
  the **six tables and the committed artifact bytes** untouched; a
  pre-rotation approval still verifies after rotation (key-agnostic
  fingerprints) and a new version publishes under the rotated key — all
  probed by me, all pinned by `PublicationRotationTests` (6 tests).
- **D62 (loader, no wiring):** fail-closed matrix probed — absent version,
  missing directory (never created), corrupt bytes, tampered
  document/stale digest, doctored `key` field, foreign card and non-card
  document committed under the key by raw adapter use (MD-4 class) each
  refuse bounded. `pinned_card` refuses a wrong or malformed pin;
  `published_card_matches` compares `(id, version, goal)` only. **No
  Runtime wiring** (no module under `work_runtime/` or `scripts/` imports
  `publication` — grep-verified), no card→policy compilation, published
  cards never execute, and **no withdrawal surface** exists (D63; the only
  "withdraw" hit is the docstring's non-claim).
- **IR-F2 (§8 re-frame):** no `revise_document` test exists; the docs
  state card-immutability within a work (changes enter as new works, new
  version strings) exactly as ratified. IR-F5 and the
  `sop-authoring.md:25–26` stale-CLI repair are correctly left to W2 (the
  diff does not touch those lines).

## Fresh battery on the extracted committed source

All runs from `git archive 9baa86d8` into a disposable `/tmp` tree (the
committed tree, not any worktree):

| check | result |
|---|---|
| tests (`unittest discover -s tests -v`) | `Ran 919 tests … OK (skipped=3)` |
| skip names | the exact three pre-existing: two `test_opted_in_action_context…` conformance skips (`test_file_adapter.FilePublisherConformanceTests`, `test_publishing.FakePublisherConformanceTests`) + `test_absent_backend_is_a_bounded_startup_error` (`test_ui_cli.AbsentBackendTests`) — identical to my own baseline run |
| baseline battery (`git archive 24dd14c`) | `Ran 874 tests … OK (skipped=3)`, same three skip names — 874 + 45 new = 919 (33 publication + 6 rotation + 6 `ReadValidatedTests`; file-adapter in-file `def test` 45 → 51, loader-counted 51 → 57) |
| contracts (`check_docs.py`) | `checked 102 markdown files, 486 local links, 0 broken` — see mi-1 |
| demo (`work_runtime demo`) | exit 0 |
| syntax (`compileall -q work_runtime tests scripts`) | exit 0 |
| site (`check_site.py`) | `checked 2 pages, 0 findings` |
| seven existing demos | `publish-demo`, `intervention-demo`, `adoption-demo`, `revocation-demo`, `compensation-demo`, `rotation-demo` + `demo` each exit 0 |
| `publication-demo` | exit 2 (unknown command — correctly absent until W2) |
| rehearsals (`discover -s examples/rehearsal`) | `Ran 15 tests … OK (skipped=1)` (pre-existing skip) |
| installed verifier (`verify_install.py`, serial) | `=== PASS ===`, exit 0, zero SKIPPED stages, unchanged stage set |
| RED replay on the parent tree | `tests.test_publication` → `ImportError: Failed to import test module` (module absent); `tests.test_file_adapter.ReadValidatedTests` → `AttributeError: module 'tests.test_file_adapter' has no attribute 'ReadValidatedTests'`; both `FAILED (errors=1)` — observed verbatim on the `24dd14c` extraction |

## Independent probes (mine — public API, `/tmp`, ephemeral secrets never printed)

Four probe scripts (`/tmp/s12-probes/`, disposable), written without the
owner's test helpers, driving the extracted source through its public
surface: **A** key non-collision incl. the both-publish end-to-end proof;
**B** `read_validated` + loader fail-closed matrix; **C+D** the governed
flow end-to-end (dirty-card refusal → blocked proposal → tampered approval
zero-write refusal → wrong-version candidate → valid approval → verbatim
command replay → response-loss dispatch → restart one-attempt reconcile →
runtime-written accepted proof → completion → D66 conflict order for both
the same-card and doctored-card second works with winner bytes intact);
**E** the full rotation interaction incl. six-table and store-byte
preservation. All checks printed PASS; exit 0 for every probe.

## Findings (all minor; none material; no product fix required)

- **mi-1 (report accuracy, no repo defect):** the owner report's contracts
  line says `checked 103 markdown files`; the **committed** tree counts
  `102` files / 486 links / 0 broken. The 103rd file was the owner
  worktree's untracked, self-ignored
  `.superpowers/sdd/2026-10-15-s12-core/progress.md` (ignored via
  `.superpowers/sdd/.gitignore` `*`, hence invisible to `git status`).
  Gate outcome identical. W2 reports should quote committed-tree counts.
- **mi-2 (test placement, cosmetic):** `ReadValidatedTests` is appended
  after the `if __name__ == "__main__": unittest.main()` block in
  `tests/test_file_adapter.py`, so running the file directly as a script
  would not execute the six new cases (the configured gate
  `unittest discover` and module import are unaffected). Optional W2
  tidy-up.
- **mi-3 (owner-disclosed, carried):** `load_published_card`/`pinned_card`
  accept a `str` directory only; a `Path` argument fails with the
  absent-version message — bounded and fail-closed but potentially
  misleading. One-line `os.PathLike` acceptance + one test if wanted.

## W2 stable API (verified empirically, for the demo/docs owners)

At the assembled control tip:

```
from work_runtime.publication import (
    PUBLICATION_KEY_PREFIX, publication_key, SopPublicationStore,
    load_published_card, pinned_card, published_card_matches,
    SopPublicationPolicy)
from work_runtime.file_adapter import FilePublisher  # read_validated(key) added
```

- `publication_key(card) -> str`: `"sop-pub:" + digest([policy.id,
  policy.version])` (64-hex tail); bounded `ValueError` on a non-card or
  missing/empty/non-str identity (messages name the requirement, never the
  content).
- `SopPublicationStore(directory)`: `.contract` declares
  `actions=("sop.publish",)`, `idempotency_scope="directory:publication-key"`,
  `retention="lifetime-of-directory"`,
  `lookup_consistency="authoritative-by-key"`,
  `uniqueness=("publication.key",)`; `execute(key, document,
  content_digest)` / `lookup(key)` delegate to `FilePublisher` verbatim;
  `.publisher` is the underlying adapter.
- `load_published_card(directory, policy_id, policy_version) -> dict`
  (bare stored card; bounded distinguishable `ValueError`s: absent — incl.
  missing directory, never created —, corrupt, digest mismatch, identity
  mismatch); `pinned_card(…, expected_digest)` adds the exact-pin check;
  `published_card_matches(card, policy) -> bool` compares
  `(id, version, goal)` only. No Runtime wiring; cards never execute.
- `SopPublicationPolicy`: `id="sop-publish"`, `version="demo-1"`,
  `goal="sop.published"`, `evidence_sources={"card_approval": "sop-owner",
  "accepted": "sop-store"}`; admission lints via `sop_digest`;
  `card_approval` data exactly `{"digest", "policy_version"}` bound to the
  card's version; `accepted` data exactly `{"digest", "external_id"}`;
  S02/S03 with S03 excluded from blockers; `operation_key` =
  `publication_key(work["document"])`.
- Demo grants (Q7): `{"agent": {"work.manage", "sop.publish"},
  "sop-owner": {"evidence.write"}}`; approver keyring via
  `SourceKey(key_id, secret, current, not_before, not_after)` with S11
  rotation semantics; `publication_demo.py` owes
  `docs/sop-authoring.md` pairing per `doc_sync_map`. W2 docs also owe the
  `sop-authoring.md:25–26` stale-CLI repair and the IR-F5 count correction
  (file-adapter is now 57 loader-counted cases: 51 in-file + 6 inherited).

## Assembly record

- Control `WayJ/s12-release-control`: merge commit **`1a83725`**
  (`merge: assemble S12 publication core 9baa86d into release control`,
  `--no-ff` on base `24dd14c`), then this note committed on top.
- Carrier `WayJ/sprint-s12-sop-publication`: fast-forwarded to the control
  tip — this note's own commit (a commit cannot contain its own hash; the
  exact SHA equals `git rev-parse` of this file's commit and is reported to
  the coordinator; contains `9baa86d` + merge `1a83725` + this note). W2
  builds on that exact SHA.
- Post-assembly gates re-run on the control tree: figures recorded in the
  dispatch report to the coordinator (full battery 919 OK / skipped=3 with
  the same three skip names; `check_docs.py` 102 files / 486 links / 0
  broken — this note lives under `.agents/`, excluded from the scan;
  `compileall` clean; `check_site.py` 0 findings; `demo` exit 0) —
  identical to the accepted-source runs.
- No main/root merge, no push, no sprint `state` flip, no acceptance
  record, no debt/ledger change — final S12 acceptance waits for W2 and a
  fresh final review. All worktrees preserved; nothing torn down.

## Risks / limits (unchanged, truthful)

Cross-database store sharing remains operator discipline (MD-4: the loader
and reconcile both fail closed, but nothing prevents two databases pointing
at one directory). Trust model unchanged: approvers are configured local
names with shared-key HMAC signatures; config-only trust, config-rollback
key revival, and no TLS/KMS/tenant-authentication/non-repudiation or
distributed exactly-once claim. No withdrawal exists (D63); approval
revocation after publication leaves the artifact standing. W2 owes
`publication-demo` + installer stage + bilingual README mention and the
docs wave (stale-CLI repair, IR-F5 count correction, verification.md
consolidation) before independent final acceptance and the
integration-owned main merge/push.
