# S4 file adapter report — 2026-10-13

Worker: Orca `s4-file-adapter` session (branch `WayJ/s4-file-adapter`), base `726a39c`.
Scope held: `work_runtime/file_adapter.py`, `tests/test_file_adapter.py`, `docs/file-adapter.md`,
plan `docs/superpowers/plans/2026-10-13-s4-file-adapter.md`. No Runtime/Policy/authoring/CLI/README/
pyproject/CI/ledger/baseline-test files touched; no merges, no pushes, no nested agents.
Spec: [S4 design](../../docs/superpowers/specs/2026-10-13-s4-adoption-design.md) D22 (master-ratified before code).

## Named RED/GREEN evidence

| step | RED (observed verbatim) | GREEN |
|---|---|---|
| Task 2 core (gate, snapshot, atomic commit, lookup) | `ModuleNotFoundError: No module named 'work_runtime.file_adapter'` (24 tests, all error at import) | 24/24 OK; full suite 297 OK. Commit `a2bd20e` |
| Task 3 conformance/corruption/detachment/staging/messages/API shape | first run: 1 failure + 3 errors — **test-harness bugs, product code unchanged** (see findings) | 46/46 OK; full suite 319 OK. Commit `4545dff` |
| Task 4 subprocess races and process death | first run: `test_death_before_link` `AssertionError: 0 != 77` — test bug: `os.link` patch was appended after the publish block; child published first. Restructured to prelude/publish/tail | 50/50 OK; `SubprocessRaceTests` ×3 → OK/OK/OK (no flakiness, no timing assertions); full suite 323 OK. Commit `c3cb50d` |
| Task 5 Runtime smoke + docs | none — verification pass on completed product (predicted in plan; smoke passed first run) | 51/51 OK; full suite 324 OK. Doc + report commit |

Mid-GREEN fix (Task 2): first implementation draft omitted the `_read_validated` method
(`AttributeError` on 11 tests); one method added, no behavior change.

## Outcomes

- **Gates (final):** `python3 -m unittest discover -s tests -v` → **Ran 323 tests ... OK**
  (273 baseline preserved + 50 new); `python3 scripts/check_docs.py` → 46 files / 132 links /
  **0 broken**; `python3 -m compileall -q work_runtime tests scripts` → clean; `python3 -m
  work_runtime demo`, `publish-demo`, `intervention-demo` → all exit 0.
- **File counts / corruption:** replay and restart return the identical winning receipt with
  committed bytes unchanged and exactly one 64-hex artifact per key; 16-variant corruption matrix
  (invalid JSON, invalid UTF-8, non-object, missing/extra keys, version `2`, version `true`,
  swapped key, tampered digest, non-dict document, 5 receipt malformations, replay-vs-corrupt-winner)
  → every case a bounded `ValueError` naming the violation class only, file never rewritten.
- **Process races (real subprocesses, no sleeps, scheduling-independent assertions):**
  same-key 5-child race → all 5 identical receipts, exactly one artifact, zero stage leaks;
  mixed-content 3-vs-3 race → exactly one artifact, every exit-0 receipt equals the committed
  winner receipt, every loser exits with `ERROR:ValueError`, committed digest is one of the two
  contents. Death **before link** (child wraps `os.link` with `os._exit(77)`) → exactly one fsynced
  `.stage`, zero artifacts, `lookup` → `None`; a later publish of the same key succeeds and the
  stale stage stays untouched. Death **after commit** (outer `os._exit(78)`) → exactly one artifact,
  zero stages (own stage cleaned in `finally`), `lookup` and same-key replay return the committed
  receipt.
- **Runtime integration:** unchanged `Runtime` + `PublishingPolicy` dispatch to
  `confirmed_succeeded`, `FILE-` external id, one committed artifact whose key equals the Runtime
  business key; C04 satisfied via the accepted proof. No lifecycle code changed.
- **Coordinator redirect (applied):** the draft `ApiShapeTests` scanned production source text for
  `_exit`/`rename` tokens; the coordinator flagged it as a brittle implementation mirror. The
  keyword-scan test is dropped (public constructor-signature check retained); the no-crash-flag /
  no-rename-fallback property is audited directly instead: an AST walk of
  `work_runtime/file_adapter.py` enumerates every call in the module — the complete inventory
  contains no `_exit`, `rename`, `replace`, `remove`, `rmtree`, `system` or `popen`, `shutil` is
  not imported, and the only filesystem mutations are `makedirs` (constructor), exclusive-stage
  `open`+`fsync`, `link` (the commit) and own-stage `unlink`. Behavior itself is covered by the
  race/`FileExistsError`/zero-overwrite tests above. Final suite: **323 tests OK**
  (273 baseline + 50 new).
