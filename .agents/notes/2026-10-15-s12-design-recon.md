# S12 SOP-publication design reconnaissance — 2026-10-15 (post-S11)

## Scope and evidence

Master-authorized S12 design/reconnaissance for the roadmap 0.4 gap: the SOP
rule-card publication process (authority approvals + immutable publication
store). **Design only — no implementation, no product/test/UI/docs-policy
changes, no dependencies, no merges/pushes, no extra workers.** The only repo
writes from this dispatch are the candidate DRAFT spec
[2026-10-15-sop-publication-design.md](../../docs/superpowers/specs/2026-10-15-sop-publication-design.md)
(pending master ratification + the independent design review the master
dispatches next) and this note. No roadmap, sprint, acceptance, ADR or
tech-debt ledger mutation was made; the master owns those.

Fresh worktree asserted at published main
`56a7f2eaa35693d77bd60bdadf799a0ff9097973`
(`git rev-parse HEAD` = the task's named baseline, branch
`WayJ/s12-publication-design`, `git status --porcelain` empty before this
note). Sources read as truth: [AGENTS.md](../../AGENTS.md) (working
agreement incl. supervibe gates + doc_sync_map), [roadmap.md](../../docs/roadmap.md)
0.4, [sop-authoring.md](../../docs/sop-authoring.md),
[file-adapter.md](../../docs/file-adapter.md),
[signed-evidence.md](../../docs/signed-evidence.md),
[interventions.md](../../docs/interventions.md),
[verification.md](../../docs/verification.md),
[tech-debt-tracker.md](../../docs/tech-debt-tracker.md),
[RFC-002](../../docs/RFC-002-sop-authoring-and-binding.md) (§1 D10, §5 D13,
§6, §8), [contributor-guide.md](../../docs/contributor-guide.md),
[runtime-boundaries.md](../../docs/runtime-boundaries.md) (registry section),
and the actual `authoring.py`, `publishing.py`, `publishing_demo.py`,
`file_adapter.py`, `runtime.py`, `adapters.py`, `adapter_contract.py`,
`policy.py`, `ingress.py`, `intervention_demo.py`, `adoption_demo.py`,
`cli.py`, `demo.py`, `check_docs.py` plus the existing test files
(`test_authoring.py` 146 tests, `test_publishing.py` 37, `test_adoption_demo.py`
43, `test_intervention_demo.py` 23, `test_file_adapter.py` 45,
`test_key_rotation.py` 50) and the S11 rotation design/recon pair for format
precedent. Historical `idea.md` / `上一次建议.md` were treated as source
material only. Probes (§3) ran from `/tmp` against the public API with
ephemeral synthetic stores; probe stores were deleted afterwards.

## 0. Fresh baseline (this checkout, 56a7f2e — recorded before any write)

| gate | result |
|---|---|
| tests | `Ran 874 tests … OK (skipped=3)` |
| contracts | `checked 98 markdown files, 443 local links, 0 broken` |
| syntax | `compileall -q work_runtime tests scripts` exit 0 |
| site | `checked 2 pages, 0 findings` |
| demo | `python3 -m work_runtime demo` exit 0 |

(The S11 recon recorded 809 tests / 399 links at `b594d757`; today's tree
grew with the S11 close-out docs and tests.)

## 1. Load-bearing facts (code-cited; every design claim below traces here)

**The gap, stated by the repo itself**

- F1. [roadmap.md](../../docs/roadmap.md) 0.4 (line 37): *"the publication
  process itself — authority approvals, an immutable publication store — is
  not implemented, and external author feedback remains uncollected"*.
- F2. [verification.md](../../docs/verification.md) line 445: *"The rule-card
  publication process itself (RFC-002 §6) is **not implemented**"*; line 452
  lists *"Policy/SOP publication, author review workflow"* under unimplemented
  coverage, and repeats that there is *"no link from a linted card to an
  executing Python policy"*.
