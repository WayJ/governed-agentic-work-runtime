# S4 FilePublisher early review (independent, file foundation only)

Reviewer: s4-release-control worktree (WayJ/s4-release-control @ fd8630c), dispatched while the
authoring developer continues. Reviewed `WayJ/s4-file-adapter` @ **9c22099** (clean tip, base
`726a39c`) against ratified **D22** in carrier `sprint-s4-adoption` @ 6f31601. Scope: the five
changed files only (`work_runtime/file_adapter.py` 294, `tests/test_file_adapter.py` 723,
`docs/file-adapter.md`, worker report, plan); no Runtime/Policy/authoring/CLI/pyproject files
touched by the branch (verified by diff-stat). Read-only review: no product/docs/master edits,
no merges/pushes; this note only.

## Verdict

**Implementable and integration-ready.** Full battery reproduced on a disposable detached
worktree at 9c22099: **50/50** file tests, **323/323** whole suite (273 baseline + 50),
`demo`/`publish-demo`/`intervention-demo` all exit 0, `check_docs` 41 files/132 links/0 broken,
`compileall` clean. One **non-blocking test-coverage finding** (F1) plus two stale statements in
the worker report (S1, S2); no product defect found.

## D22 conformance (code + tests + probes)

- **Strict native ONE snapshot** — iterative exact-type walk (`type() is`), root must be plain
  dict, depth ≤ 64 containers (root = 1; tests pin 63-nested-valid/64-invalid), finite floats,
  |int| ≤ 2^53−1, plain-UTF-8 keys and strings (empty property keys valid per D22 B4 — pinned by
  test and probe), acyclic aliases copied per occurrence, cycles via active-path identity
  without RecursionError. Digest is computed **from the one detached snapshot**, and the stored
  document is re-gated and re-digested on every read — `SnapshotDetachmentTests` pin caller
  mutations post-publish.
- **Original key + actual document digest** — artifact embeds the original key (NUL/whitespace/
  unicode keys round-trip, probe-verified), `content_digest` recomputed from stored contents;
  wrong-key and tampered-digest artifacts are refused (`CorruptionTests`), file never rewritten.
- **artifact_version bool rejected** — `type(v) is not int or v != 1`; the `true` corruption
  variant is tested and mutation-verified (M3 below).