- **Platform notes (macOS 25.6.0/darwin, Python 3.9.6):** `os.link` commit and directory fsync
  both supported here; directory fsync is best-effort by design (POSIX-supported, skipped where
  refused). Hardlink-unsupported volumes propagate the explicit `OSError` (no rename fallback —
  verification basis: the `ApiShapeTests` constructor-signature check, the behavioral
  non-overwrite/race/corruption tests, and the direct AST call-inventory audit recorded below,
  independently re-confirmed by the wave-2 reviewer).

## Design rulings (routine, recorded for integration review)

1. Depth boundary: the document root dict counts as depth 1, so 63 nested lists validate and 64
   raise (`ValueError`). The D22 text pins "depth<=64"; the plan's "62 nested lists = total 64"
   was off by one against its own "root is depth 1" pin; the test pins 63/64. The gate is
   deliberately independent of the authoring module, which owns its own identical-bound bound.
2. Whitespace-only keys are accepted (D22 says "nonempty"; only an empty, non-string or
   non-UTF-8 **idempotency key** is rejected — JSON document property keys may be empty per
   D22 B4, fixed in 9c22099). Documented in docs/file-adapter.md.
3. No pre-commit existence fast path: replay always stages and commits through `os.link`, losing
   the link race to the existing file and reading the validated winner — one code path, no
   check-then-act window, matching the D22 flow literally.

## Remaining risks / boundaries (all documented in docs/file-adapter.md)

- No power-loss durability guarantee; best-effort directory fsync; trusted local directory only
  (no hostile-FS/symlink claims); hardlink support required; no distributed exactly-once.
- `.stage` files from dead processes are ignored, never cleaned by other processes (deleting
  another live racer's stage would be wrong) — bounded growth is left to the operator.
- The JSON gate here is independent of the future authoring module by design (D22); integration
  may want a one-line cross-reference between the two docs once both land.

## 2026-10-14 correction addendum (review findings F1/S1/S2)

Source: independent wave-2 review `.agents/notes/2026-10-14-S4-file-review.md` (s4-release-control,
@d119db3) — verdict *integration-ready, product compliant, no product defect*. This addendum records
the owner-side corrections; all evidence above is preserved unchanged. The Task-5 table row
"51/51 … 324 OK" remains as the chronological pre-redirect record; the standing final basis is
**323 tests (50 file tests)** per the redirect paragraph and this addendum.

**F1 — surrogate gate now pinned to plain `ValueError` (test-only fix).** The reviewer's mutation
M4 (remove the value-string UTF-8 gate) survived the original suite because `UnicodeEncodeError`
is a `ValueError` subclass and its message carries only the *escaped* surrogate render, so
`assertRaises(ValueError)` + raw-character `assertNotIn` both passed while the raw exception class
leaked. Both lone-surrogate tests now assert `type(raised.exception) is ValueError` and that
neither the raw surrogate nor its escaped render (`\ud800`/`\udfff`) appears in the message.
Evidence, observed in order:

- strengthened tests on pristine source → 2/2 OK;
- disposable working-tree mutation (deleted the single `_check_utf8(value)` call in the string
  branch; **never committed**) → `test_lone_surrogate_strings_are_rejected_without_leaking_them`
  FAIL, verbatim: `AssertionError: <class 'UnicodeEncodeError'> is not <class 'ValueError'>`;
  it was the **only** failure in the full 50-test file run under the mutation;
- `git restore work_runtime/file_adapter.py` → product byte-identical to 9c22099 (working tree
  showed only `tests/test_file_adapter.py` modified) → GREEN: 50/50 file tests, full suite
  **Ran 323 tests … OK**.

**S1 — stale platform statement corrected in place.** The Platform-notes sentence attributing the
no-rename-fallback property to an `ApiShapeTests` mechanism-token scan described the assertion
commit 1bb1342 removed. Corrected wording names the actual threefold basis: constructor-signature
check, behavioral tests, and the direct AST call-inventory audit (independently re-confirmed by the
reviewer's source audit).

**S2 — stale ruling corrected in place.** Design ruling 2's parenthetical listed *empty* keys among
the rejected; since 9c22099 (and per D22 B4) empty **JSON document property keys are valid** — the
nonempty rule belongs to the business **idempotency key** only. The ruling now says exactly that.

Product code was not touched by this correction (commit contains `tests/test_file_adapter.py` and
this report only); no exception property was weakened to accept subclasses and no comment was
edited to appease a test.
