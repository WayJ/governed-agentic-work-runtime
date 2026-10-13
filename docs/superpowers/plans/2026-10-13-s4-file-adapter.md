# S4 File Adapter (FilePublisher) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the real-filesystem third adapter `work_runtime/file_adapter.py` (`FilePublisher(directory)`) with atomic non-overwriting JSON artifact commits, its test suite, and `docs/file-adapter.md` — without touching Runtime/Policy lifecycle code.

**Architecture:** One new module `work_runtime/file_adapter.py` mirroring the `FakeOA`/`FakePublisher` adapter shape (declared `AdapterContract`, `execute`/`lookup`) but with a real side effect: one immutable JSON artifact per idempotency key on local disk, committed through an exclusive same-directory `.stage` file, `flush`+`fsync`, then `os.link` (non-overwrite). Validation (strict key, independent JSON-native gate, ONE detached snapshot, digest) runs entirely before any I/O. Tests adopt the existing `AdapterConformanceMixin` and add real subprocess race/process-death suites; no mocks of the filesystem.

**Tech Stack:** Python >= 3.9 standard library only (`json`, `hashlib`, `os`, `uuid`, `tempfile`, `subprocess`), `unittest`, real directories and real child processes.

**Spec:** `docs/superpowers/specs/2026-10-13-s4-adoption-design.md` ("Filesystem third adapter" + D22 addendum, the authoritative ratified choices), `docs/superpowers/sprints/2026-10-13-S4-plan.md` Wave 1, `AGENTS.md`.

## Global Constraints

- Python 3.9.6 on this machine: no 3.10+ syntax; `typing` spellings as in existing code.
- Zero runtime dependencies; standard-library `unittest` only.
- Ownership (exact): `work_runtime/file_adapter.py`, `tests/test_file_adapter.py`, `docs/file-adapter.md`, this plan, report in `.agents/notes/`. **Never** edit Runtime/policy/adapters/adapter_contract/ingress/CLI/demos, `work_runtime/__init__.py`, README/pyproject/CI, sprint/roadmap docs, or any baseline test file. Interface defects go to the coordinator via `orca orchestration ask`.
- Baseline: 273 carrier tests green before and after; suite green except during observed RED steps.
- No merge, no push, no nested agents, no local approval UI; Orca heartbeats while working, `check` at checkpoints (before new files, after test runs, before `worker_done`).
- No production `os._exit`, no crash/timeout constructor flags: API is exactly `FilePublisher(directory)`.
- No authoring dependency: the JSON gate is implemented inside `file_adapter.py` and must not import any authoring module (which is a parallel, disjoint ownership).
- Docs must state tested scope only: trusted local directory, no hostile-filesystem/symlink security claim, no power-loss guarantee, hardlink support required, no distributed exactly-once claim.

## Pinned contract (decisions the implementer cannot choose)

- `FilePublisher(directory)`: stores `str(directory)`, `mkdir(parents=True, exist_ok=True)` in `__init__` (matches FakeOA/FakePublisher parent creation). No other constructor parameters.
- Declared contract (exact):
  `AdapterContract(actions=("content.publish",), idempotency_scope="directory:key", retention="lifetime-of-directory", lookup_consistency="authoritative-by-key", uniqueness=())` — empty uniqueness tuple asserts no document-content uniqueness promise beyond key replay.
