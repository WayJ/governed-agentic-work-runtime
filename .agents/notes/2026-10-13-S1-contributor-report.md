# S1 Contributor Wave — Report

Task task_878e8fa82b1a · dispatch ctx_e6c377ef913b · 2026-10-13 · worktree WayJ/s1-contributor-preview
Plan: [2026-10-13-S1-contributor-plan.md](2026-10-13-S1-contributor-plan.md) (committed as 6512713; checkboxes left as written — this report is the execution record)

## Outcome

Delivered the contributor half of S1 Wave 1: the documentation contracts gate (`scripts/check_docs.py` + `tests/test_docs.py`), the fresh-venv install verification (`scripts/verify_install.py`), the honest P01–P15 coverage matrix (`docs/verification.md`) with RFC status annotations, and contributor-ready README/CONTRIBUTING/CI. No merge, no push. All five gates run fresh below; the contracts gate intentionally reports exactly one pending cross-worker link until integration lands `docs/runtime-boundaries.md`.

## Commits (this worktree, in order)

| commit | content |
|---|---|
| 6512713 | Scoped implementation plan (.agents/notes) |
| 08d4c6e | Markdown link checker + tests + CONTRIBUTING (same commit per doc_sync_map) |
| 769dc69 | docs/verification.md P01–P15 matrix + RFC-001/002/003 status annotations + reference-scenarios status + repo contract test |
| 801a0cf | scripts/verify_install.py fresh-venv out-of-repo verification |
| 3e98277 | README/README.zh-CN verify-a-checkout sections, CONTRIBUTING additions, CI gate mirroring |
| 5a22669 | Parser fixes from coordinator review (fenced reference definitions; fence delimiter length), TDD, CONTRIBUTING synced |
| 014ea03 | Coverage honesty corrections (P03 caveat, P06 partial, E07 partial enforcement, ≥35 wording) |
| (this commit) | Report |

## RED/GREEN evidence (observed)

**Task 1 — link checker (TDD).**
RED: `python3 -m unittest tests.test_docs -v` → all tests ERROR with `FileNotFoundError: .../scripts/check_docs.py` (module under test absent).
One authoring fix on the way: fixture file-count expectation 3→4 (test bug; implementation correct).
GREEN: `python3 -m unittest tests.test_docs -v` → 13/13 ok; full suite `python3 -m unittest discover -s tests -q` → 48 tests OK.

**Task 2 — coverage matrix + RFC links (TDD).**
RED: `python3 -m unittest tests.test_docs.RepoDocsContractTests -v` → FAILED, listing 5 broken links `README.md:7/67/99, README.zh-CN.md:7/38 → docs/verification.md`.
GREEN: full suite → 49 OK; `python3 scripts/check_docs.py` → `checked 19 markdown files, 60 local links, 1 broken` — only `docs/verification.md:67 -> runtime-boundaries.md` (the recorded cross-worker pending link), exit 1 as documented.

**Task 3 — verify_install.py.**
Pipeline probe first (fresh /tmp venv, pip 21.2.4, real install, out-of-repo module demo) — confirmed the design and exposed the checkout-import false-pass mode the origin check must kill.
First script run FAILED at the origin assertion — a real observed failure of an acceptance check (macOS `/var` vs `/private/var` aliasing made a correct venv origin look wrong). Fixed by comparing resolved paths (`Path.is_relative_to`). Rerun: **PASS, exit 0, 5.8 s** (final fresh run 7.8 s): fresh venv → real non-editable install → import origin inside venv (cwd outside repo, PYTHONPATH stripped) → installed set = {governed-work-runtime, pip, setuptools} → module demo + console demo outside checkout, both ending `external applications created: 1` → independent SQLite count of accepted receipts = 1.