- F3. [sop-authoring.md](../../docs/sop-authoring.md) lines 25–26: *"Authority
  approvals, immutable publication and a `lint-sop` CLI are later sprint
  work"*. **The CLI part is stale**: the `lint-sop` CLI shipped with the S4
  adoption wave (`cli.py:74–77`, `LintCliUsageTests` at
  `tests/test_adoption_demo.py:336`, exit-0/1/2 trio described at
  [verification.md](../../docs/verification.md) line 78). Only authority
  approvals and immutable publication remain open. Doc repair is owed to the
  implementing sprint (out of this dispatch's scope).

**Card identity and content digest (exists, pure, test-pinned)**

- F4. `lint_sop`/`sop_digest` are pure functions
  (`work_runtime/authoring.py:621–629, 634–650`); the digest reuses
  `policy.canonical`/`policy.digest` (sorted-key compact JSON, SHA-256) only
  after a clean preflight+schema gate and raises a bounded `ValueError`
  (counts and first pointer only) otherwise. 146 tests pin the exactly-14
  diagnostics, iterative preflight/SCC boundaries and key-order neutrality
  (`tests/test_authoring.py`).
- F5. Packaged cards exist as the single example truth source:
  `work_runtime/data/sop/expense.json` (8 rules, capabilities
  `expense.submit`, policy `expense-submit/demo-1`) and
  `publishing.json` (4 rules, `content.publish`, `content-publish/demo-1`);
  read via `importlib.resources` (`adoption_demo.py:127`), digest-pinned by
  `PackagedResourceTests` (`tests/test_adoption_demo.py:308`). Probe P1:
  today's expense-card digest is
  `4876285f00f5f9ad0287e92825f1aec212e9fc3bce10fd8c073bd2151d817627`,
  stable across key-order reshuffles.
- F6. A strict file loader exists with bounded exit-2 codes (1 MiB cap,
  UTF-8, duplicate keys, non-finite literals, deep JSON:
  `adoption_demo.py:60–124`); cards are loaded, linted and digested, never
  executed (`contributor-guide.md:9`, `sop-authoring.md:14–21`).

**Immutable hash-named artifact commit (FilePublisher, real-effect adapter)**

- F7. `FilePublisher(directory)` commits one canonical-JSON artifact per
  idempotency key at `<directory>/<sha256(key UTF-8)>.json` — the caller key
  is never a path (`file_adapter.py:224–228`); commit is exclusive `.stage`
  write + `flush`/`fsync` + `os.link` (atomic, non-overwriting, no rename
  fallback; `file_adapter.py:230–241, 266–275`); the committed bytes are read
  back and fully validated before the receipt is returned
  (`file_adapter.py:276–278`); a lost link race returns the winner's receipt
  for identical content and refuses (`ValueError`, zero overwrite) changed
  content (`file_adapter.py:270–274`); `lookup` validates or raises bounded
  `ValueError`, never rewrites (`file_adapter.py:286–294, 167–200`).
  Contract: `actions=("content.publish",)`, `idempotency_scope="directory:key"`,
  `retention="lifetime-of-directory"`, `lookup_consistency="authoritative-by-key"`,
  `uniqueness=()` (`file_adapter.py:213–218`). 45 tests incl. subprocess races
  and real process death (`tests/test_file_adapter.py`).
- F8. `uniqueness` difference that matters for this design: `FakePublisher`
  promises `("document.id+content_digest",)` (`publishing.py:117–122`) — same
  content under another key reuses the external id — while `FilePublisher`
  promises nothing beyond key replay (`file_adapter.py:218`). A publication
  store keyed by card identity gets same-(id,version) convergence from the
  *key* rule, not from content uniqueness.
- F9. Probe P2 (fresh `/tmp` directory): same key+content replay returns the
  byte-identical receipt; same key+changed content raises
  `idempotency key is already committed with different content`; a different
  key with the same content commits a second artifact (F8 confirmed).

**Command/evidence/grants model (the protocol a publication must ride)**

- F10. `Runtime.command(actor, command_id, work_id, kind, payload,
  expected_version)` — nonempty identity strings, CAS on `expected_version`
  for everything except `create_work`/`record_evidence`, durable dedup under
  `(actor, command_id)` with `COMMAND_ID_REUSED` on fingerprint mismatch, and
  replay of a stored receipt only while current authority holds
  (`runtime.py:250–292, 298–338`). `CommandError` is unpersisted API misuse;
  business refusals are persisted rejected receipts (`runtime.py:19–20`).
- F11. Grants decide authority by name: actor must exist in `grants`
  (`runtime.py:261–262`); `record_evidence` requires
  `policy.evidence_sources.get(kind) == actor` **and** `evidence.write`
  (`runtime.py:775–777`); `propose_action` requires the current owner holding
  the capability (`runtime.py:639–644`), re-checked at dispatch
  (`runtime.py:1020–1021`) and on replay (`runtime.py:326–328`); admin means
  `work.intervene` (`runtime.py:455–456`). Publishing-domain demo grants:
  `{"agent": {"work.manage", "content.publish"}, "reviewer"/"author":
  {"evidence.write"}}` (`publishing_demo.py:24–26`).
- F12. Evidence lifecycle: candidates land `pending_verification`; the
  trusted verifier `verify_pending` marks `verified` only when the kind's
  *currently configured* source matches and `validate_evidence` passes
  (`runtime.py:798–803, 885–908`); the reserved kind `"accepted"` is written
  only by the Runtime when resolving an accepted external effect, under the
  policy's `accepted` source with `event_id = operation id`
  (`runtime.py:925–975`), and signed ingress refuses that kind outright
  (`ingress.py:26, 318–319`).
- F13. Version-bound approval precedent: `ExpensePolicyV2` requires approval
  data exactly `{"digest", "policy_version"}` with
  `policy_version == self.version` (`policy.py:175–181`); migration
  revalidation turns old-shape verified approvals `invalid`, never the
  reverse (`runtime.py:602–613`).
- F14. Policy registry + pinning: `Runtime(path, policy, grants, *,
  policies=None)`; an explicit registry must be same-family (`id`, `goal`),
  key-equal-to-version, and the default version must map to the default
  policy *object* (`runtime.py:62–89` — probe P3 initially violated exactly
  this object-identity rule); every work resolves its pinned version and a
  missing pinned version fails closed with `CommandError` on any access
  (`runtime.py:163–185`; demonstrated end-to-end at
  `intervention_demo.py:177–186`, probe P3c). `migrate_policy` is the only
  explicit rebind, admin-only (`runtime.py:565–623`).
- F15. Signed approval path exists end-to-end: `sign_evidence` +
  `SignedEvidenceGateway` verify HMAC-SHA256 over canonical bytes with
  `hmac.compare_digest`, one shared clock sample, freshness, and forward only
  `{event_id, kind, data}` to `record_evidence` — signature, timestamp and
  `key_id` are never persisted (`ingress.py:149–168, 270–325`). S11 keyrings:
  per-source `SourceKey(key_id, secret, current, not_before, not_after)`
  tuples, exactly one current, deterministic selection (cited `key_id`, else
  the current entry), inclusive validity windows on the verification clock,
  immutable construction-time copy (`ingress.py:40–53, 105–142, 246–268`).
  Fingerprints are key-agnostic, so rotation never withdraws an accepted
  proof (`signed-evidence.md` rotation section).
- F16. Publish/recover shape a publication demo would mirror:
  proposal blocked by policy blockers → signed approvals verified →
  `dispatch` (adapter exception ⇒ `outcome_unknown`) → restart →
  `reconcile` by the original business key → `confirmed_succeeded` with one
  attempt → completion cites verified evidence
  (`publishing_demo.py:76–133`, `adoption_demo.py:286–400`). A malformed or
  conflicting adapter result quarantines as `outcome_unknown` +
  `ADAPTER_RESULT_INVALID` with the work in `needs_attention`, never an
  overwrite (`runtime.py:1105–1127, 1145–1150`).
- F17. RFC-002 §6 (lines 129–149) fixes the intended flow: draft → assisted
  card extraction → disambiguation/engineering binding → static checks +
  scenario regression → **an authorized principal approves the exact
  content** → publish an immutable version; *"approval binds the exact
  content identity; any later change requires a new version"*; drafts,
  skill suggestions or chat history cannot directly become mandatory runtime
  rules. §5 D13: publication determines rule meaning; binding instantiates;
  runtime evaluates — only the publication mechanism may change normative
  meaning. §8 leaves author usability, digest-field policy, approval
  revocation effect on past execution, and multi-SOP composition open.
- F18. Evidence revocation (S8) exists as the model for withdrawing a proof's
  current validity without rewriting history (`runtime.py:819–883`,
  [evidence-revocation.md](../../docs/evidence-revocation.md)); there is no
  publication-withdrawal analogue today.
- F19. AGENTS supervibe gates: `contracts` = `python3 scripts/check_docs.py`
  (local-link resolution; `.agents/` is not a link source but links into it
  are validated — `check_docs.py:1–30`), `tests`, `demo`, `syntax`, `site`;
  doc_sync_map owes are per-file; the working agreement itself is the
  master's to change (SKR-9 precedent).
- F20. Global decision numbering currently ends at D53 (S11 ratification);
  the rotation design used a local `SKR-*` prefix pending master
  allocation. This design uses `SPD-*` the same way.

## 2. What does NOT exist (verified, not assumed)

- No module, class or function mentioning rule-card *publication* exists in
  `work_runtime/` (grep over the package: only the content-publication
  domain — articles, not cards — and the static lint).
- No approval kind, grant or command references card approval; the packaged
  cards' `policy.source` is declared provenance only (`sop-authoring.md:94`).
- No loader turns any stored artifact into a `Policy` or registry entry;
  registries are constructor-supplied Python objects only (F14).
- No store, table or directory semantics beyond `FilePublisher`'s per-key
  artifacts; no tombstones, no withdrawal, no append-only log structure.

## 3. Probe log (public API, `/tmp`, disposable stores, since deleted)

| # | probe | result |
|---|---|---|
| P1 | `sop_digest(packaged_card("expense.json"))`, twice incl. one key-order reshuffle | identical digest `4876285f…7627`; determinism confirmed |
| P1b | `sop_digest({"schema_version": 1})` | `ValueError: SOP is not lint-clean: 6 diagnostic(s); first: MISSING_FIELD` — bounded message, no content echo |
| P2 | `FilePublisher.execute` same key+content twice | byte-identical receipt replay, one artifact |
| P2b | same key, changed title | `ValueError: idempotency key is already committed with different content`; winner untouched |
| P2c | different key, same content | second artifact committed (`uniqueness=()` honored) |
| P3 | `Runtime(..., policies={"demo-1": ExpensePolicy(), "demo-2": ExpensePolicyV2()})` with a *second* default instance | `CommandError: The default version must map to the default policy object` — the registry object-identity rule is live (`runtime.py:86–88`) |
| P3b | same registry built with one shared `v1` object; `migrate_policy` demo-1→demo-2 | accepted; contract pinned to `demo-2` |
| P3c | reopen that database without the registry; `get_work` | `CommandError: Load the policy version bound to this Work; migration is not implicit` — fail-closed pin confirmed |

## 4. Design constraints the baseline imposes

- The slice must be stdlib-only, Python ≥ 3.9, `unittest`, zero runtime
  dependencies (AGENTS).
- Every external effect rides the unchanged command protocol; new semantics
  belong in a policy + adapter + (at most) a thin composition module, not in
  `runtime.py` (the S4 file-adapter and S2 publishing precedents).
- Trust boundaries stay trusted-local: principals are configuration; signed
  ingress authenticates *sources*, not humans/tenants; no security claims
  beyond the documented shared-key boundary.
- Docs owed by a new `work_runtime/publication.py` would need a doc_sync_map
  row — a working-agreement change reserved to the master (F19).

## 5. Self-review (NOT independent — same session as the design)

Grounded facts above were read on this tree and probed through the public
API; the spec marks which claims are facts (F-numbers) versus
recommendations (SPD defaults). Known bias risks: reuse bias toward the
Runtime-work shape (the codebase's house style) may undersell a simpler
direct-API alternative — the spec carries it as a real alternative with an
explicit rejection rationale; the stale-doc finding F3 was double-checked
against `cli.py` and `verification.md` before being recorded. The master's
independent design review is the required counterweight; this note
self-ratifies nothing.
