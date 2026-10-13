# S4 foundation integration — 2026-10-13/14

Integration worker: s4-release-control (Claude Code), carrier `sprint-s4-adoption`
(branch `WayJ/sprint-s4-adoption`). Base for both foundations: `726a39c` (D22 ratification);
carrier before merge: `6f31601` (graph clarification + supervision plan). This note records the
independent review, the merges and the fresh post-merge evidence. No main merge, no push, no
acceptance — those belong to the later waves.

## Merge proof

| step | commit | content |
|---|---|---|
| merge 1 | `7b1ec54` | `WayJ/s4-sop-authoring` (tip `86d4a9e`, --no-ff) — authoring foundation |
| merge 2 | `a09d3ab` | `WayJ/s4-file-adapter` (tip `400a3f2`, --no-ff) — file adapter foundation, corrected |
| cherry-pick | `434a4a5` | builder check `fd8630c` — `.agents/notes/2026-10-13-S4-design-review.md` |
| cherry-pick | `629cf0a` | controller report tip `d119db3` — `.agents/notes/2026-10-14-S4-file-review.md` (per master follow-up msg_78569d674fe1, so the early-review evidence ships) |

**Tip drift disclosure:** the authoring branch advanced `d1051b6 → 86d4a9e` after my review
pass and before the merge. The delta is docs-only (a dated workflow-audit addendum to the
owner's own report: skill-timeline disclosure + plan-conformance audit, +59 lines in
`.agents/notes/2026-10-13-S4-sop-authoring-report.md`, no product/docs-code change) — inspected
at merge time and accepted. The file-adapter tip matched its reviewed correction `400a3f2`
exactly. **Sequencing note:** master's follow-up (msg_78569d674fe1, 16:23Z) asked me to HOLD
the authoring merge until the exact settled tip was sent; that durable message reached me only
at my post-merge inbox check, after merge `7b1ec54` had already included `86d4a9e` — the audit
commit itself (authored 16:25Z, branch clean and unmoved since). **Master ruled via Orca ask (2026-10-14):
`86d4a9e` is the settled audited tip and product-identical to `d1051b6`; merge `7b1ec54`
stands, no revert/re-merge.** A small docs-only authoring alignment followup (plan/report
wording/form only) may land on the branch later; per master it merges normally when ready with
no product change and no full re-review. The same follow-up's directive to ship the controller
evidence tip `d119db3` is satisfied by `629cf0a`, and the builder note `fd8630c` is present as
`434a4a5` — both verified byte-identical to their source commits (`git diff --stat` empty).
Post-merge proof (469 tests, gates, demos, lifecycle-empty diff) was preserved untouched by
these docs-only additions.

## Independent review (both foundations, against base 726a39c)

### Authoring (`work_runtime/authoring.py`, `tests/test_authoring.py`, docs, examples)