**Coordinator review round — parser fixes (TDD).**
RED: `python3 -m unittest discover -s tests -p test_docs.py -v` → `test_reference_definitions_inside_fences_are_ignored` FAIL (fenced `[ref]: missing.md` leaked into the label map) and `test_longer_fence_not_closed_by_shorter_marker` FAIL (inner ``` closed a ```` fence, skipping a post-fence link).
GREEN: 16/16 docs tests; full suite OK.

## Final gates (fresh, this session)

| gate | command | result |
|---|---|---|
| tests | `python3 -m unittest discover -s tests -v` | **51 tests OK** (35 runtime + 16 docs) |
| contracts | `python3 scripts/check_docs.py` | 19 files / 61 local links / **1 broken** = the recorded pending `docs/verification.md:67 -> runtime-boundaries.md`; exit 1 (temporary cross-worker condition, resolves at integration) |
| demo | `python3 -m work_runtime demo` | exit 0; `external applications created: 1` |
| syntax | `python3 -m compileall -q work_runtime tests scripts` | exit 0 |
| install | `python3 scripts/verify_install.py` | PASS exit 0 (7.8 s, Python 3.9.6) |

New test names (tests/test_docs.py): test_valid_links_pass, test_broken_link_reported_with_location, test_external_urls_and_mailto_skipped, test_pure_anchor_and_empty_links_skipped, test_fragment_targets_check_file_only, test_fenced_code_blocks_skipped, test_inline_code_spans_skipped, test_reference_links_checked, test_reference_definitions_inside_fences_are_ignored, test_longer_fence_not_closed_by_shorter_marker, test_images_checked, test_leading_slash_resolves_from_root, test_excluded_sources_are_not_checked, test_cli_clean_tree_exits_zero, test_cli_broken_link_exits_one_and_prints, test_repo_docs_no_unexpected_broken_links.

## Coverage claims (docs/verification.md; corrected per coordinator follow-up msg_80b66581745d)

P01–P15: **local subsets of 14 protocol cases have named-test evidence, with partial coverage or caveats** — P03 partial (sequential CAS proof only), P04 partial (receipt loss simulated by re-invocation), P06 partial (clean restart only), P09 partial (obsolete-approval invalidation via `test_existing_invoice_proof_reused_after_document_change`, source conflicts, and closed-work callbacks tested as separate local subsets; the complete scenario is not exercised as a whole); **P13 deferred** (no distributed leases or distributed exactly-once claims). Concurrency wording corrected: SQLite serializes command submission across Runtime instances; dispatch assumes a single coordinator. E07 partial enforcement via capability allowlist — no independently evaluated protected-field check exists. Local principal names ≠ authentication; FakeOA is a local stand-in. No blanket RFC-001/002 implementation claims.

## Coordinator follow-ups → actions

1. Ownership/verification constraints → runtime-boundaries.md only linked, never substituted; both entry points run outside source; failures abort; no absolute worktree-path links in published Markdown (all relative).
2. Prioritize executable slice → checker + install script implemented before docs polish.
3. Inline execution, no nested review cycles → whole-branch review subagent stopped; self-review pass + this report instead; independent review delegated to the integration session.
4. Plan review corrections → E07/P03/P06 fixed in 014ea03; `-p test_docs.py` discover form used for docs-only runs; no external YAML dependency.
5. Checker bugs → both fixed TDD in 5a22669.
6. Repo test must accept zero findings after integration → test now self-expiring: strict zero once `docs/runtime-boundaries.md` exists; exactly-one pending link tolerated only while it is absent.

## Rulings (cost if wrong)

- Findings report RAW targets; percent-decoding only at resolution — one display tweak.
- CONTRIBUTING rows added only for files existing at each commit — one docs row moves.
- Dropped the planned `--no-build-isolation` retry (bundled setuptools 58 < required 61 makes it futile) — offline-capable mode missing until a backend is vendored.
- Subagent whole-branch review stopped per coordinator directive — one fewer fresh-context review before integration.
- Self-expiring repo test: its zero-findings branch cannot be exercised in this worktree without touching parallel-owned files — latent assertion branch untested until integration's strict CLI gate.

## Caveats and remaining risks

- `verify_install.py` install stage needs pip index access for the isolated build backend (setuptools); offline runs fail there loudly by design.
- CI workflow edited but not executed locally (no runner); first real evidence lands on GitHub after integration pushes.
- Contracts gate is intentionally red on exactly one link until integration merges the runtime worker's `docs/runtime-boundaries.md`; after that, the repo contract test demands zero findings.
- `verify_install.py` is not under unittest (ownership lists only tests/test_docs.py); its evidence is direct execution, recorded above.
- The checker is a documented CommonMark subset: no HTML `<a href>` links, no shortcut reference links, no angle-bracket edge cases beyond basic unwrapping.
- Repo layout note: `.superpowers/sdd/<plan>/` scratch (ledger + review diff) deleted after this report; git history + this report carry the record.
