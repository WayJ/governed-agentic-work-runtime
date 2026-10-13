# S3 final release inputs — 2026-10-13

## Background

Master supervision checkpoint before final acceptance. Current assembled carrier5840d3d contains D15/D16, builder report and independently reviewed core8715151 (249 tests). Demo isolated base236ac14 remains valid; integration combines branches, never developers.

## Decisions

Final integration must independently review and merge BOTH latest corrected owner branches, not just the original demo tip:

- Core WayJ/s3-intervention-core **fd16b61** (parent8715151): demo-2 E05 explanation now accurately says every known amount needs version-bound approval, preserving v1 and admission logic; one meaningful diagnostic regression test, core suite250. Root independently ran all7 ExpensePolicyV2Tests OK; report addendum accompanies owner commit. Independently confirm the new test RED on8715151/GREEN onfd16b61 before merge.
- Demo WayJ/s3-intervention-demo: originald29aa04 has263 localtests, but installed console verification only checked stdout, and report overstated consolepublish coverage. Original owner correction task1e4c72777b95 adds shared distinct transfer/cancel/migrate-path validation and actualcount1 for BOTH module and console, with real negative SQLite fixtures and fresh installed verification. Only the corrected post-d29aa04 tip can be accepted; master records exact tip after worker_done. Original report remains history; correction addendum supersedes inaccurate coverage.

Both owner branches have disjoint file scopes (core policy/test_interventions/core report; demo CLI/harness/verifier/test_intervention_demo/publicdocs/demo report). Preserve carrier wait correction and master documentation in normal merges. Actual final test count comes from freshly assembled run, not sum guessed in advance.

## Lessons

Successful branch tests and PASS stdout are insufficient release proof. Root live harness showed stale v2 explanation; source audit showed missing console raw-store counts. All corrections remain original-owner work, with independent review by integration. This note makes exact merge obligations concrete even when mid-task Orca follow-up mail is not observed.

## Handover

Final integration reads current carrier design/epic/sprint and this note, executes all6 scenarios plus verbatimDoD, same-commit doc-sync audit, installed module+console intervention actualcounts, and three printed inspection commands. Record append-only acceptance before main merge; ordered merge, non-force push, remoteSHA equality, actualCI. Do not claim consolepublish installed verification: existing script covers moduleexpense/modulepublish/moduleintervention + consoleexpense/consoleintervention. Preserve user-owned development/controller worktrees; remove only clean merged sprintcarrier.

## Corrected demo input confirmed

Demo original-owner correction **99e5266** is clean, parentd29aa04; report records269 localtests and fresh installed PASS with both module/console actual3-store checks. Root independently ran6 VerifyInstallInterventionCountsTests OK. Final merge inputs are **corefd16b61** and **demo99e5266** into currentcarrier; expected273 after combining demo269 with3 wait-correction tests and1 diagnostics test, but fresh assembled run is authoritative. Both correction tasks settled successfully and their external-owned sessions are retained.
