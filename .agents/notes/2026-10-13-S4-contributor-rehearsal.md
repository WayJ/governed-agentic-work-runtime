# S4 contributor rehearsal — third-party-style persistent queue adapter (guide-only)

- Date: 2026-10-14 (report filename pinned by the dispatch)
- Worker: fresh Claude Code worktree `s4-contributor-rehearsal`, branch `WayJ/s4-contributor-rehearsal`
- Orca: task `task_84dadab2d8d5`, dispatch `ctx_2433830d8dd0`
- Role: independent third-party-style contributor working from public docs only

## Scope labels (required by dispatch)

- This is a **guide-only agent rehearsal, not real external human adoption feedback**; human adoption remains uncollected.
- The sample adapter is a **disposable teaching artifact**: single-process SQLite commit, no power-loss, hostile-filesystem, symlink or distributed exactly-once guarantee; it is not production code and promises no distributed semantics.

## Read-source list (complete)

Read in full, and nothing else:

1. `AGENTS.md` (project working agreement)
2. `docs/contributor-guide.md`
3. `docs/adapter-contract.md`
4. `docs/file-adapter.md`
5. `docs/sop-authoring.md`
6. `README.md`
7. `CONTRIBUTING.md`
8. `tests/adapter_conformance.py` (publicly documented conformance fixture)

Not read, per dispatch: any `work_runtime/*.py` source; `docs/superpowers/**` (specs/sprints/roadmaps); every other `docs/` file (`runtime-boundaries.md`, `signed-evidence.md`, `verification.md`, RFCs, `roadmap.md`, `interventions.md`, `reference-scenarios.md`); other `tests/*` files; `.agents/notes/*`; `README.zh-CN.md`; `idea.md`; `上一次建议.md`; `scripts/*` sources. Importing documented public modules at runtime is allowed and was used; no lifecycle source was opened. Directory listings (`ls`) were used for navigation only.

## Scoped plan (superpowers, inline; executed with executing-plans + TDD)

Goal: from the public guide alone, implement a tiny disposable persistent queue
adapter for the `content.publish` capability — the external effect is one
durable row in a `queue` table of a real SQLite database file, and the
committed receipt per idempotency key lives in a `receipts` table that
survives restarts — plus real SQLite/filesystem tests that adopt the reusable
conformance mixin. No lifecycle edits; stdlib only; Python 3.9-compatible.

Design decisions, each traceable to the guide:

- Protocol (guide Part A): `execute(key, document, content_digest)` returns
  `{"status": "accepted", "external_id": "QUEUE-<hex>", "digest": content_digest}`;
  `lookup(key)` returns the committed receipt or `None`.
- Idempotency (guide Part A / adapter-contract.md): `sha256(key)` is the row
  identity; same key + same digest returns the stored receipt with no new
  queue row; same key + different digest raises `ValueError`.
- Contract declaration (guide Part A):
  `AdapterContract(actions=("content.publish",), idempotency_scope="queue-database:key",
  retention="lifetime-of-database", lookup_consistency="authoritative-by-key", uniqueness=())`.
- `content_digest` is treated as opaque — the guide's teaching adapter does not
  recompute it and the digest function is not documented in the guide.
- Commit: one SQLite transaction (`BEGIN IMMEDIATE`) inserting the queue row
  (the effect) and the receipt row together — a single-process teaching commit,
  the same honesty tier as the guide's `os.replace` teaching shortcut.
- Test effect counting reads the `queue` table through an independent read-only
  connection — the external object itself, never an internal counter.

Tasks (TDD order):

1. T1 — write the tests first: `examples/rehearsal/test_queue_adapter.py`
   (conformance mixin adoption; restart receipt stability; changed-content
   rejection after restart; queue-row payload/digest contents; key/digest
   argument gates; real-file store check; documented Runtime capability
   preflight via the README local API). Observe and record RED.
2. T2 — minimal implementation: `examples/rehearsal/queue_adapter.py`.
   Observe and record GREEN.
3. T3 — gates (`python3 -m unittest discover -s tests -v`,
   `python3 scripts/check_docs.py`, `python3 -m work_runtime demo`,
   `python3 -m compileall -q work_runtime tests scripts` plus
   `python3 -m compileall -q examples/rehearsal`), self-review pass, finalize
   this report, commit exactly the three owned files.

Fallback: if README-documented demo helpers behave differently than
documented, investigate from observed behavior only, adapt or trim the
runtime test with an honest finding; never open lifecycle internals to fix it;
ask the master through Orca only if the guide truly blocks implementation.

## Rulings (executing-plans ledger)

- Ruling: plan + ledger live inline in this report file instead of a
  `.superpowers/sdd` workspace — dispatch ownership is restricted to exactly
  three files. Cost if wrong: none functional; a coarser ledger.
- Ruling: final review is a self-review pass (dispatch forbids nested agents).
  Cost: weaker than a fresh-context reviewer; disclosed here and in the
  worker_done summary.
- Ruling: no merge/push and no finishing-a-development-branch flow — the
  integration session alone accepts/merges/pushes (AGENTS.md). Work stops at
  commit + worker_done.
- Ruling: greenfield RED is the observed failure of the new test module while
  `queue_adapter` does not exist (feature absent), matching AGENTS.md's
  "write a meaningful failing test, observe failure, implement minimally".