- Idempotency filename: `hashlib.sha256(key.encode("utf-8")).hexdigest() + ".json"` (safe 64-hex basename; caller key/document id never used as a path).
- Committed artifact JSON object, exact five keys: `artifact_version` (strict `type() is int` and `== 1`, bool rejected), `key` (original key string), `content_digest`, `document` (the detached canonical snapshot), `receipt`. File bytes = `policy.canonical(artifact)` encoded UTF-8 (deterministic; stable across replay).
- `receipt`, exact three keys: `{"status": "accepted", "external_id": "FILE-" + uuid.uuid4().hex, "digest": content_digest}` — the uuid (32 hex) is chosen when building the staged artifact; the **winning** staged commit's uuid is the durable one. `external_id` nonempty.
- `execute(key, document, content_digest)` order:
  1. Key gate: `type(key) is str`, nonempty, UTF-8 encodable (`key.encode("utf-8")` must not raise) → else bounded `ValueError` (no payload echo).
  2. `content_digest` gate: `type() is str`, nonempty.
  3. JSON-native gate + ONE detached snapshot: `type(document) is dict`; walk iteratively producing a plain deep copy; at every node require `type(x) is` one of `dict, list, str, int, float, bool, NoneType` (subclasses/tuples/sets/bytes rejected); dict keys `type() is str` and UTF-8 encodable; strings UTF-8 encodable (lone surrogates rejected); floats finite (`math.isfinite`); ints `abs <= 2**53 - 1`; container depth <= 64 (document root is depth 1); cycles detected by active-path container identity (`id()` in the current path stack) → bounded `ValueError`; repeated **acyclic aliases are valid** and each occurrence is copied anew (full detachment from caller objects).
  4. Digest: serialize the snapshot exactly once (`policy.canonical(snapshot)`) → `hashlib.sha256(...).hexdigest()`; mismatch with `content_digest` → bounded `ValueError` before any file I/O.
  5. Commit: exclusive stage file `<uuid32>.stage` in the same directory (`open(..., "xb")`, retry on `FileExistsError` with a fresh name, bounded retries), write artifact bytes, `flush()` + `os.fsync()`, close; `os.link(stage, final)`; on `FileExistsError` read/validate the winner — same `content_digest` → return the **winner's** receipt; different digest → `ValueError` (no overwrite); after a successful link, best-effort directory fsync (`os.open(directory, os.O_RDONLY)` + `os.fsync`, any `OSError` swallowed — supported on POSIX, skipped elsewhere), then read the final file back, validate it, and return **its** receipt. Own stage is removed in `finally` (tolerate `FileNotFoundError`); foreign/leftover `.stage` files are never touched.
  6. Non-`FileExistsError` `OSError` from `os.link` (hardlink-unsupported volume) propagates explicitly — no rename fallback.