- **os.link exclusive commit / winner readback / cleanup** — exclusive `open("xb")` `<uuid>.stage`
  + fsync, `os.link(stage, final)`, `FileExistsError` → read/validate winner (same content →
  winner's receipt; different → bounded `ValueError`, no overwrite), own-stage unlink in
  `finally`, foreign stages untouched, best-effort directory fsync. No rename fallback, no
  production crash flags — API is exactly `FilePublisher(directory)`.
- **Real subprocess race/death** — 5-way same-key race (all identical receipts, one artifact,
  zero stage leaks), 3-vs-3 mixed-content race (one artifact, losers exit `ERROR:ValueError`),
  death before link via `os.link`-wrapped `os._exit(77)` (one fsynced stage, zero artifacts,
  lookup None, retry succeeds, stale stage untouched), death after commit via `os._exit(78)`
  (one artifact, own stage cleaned, stable receipt). No sleep/timing assertions anywhere.
- **Conformance + actual artifact count** — `AdapterConformanceMixin` adopted with
  `effect_count` = real hash-named file enumeration; `RuntimeDispatchTests` drives the unchanged
  Runtime + PublishingPolicy to `confirmed_succeeded`, C04 satisfied, artifact key equals the
  Runtime business key.
- **Doc honesty** — `docs/file-adapter.md` claims no power-loss durability, no hostile-FS/
  symlink defense, no distributed exactly-once; hardlink-required and explicit-OSError behavior
  stated; committed-bytes stability correctly scoped (racing stages may differ, committed bytes
  never change). Matches the code.

## Independent source audit (no-exit / no-rename)

Direct read of `file_adapter.py`: imports are `hashlib/json/math/os/uuid` only (no `shutil`);
the complete filesystem-mutation inventory is `makedirs` (constructor), exclusive stage
`open`+`fsync`, `os.link` (the commit) and own-stage `unlink`. No `_exit`, `rename`, `replace`,
`remove`, `rmtree`, `system` or `popen` anywhere; no crash/timeout/fault constructor options
(pinned by `ApiShapeTests`' signature check). Property confirmed.

## RED evidence (reproduced)

- **Base RED**: the new test module against base `726a39c` product code fails at import
  (`ModuleNotFoundError: work_runtime.file_adapter`, 1 collection error) — the trivial import
  RED the report documents; running discovery at the bare base correctly finds **0 tests**
  (the file does not exist there), which I have *not* counted as RED.
- **Bounded mutations** (applied to a disposable copy, restored after each; full file suite):
  - **M1** `os.link` → `os.replace` (overwrite-capable commit): **10 failures** — non-overwrite,
    race and corrupt-winner properties are strongly pinned.
  - **M2** skip winner-digest comparison in the `FileExistsError` path: **2 failures** —
    changed-content refusal and mixed-race loser handling pinned.
  - **M3** accept bool `artifact_version` (`version != 1` only): **1 failure** — strict int pin.
  - **M4** remove `_check_utf8(value)` on document strings: **0 failures — mutation survives.**
- **Direct probes on the pristine tip** (beyond the suite): NUL-byte and whitespace-only keys
  accepted, hash-contained, original key embedded verbatim; surrogate value → **plain
  `ValueError`** with the bounded message (no leak); empty property key + repeated alias commit
  detached from caller mutation.

## Findings

- **F1 (non-blocking, test-coverage gap — recommend original-owner fix before/with wave-2):**
  M4 survives because `UnicodeEncodeError` is a `ValueError` subclass and Python renders the
  surrogate in its message only as escaped text (`\ud800`), so
  `assertRaises(ValueError)` + `assertNotIn("<surrogate>", msg)` both pass while the *raw
  exception class* leaks (probe on mutated code: class `UnicodeEncodeError`, message
  `'utf-8' codec can't encode character '\ud800' ...`). The product is compliant today (probe
  on pristine tip: plain `ValueError`, bounded message), but D22's "no raw UnicodeEncodeError
  leakage" property is unpinned by the suite — a regression deleting that one gate would go
  green silently. One-line strengthening: assert `type(raised.exception) is ValueError` (or the
  exact bounded message) in `test_lone_surrogate_strings_are_rejected_without_leaking_them`
  and the key-surrogate sibling. Not a product defect; no self-fix per instructions.
- **S1 (report stale statement — the one flagged for honest correction):** the report's
  Platform-notes line "(no rename fallback — asserted in `ApiShapeTests` against mechanism
  tokens `os.rename`/`os.replace`/`shutil`/`_exit`)" refers to the keyword-scan assertion that
  commit `1bb1342` **removed** per coordinator redirect. The actual current verification basis
  is threefold: (i) `ApiShapeTests`' constructor-signature check (no flags exist to misuse),
  (ii) the behavioral tests — M1 above shows a rename/replace fallback breaks 10 of them — and
  (iii) the direct AST call-inventory audit recorded in the report's own redirect paragraph,
  which my independent source audit above re-confirms. The property holds; only the sentence's
  "asserted in ApiShapeTests" attribution is stale.
- **S2 (report stale ruling):** Design ruling 2 still lists *empty* keys among the rejected
  ("only empty/non-string/non-UTF-8 keys are rejected"), but `9c22099` + D22 B4 + the code and
  `test_non_string_dict_keys_are_rejected_and_empty_keys_are_valid_json` make empty document
  property keys valid (the nonempty rule is the idempotency key's). First half of the ruling
  (whitespace-only accepted) is correct; the parenthetical is stale.
- Minor: the Task-5 table row still reads "51/51 … 324 OK" predating the redirect's −1 test;
  the redirect paragraph's "Final suite: 323" supersedes it — chronological record, acceptable.

## Boundaries respected

No product/docs/master edits, no merges/pushes, no nested agents, no local approval UI; authoring
domain and old history untouched; disposable worktrees removed after verification. Foundation
integration can reuse tip 9c22099 with this evidence; F1 and the S1/S2 wording corrections
belong to the original owner.