- Ruling (T2): first GREEN attempt failed 5/14 — `AdapterConformanceMixin`'s
  raising `make_adapter` stub shadowed the shared fixture base in the MRO.
  Code wrong, not plan wrong: fixed by overriding `make_adapter` in the
  concrete class (the guide's own example pattern). Recorded as finding 4.

## Evidence (exact commands and observed results)

RED (T1, tests written first, adapter absent):

```
$ python3 -m unittest examples.rehearsal.test_queue_adapter -v
ModuleNotFoundError: No module named 'queue_adapter'
Ran 1 test in 0.000s — FAILED (errors=1)
```

The import shim and test module themselves load; the failure is exactly the
missing production module.

GREEN (T2, after minimal implementation): first run `FAILED (errors=5)`
(mixin stub shadowing, see ruling above); after the one-line override fix:

```
$ python3 -m unittest examples.rehearsal.test_queue_adapter -v
Ran 14 tests in 0.057s — OK            (exit 0)
```

14 tests = 5 reusable conformance (public mixin) + 2 restart stability +
3 queue-content + 3 argument gates + 1 Runtime capability gate. All five
conformance guarantees pass against real behavior: valid frozen contract,
same-key identical receipt with exactly one queue row, same-key different
content `ValueError` with no new row, authoritative `lookup`, `None` for a
missing key. Restart tests build a fresh adapter instance on the same database
file — receipts and effects are proven durable in the file, not memory.

Self-review pass (no nested agents, per dispatch): removed an unused schema
index and a vacuous assertion (TDD refactor-after-green), re-ran green. No
Critical/Important findings remained; limitations below are recorded rather
than fixed.

Final fresh gates (after the last edit, immediately before commit):

```
$ python3 -m unittest examples.rehearsal.test_queue_adapter   → exit 0, OK (14 tests)
$ python3 -m unittest discover -s tests                       → exit 0, Ran 512 tests, OK
$ python3 scripts/check_docs.py                               → exit 0, 46 files, 166 links, 0 broken
$ python3 -m work_runtime demo                                → exit 0 (crash-recovery demo)
$ python3 -m compileall -q work_runtime tests scripts         → exit 0
$ python3 -m compileall -q examples/rehearsal                 → exit 0
$ python3 examples/rehearsal/test_queue_adapter.py            → exit 0, OK (14 tests; direct run)
```

Reproduction for integration: from a fresh checkout of this branch, the first
command above is the rehearsal suite (dotted module form — see finding 3 for
why `unittest discover -s examples/rehearsal` does not work).

Commit (this branch, no merge/push by this worker): subject
`feat(adoption): S4 guide-only contributor rehearsal queue adapter` —
exact hash reported in the worker_done message.

## Findings: guide omissions / API friction

1. **Digest computation for domain tests is undocumented in the guide.**
   Part A never says how a third-party tester computes `content_digest` when
   calling `execute` in its own tests; the answer (`from work_runtime.policy
   import digest`) is only discoverable by reading the public fixture
   `tests/adapter_conformance.py`. One sentence in Part A would close it.
   Not blocking.
2. **A positive `content.publish` dispatch through the Runtime is not
   constructible from the allowlisted public docs.** The guide narrates how
   the Runtime treats an adapter, and README documents the expense-domain
   local API, but `PublishingPolicy` construction and the signed-evidence
   envelopes needed to accept a publish intent live in `signed-evidence.md` /
   internals outside the contributor allowlist. A third-party author can
   therefore not reproduce a FilePublisher-style positive
   `RuntimeDispatchTests` from the guide; only the capability-mismatch/held
   path is reachable via the README expense API (which the rehearsal test
   uses: held with zero effects, re-dispatch with a compatible adapter,
   evidence-backed completion accepted — all behaved exactly as documented).
   Suggest a minimal "drive one content.publish dispatch against your
   adapter" recipe in Part A.
3. **Out-of-`tests/` placement friction.** `unittest` discovery refuses a
   namespace start directory without `__init__.py`
   (`ImportError: Start directory is not importable` for
   `discover -s examples/rehearsal -t .`); the dotted-module invocation works
   and is what this report documents. The guide assumes `tests/` placement
   and does not cover contributions whose ownership keeps examples elsewhere.
4. **`AdapterConformanceMixin` stub-shadowing gotcha.** The mixin defines
   raising stubs for all four hooks, so a shared fixture base class providing
   `make_adapter` is shadowed unless the concrete class overrides it (mixin
   precedes the base in the MRO). The guide's inline example never hits this
   because it overrides all four hooks in the concrete class; a contributor
   factoring a disposable-fixture base (natural for SQLite domains) trips it.
   Cost this rehearsal one RED→fix cycle. A one-line note would prevent it.
5. **Otherwise: no findings.** `AdapterContract` construction/validation,
   receipt validation semantics, replay/mismatch/lookup authority, and the
   documented Runtime behaviors (`ADAPTER_ACTION_UNSUPPORTED` hold with zero
   external effects; held operation re-dispatches with a compatible adapter;
   completion accepted on evidence) all matched the docs exactly on first
   exercise — no contradictions between guide and observed behavior.

## Limitations

- Agent rehearsal, not real user adoption; no external human feedback collected.
- Teaching sample: single-process commit; no concurrent-writer, subprocess-race
  or crash testing; best-effort SQLite durability defaults; no power-loss,
  hostile-filesystem, symlink or distributed exactly-once guarantee.
- `json.dumps` coerces non-string dict keys (e.g. `{1: "a"}` → `{"1": "a"}`)
  rather than rejecting them, unlike the reference adapter's strict
  JSON-native gate; runtime-supplied documents come from the policy layer, so
  this path is not exercised in practice.
- Database-corruption handling is not implemented or tested (sqlite3 errors
  propagate); not required by the conformance contract, which the mixin
  deliberately scopes to key idempotency.
- The queue adapter is a demonstration of the public adapter surface only; it
  is not wired into any product lifecycle and makes no product claim.