- `lookup(key)`: same key gate; final path missing → `None`; present → parse and fully validate: valid UTF-8 JSON object; exact five keys; `artifact_version` strict int 1; `key` equals the requested key; `content_digest` nonempty str; `document` `type() is dict` re-passing the JSON-native gate (detached re-snapshot) with **recomputed** `sha256(canonical(document)) == content_digest`; `receipt` exact three keys, `status == "accepted"`, nonempty `external_id`, `receipt["digest"] == content_digest`. Any violation (parse error, wrong shape, wrong key, digest mismatch, version, receipt) → bounded `ValueError` naming the violation class only — never accepted as a result. Returns the validated receipt dict.
- Reuse `policy.canonical` from `work_runtime.policy` for serialization (byte-identical to Runtime's `digest(document)`; adapters.py precedent). Compute the digest hash with `hashlib.sha256` on the serialized bytes once per call purpose.
- Error messages are fixed short strings (constants), never containing key/document/digest payload content.
- Conformance: `tests/test_file_adapter.py` adopts `AdapterConformanceMixin`; `effect_count` counts actual committed hash-named files in the directory (`^[0-9a-f]{64}\.json$`), not adapter-internal counters.
- Subprocess suites use `sys.executable -c` children (inherit cwd, matching `test_runtime.py` precedent), `Popen` groups started together then waited — no sleeps, no timing assertions; all invariants are scheduling-independent.
- Process death tests: before-commit death by child monkeypatching `os.link` to `os._exit(77)`; after-commit death by child calling `os._exit(78)` right after `execute` returns. Parent inspects the real directory contents.
- Runtime smoke (read-only reuse): drive one `content.publish` operation through the unchanged `Runtime` + `PublishingPolicy` + `FilePublisher` to `confirmed_succeeded` with exactly one committed artifact (third adapter without lifecycle edits; no demo/README changes).

## Review Focus

1. Lone-surrogate strings in the **key** and in document strings/keys leaking a raw `UnicodeEncodeError`/payload → bounded `ValueError` before any I/O (Task 2 gate tests).
2. An acyclic alias (the same dict/list object referenced twice) wrongly rejected as a cycle → must publish validly (Task 2).
3. Caller mutating the document after `execute` changing the stored artifact → the committed bytes and lookups stay fixed to the snapshot (Task 3).
4. A leftover/foreign `.stage` file (including one from a dead process) blocking or polluting lookup/re-publish → ignored; exactly-one-artifact invariants hold (Tasks 3 and 4).
5. Race losers overwriting the winner or leaving a second artifact/stage leak → subprocess suites assert exactly one committed file, identical receipts for same content, `ValueError` for losing content, zero leftover own-stage files (Task 4).
6. A corrupt/tampered committed artifact being accepted on replay or lookup → bounded `ValueError`, file never rewritten (Tasks 2 and 3).

---

### Task 1: Baseline and plan

**Files:** Create: this plan.
- [x] Record baseline: `python3 -m unittest discover -s tests` → `Ran 273 tests ... OK`; `check_docs` 0 broken; `demo`/`publish-demo`/`intervention-demo` green; `compileall` clean (observed 2026-10-13, Python 3.9.6, darwin).
- [ ] Commit plan: `docs(plan): scoped S4 file adapter plan`.

### Task 2: `FilePublisher` core — gate, snapshot, atomic commit, lookup (RED → GREEN)

**Files:** Create `work_runtime/file_adapter.py`, `tests/test_file_adapter.py`.
**Interfaces:** Produces `FilePublisher(directory)` with `execute(key, document, content_digest) -> dict`, `lookup(key) -> dict|None`, attribute `contract`, per Pinned contract. Test helpers reused later: `committed_files(directory)` (sorted hash-named `.json` list), `stage_files(directory)`, `read_artifact(directory, key)`.

- [ ] **Step 1: Write failing tests** — classes:
  - `KeyGateTests` (through `execute`/`lookup`, each asserting the directory stays empty): non-str keys (`int` 7, `bytes`, `None`), empty `""`, lone-surrogate `"\ud800"` → `ValueError` whose message excludes the key text; valid unicode key `"中文\U0001f511"` accepted (covered by happy path).
  - `DocumentGateTests` (through `execute`, directory stays empty): non-dict root (`list`), `dict` subclass root; value `tuple`, `set`, `bytes`, `list`/`dict` subclass, non-string dict key (`{1: "a"}`), `float("nan")`/`inf`, `2**53` and `-2**53 - 1` ints (bool `True` stays valid), lone-surrogate string value and lone-surrogate dict key; list-cycle and dict-cycle → `ValueError` (assert not `RecursionError`); alias (same dict object under two keys) publishes fine; depth: 62 nested lists inside `{"a": ...}` (total container depth 64) valid, one more (65) → `ValueError`.
  - `DigestGateTests`: wrong `content_digest` → `ValueError`, no files; non-str digest (`None`, `""`) → `ValueError`.
  - `CommitTests` (happy path on `tempfile.TemporaryDirectory`): `execute` returns a `receipt_is_valid` receipt (`status="accepted"`, matching digest, `external_id` startswith `"FILE-"`, `len(external_id) == 5 + 32`, receipt keys exactly `{status, external_id, digest}`); exactly one file in the directory and its name equals `sha256(key).hexdigest() + ".json"`; file parses to exactly `{artifact_version: 1, key, content_digest, document, receipt}` with byte-exact document equality to the submitted document; no `.stage` leftovers; replay same instance → identical receipt dict, still one file, file bytes unchanged; **restart**: fresh `FilePublisher(same dir)` same key/content → same receipt, one file; different content same key → `ValueError`, file bytes unchanged, still one file; `lookup` committed key → equal receipt; `lookup` missing key (empty and unrelated-`json`-free dir) → `None`; unicode document round-trips through the artifact; traversal-shaped keys (`"../../etc/passwd"`, `"a/b"`) commit inside the directory only (directory listing is exactly the one hash-named file); metadata: `contract` equals the exact pinned `AdapterContract` (fields incl. `uniqueness == ()`).
- [ ] **Step 2: RED** — `python3 -m unittest discover -s tests -p test_file_adapter.py -v` → `ModuleNotFoundError: No module named 'work_runtime.file_adapter'`. Record verbatim (named classes).
- [ ] **Step 3: Implement `work_runtime/file_adapter.py`** per Pinned contract: module docstring stating trust boundaries; `_validate_key`, `_snapshot_document` (iterative, active-path cycle set, depth counter, plain-copy), `_validate_artifact(raw, key)`, `_sync_directory` best-effort, `FilePublisher` with `contract`, `__init__`, `execute` (stage → fsync → `os.link` → validate-winner/read-back → finally-stage-cleanup), `lookup`. Bounded message constants; no payload formatting.
- [ ] **Step 4: GREEN** — rerun Step 2 command → all new tests PASS. Then full suite `python3 -m unittest discover -s tests` → 273 + new, OK.
- [ ] **Step 5: Commit** — `git add work_runtime/file_adapter.py tests/test_file_adapter.py` + `feat(file): FilePublisher atomic JSON artifact adapter core`.

### Task 3: Conformance, corruption, detachment, staging hygiene (verification pass)

**Files:** Modify `tests/test_file_adapter.py`.
**Interfaces:** Consumes `AdapterConformanceMixin` (four hooks), `FilePublisher` from Task 2.

- [ ] **Step 1: Write tests** — classes:
  - `FilePublisherConformanceTests(AdapterConformanceMixin, unittest.TestCase)` with `make_adapter` (fresh `TemporaryDirectory` adapter, tracked for cleanup), `sample_document` (`PublishingPolicy`-valid article), `changed_document` (different digest), `effect_count` = `len(committed_files(directory))`.
  - `CorruptionTests` (each writes a committed artifact first, then damages the file; `lookup` → bounded `ValueError`, file content unchanged after the raise): invalid JSON bytes; invalid UTF-8 bytes; artifact not an object; missing key / extra key; `artifact_version` `2`; `artifact_version` `True`; `key` field swapped (artifact copied to another digest-name with different `key`); `content_digest` tampered so it no longer matches the recomputed document digest; `document` replaced by a non-dict; receipt with a missing/empty `external_id`, wrong `status`, extra receipt field, receipt digest mismatch. Also: replay path (`execute` same key/content) against a corrupted winner → `ValueError`, winner bytes unchanged.
  - `SnapshotDetachmentTests`: publish, then mutate the caller document (add key, mutate nested list) → committed file bytes unchanged, `lookup` still returns the original receipt; publishing the mutated document under a new key commits the mutated content only there.
  - `StagingHygieneTests`: a foreign `junk.stage` (and a stale stage from a dead process simulated by writing one directly) does not affect `lookup` (missing key → `None`) or a subsequent successful publish; successful publish leaves no own-stage files; `effect_count` ignores `.stage` files.
  - `BoundedMessageTests`: for a representative set of gate/corruption failures, the str(exception) does not contain the payload marker string planted in the document/key.
  - `ApiShapeTests`: `inspect.signature(FilePublisher.__init__)` parameters are exactly `self, directory` (no crash/timeout flags); the production source of `work_runtime/file_adapter.py` contains no `_exit` and no `rename` fallback.
- [ ] **Step 2: Run** — expected: pass if Task 2 is complete (verification pass; record actual result). Any RED is a real defect → fix minimally under systematic debugging, recording RED/GREEN.
- [ ] **Step 3: Full suite** — `python3 -m unittest discover -s tests` → OK.
- [ ] **Step 4: Commit** — `test(file): conformance, corruption, detachment and staging hygiene`.

### Task 4: Real subprocess races and process death

**Files:** Modify `tests/test_file_adapter.py`.
**Interfaces:** Consumes `FilePublisher`; children import `work_runtime.file_adapter` via `sys.executable -c` with inherited cwd.

- [ ] **Step 1: Write tests** — class `SubprocessRaceTests` (real `Popen` children, each printing `canonical(receipt)` on success or `ERROR:<ExceptionName>` and exit 1 on failure; parent waits all):
  - same-key/same-content race: 5 children, one key → all exit 0, all receipts identical to the committed artifact's receipt, exactly one hash-named `.json`, zero `.stage` leftovers.
  - mixed-content race: one key, content A ×3 and content B ×3 → exactly one committed artifact; every exit-0 child's receipt equals the committed receipt; every exit-1 child failed `ValueError`; at least one exit-0 child; committed `content_digest` ∈ {digest(A), digest(B)}; zero `.stage` leftovers.
  - death before link: child monkeypatches `os.link` to `os._exit(77)` before `execute` → exit 77; parent: zero `.json` for that key, exactly one `.stage` (the dead child's, fsynced), `lookup` → `None`; then parent publishes the same key/content → succeeds, one `.json` + the stale `.stage` untouched, `lookup` returns the receipt.
  - death after commit: child runs `execute` then `os._exit(78)` → parent: exactly one `.json`, zero `.stage`, `lookup` returns the committed receipt; parent re-executes same key/content → identical receipt, still one `.json`.
- [ ] **Step 2: Run** — record actual outcomes; any RED is a real concurrency/cleanup defect → minimal fix with recorded RED/GREEN evidence.
- [ ] **Step 3: Full suite** → OK. Repeat the subprocess module run 3× to check for flakiness (no timing dependence expected).
- [ ] **Step 4: Commit** — `test(file): real subprocess same-key/mixed races and process death`.

### Task 5: Runtime smoke, docs, gates, report

**Files:** Create `docs/file-adapter.md`, `.agents/notes/2026-10-13-S4-file-adapter-report.md`; modify `tests/test_file_adapter.py` (smoke test only).
**Interfaces:** Consumes unchanged `Runtime`, `PublishingPolicy`, `FilePublisher`.

- [ ] **Step 1: Write the failing Runtime smoke test** — `RuntimeDispatchTests`: real `Runtime` + `PublishingPolicy` + `FilePublisher(tempdir)`; create work with a valid article, bind contract, record reviewer approval + author confirmation, `verify_pending`, propose `content.publish`, `dispatch` → `confirmed_succeeded`, `external_id` startswith `"FILE-"`; exactly one committed artifact file in the adapter directory; work's verified evidence includes the accepted proof. RED first (`dispatch` uses FilePublisher — fails before Task 2 only if run out of order; in-order it may pass on first run — record actual).
- [ ] **Step 2: Write `docs/file-adapter.md`** — module purpose and trust boundary (third adapter, unchanged lifecycle); contract table (directory-scoped semantics incl. empty uniqueness); filename hashing; artifact/receipt shapes with the exact five/three keys; commit protocol steps (exclusive `.stage`, flush+fsync, `os.link` non-overwrite, winner read-back, own-stage cleanup, best-effort dir fsync and its platform behavior); idempotency semantics (same key+content → stable winning receipt across restarts; different content → `ValueError`, zero overwrite); lookup semantics (missing `None`; full recomputed-digest validation; bounded `ValueError` on corruption — Runtime retains `outcome_unknown`); validation gate (strict UTF-8 key; independent JSON-native/depth-64/cycle-alias/finite/2^53/UTF-8 limits; ONE detached snapshot); platform/scope boundaries (hardlink support required, no rename fallback, no power-loss/hostile-FS/symlink guarantee, no distributed exactly-once); test coverage map (conformance + restart/corruption/traversal/surrogate/tuple/int-key/cycle/alias/snapshot-mutation + subprocess races/death) with commands. Cross-link `adapter-contract.md` and the S4 spec.
- [ ] **Step 3: Gates** — `python3 scripts/check_docs.py` (0 broken); `python3 -m unittest discover -s tests -v` (273 + new, OK); `python3 -m work_runtime demo` / `publish-demo` / `intervention-demo` all succeed; `python3 -m compileall -q work_runtime tests scripts` clean.
- [ ] **Step 4: Report** — `.agents/notes/2026-10-13-S4-file-adapter-report.md`: named RED/GREEN evidence per task, file/test counts, corruption matrix outcome, race/death outcomes, SHAs, platform notes, remaining risks.
- [ ] **Step 5: Commit** — `docs(file): adapter contract doc, runtime smoke, sprint report` (single scoped commit or two: doc+test, report).