Verdict **pass**. D22 conformance verified in source and tests: exactly-14 diagnostic codes;
strict root/policy/defaults/facts `{id}`/collections/rules 14-field cardinality; pinned
defaults and rule handling values (block/escalate/forbidden/explicit); global fact/collection/
rule ID namespace; reserved tokens (`goal` capability, `document` collection id); provenance ≠
business scope — scope is the literal `document` or a declared collection id (probe: using
`policy.source.document`'s value as scope → `UNKNOWN_REFERENCE` at `/rules/0/scope`); must AND
forbidden both mandatory (all-forbidden valid, empty rules → `NO_MANDATORY_RULE`, advice never
counts); iterative JSON-native preflight (exact types, subclasses rejected without invoking
`__repr__`/`__iter__`/`keys` hooks — hostile-hook test; finite floats; |int| ≤ 2^53−1;
UTF-8-encodable strings/keys; active-path cycle detection, repeated acyclic aliases valid);
schema cascade suppressed on preflight findings; pointer order `(path, code, message)` with
RFC 6901 `~0`/`~1` escaping and identical-triple dedup; **iterative Tarjan SCC per the D22
graph clarification** — one diagnostic per cyclic component at the lowest document-index
member, long flat chains fine (2000-rule chain lints clean; 1500-rule cycle → exactly one
`CYCLE`; 1200+short-cycle → one component); `sop_digest` reuses `policy.digest` only after the
clean gate, key-order neutral, bounded no-payload-leak `ValueError` otherwise. No natural-
language evaluation anywhere; static-only limitation documented.

**RED evidence** (disposable worktrees): new test module against base `726a39c` → module
import error (collection RED); mutations on the tip — SCC filter removed (suite fails),
reserved-`goal` check disabled (3 failures), digest clean-gate skipped (27 failures); all
restored to green. **Probes:** provenance≠scope (above), whitespace-only string →
`EMPTY_VALUE` untrimmed, determinism across calls, key-order-neutral digest of the packaged
cards. Packaged digests recorded: `expense.json` =
`4876285f00f5f9ad0287e92825f1aec212e9fc3bce10fd8c073bd2151d817627`, `publishing.json` =
`56c85d32da9a9eee6330326e2d14ce0661dbc26d782b13d0259c3f149e6be000`.

### FilePublisher (`work_runtime/file_adapter.py`, `tests/test_file_adapter.py`, docs)

Verdict **pass** (full review at `9c22099` recorded in
`.agents/notes/2026-10-14-S4-file-review.md` @ `d119db3`; correction `400a3f2` re-verified
here). The correction pins both surrogate gates to plain `ValueError` (no raw
`UnicodeEncodeError` class, no escaped surrogate render in the message) and corrects the two
stale report statements; the owner reproduced the mutation RED before restoring. Independent
re-verification at `400a3f2`: 50/50 file tests, 323/323 suite, and my M4 mutation (remove the
value-string UTF-8 gate) now fails exactly `test_lone_surrogate_strings_are_rejected_without_
leaking_them`. Carried-over mutation REDs at the byte-identical product code: overwrite-capable
commit (10 failures), skipped winner-digest comparison (2), bool `artifact_version` (1).
`os.link` exclusive stage→commit, winner read-back validation, own-stage cleanup, `uniqueness=()`
with no extra business claim, no production crash flags, subprocess races/death real, honest
platform boundaries (best-effort directory fsync, POSIX; hardlink required, explicit `OSError`;
no power-loss/hostile-FS/symlink/distributed claims).

### Cross-foundation observation (non-blocking)

The two JSON-native gates count depth differently: authoring allows 64 container levels below
the root value (root = depth 0), the file gate allows 64 containers including the root dict
(root = depth 1) — a one-level difference at the extreme boundary. Both are self-consistent,
test-pinned and independently documented; the gates never exchange data in S4. Recommended
wave-3 nicety: a one-line cross-reference between `docs/sop-authoring.md` and
`docs/file-adapter.md` (both owners independently suggested the same).

## Post-merge verification (fresh, on carrier tip `434a4a5`)

- `python3 -m unittest discover -s tests` → **Ran 469 tests … OK** (273 baseline + 146
  authoring + 50 file; baseline intent unchanged, no existing test edited by either branch).
- `python3 scripts/check_docs.py` → 44 markdown files, 139 local links, **0 broken**.
- `python3 -m compileall -q work_runtime tests scripts` → clean.
- `python3 -m work_runtime demo`, `publish-demo`, `intervention-demo` → all exit 0.
- Lifecycle untouched: `git diff --stat 726a39c..HEAD -- work_runtime/runtime.py policy.py
  adapters.py cli.py adapter_contract.py` → **empty**.
- Master docs preserved: vs `6f31601`, `AGENTS.md`, the sprint plan, opening note and roadmap/
  E5-GUI docs are unchanged; the diff is additions only (`docs/sop-authoring.md`,
  `docs/file-adapter.md`, two owner plans, plus `.agents/` notes via merges).

## Delivered interfaces for wave 3 (adoption harness)

- `work_runtime.authoring.lint_sop(value) -> list[{code, path, message}]` (deterministic,
  never raises) and `sop_digest(value) -> str` (`ValueError` unless lint-clean) — canonical
  digest shared with `policy.digest`; 14 codes: MISSING_FIELD, UNKNOWN_FIELD, TYPE_MISMATCH,
  EMPTY_VALUE, INVALID_VALUE, DUPLICATE_ID, UNKNOWN_REFERENCE, CYCLE, NO_MANDATORY_RULE,
  NOT_JSON_NATIVE, NONFINITE_FLOAT, INVALID_UNICODE, INTEGER_RANGE, DEPTH_LIMIT.
- `work_runtime.file_adapter.FilePublisher(directory)` — `execute(key, document,
  content_digest)` / `lookup(key)`; contract `actions=("content.publish",)`,
  `idempotency_scope="directory:key"`, `retention="lifetime-of-directory"`,
  `lookup_consistency="authoritative-by-key"`, `uniqueness=()`; artifact =
  `<sha256(key UTF-8)>.json` with exact keys artifact_version(1)/key/content_digest/document/
  receipt. Platform bounds: trusted-local directory, hardlink-support required, best-effort
  directory fsync, no power-loss/hostile-FS/distributed-exactly-once claims.
- Packaged single-truth examples: `work_runtime/data/sop/expense.json`,
  `work_runtime/data/sop/publishing.json` (pyproject package-data wiring is wave 3's);
  19 invalid fixtures under `examples/sop/` with pinned code expectations (incl.
  `long-chain-cycle.json`, 80-rule single-component cycle).

## Remaining for later waves

Wave 3 (dependent adoption harness): `adoption_demo.py`, CLI `lint-sop` (loader duplicate-key/
nonfinite/UTF-8/1MiB rules, exits 0/1/2), pyproject package-data, `verify_install` adoption
stages + CI, contributor guide; wave 6 guide-only rehearsal; wave 7 accept → ordered main
merge/push/CI. No lifecycle edits anywhere in scope.

## Docs-only alignment merge (2026-10-14, task_b0d29bc4892d)

Merge `acdb436` brings the authoring owner's plan/report alignment tip `a672ae5` (the followup
master announced). Reviewed delta vs the already-merged `86d4a9e`: exactly two owned files
(`docs/superpowers/plans/2026-10-13-s4-sop-authoring.md` +146/−49, own report +20), no
product/tests/examples changes. Content verified truthful: the plan's alignment note discloses
the writing-plans timeline honestly (authored 2026-10-13 without it; loaded only for the
2026-10-14 audit and this alignment); the unknown-field anchor is corrected to the
implemented, tested and master-accepted key-pointer form (`/extra`, "formerly pinned here as
`''`" — history preserved, not erased); a Review Focus section and per-task
Consumes/Produces Interfaces were added; folded steps became explicit five-phase checkboxes
with commit identities annotated (`→ 008d429` … `→ d1051b6`); the stale `_sorted_dedup` name
was corrected to `_finalize`. All aligned statements match the product I reviewed at
`d1051b6`. Evidence per dispatch: `check_docs` → 44 files/139 links/0 broken and
`git diff --stat cc40ef0..HEAD -- work_runtime tests examples scripts pyproject.toml` →
**empty** (code byte-identical; no 469 rerun needed for this reversible docs-only delta).
Cosmetic only: task checkboxes other than Task 0 remain unchecked, preserving the historical
artifact per the alignment note. No accept/main merge/push/teardown; master authorization,
E5-GUI docs and all previous merges untouched (additions only). Final carrier tip after this
note: see the commit this addendum rides on.
