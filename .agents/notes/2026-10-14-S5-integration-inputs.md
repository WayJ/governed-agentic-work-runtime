# S5 integration inputs — 2026-10-14

## Accepted owner settlements, not sprint acceptance

- CURRENT carrier WayJ/sprint-s5-gui at8fded64 before this note; preserve all master documents.
- Backend corrected immutable tip fad5e01 (base8d4cfac); initialtip7c0d4ae was not acceptable for Origin behavior. Master reproduced cross-alias HTTP200 at oldtip, then ran corrected26 HTTP tests PASS and real four-pair HTTP probe: samealias200, crossalias403. Initial62 reader+HTTP tests also independently passed. Finalbackend code622fc5e/docs e0eb120/reportfad5e01; actual public DTO docs/gui-api.md at finaltip supersedes3d5732e. Full reportedbackend575 = baseline512+63; independently reproduce during integration.
- Frontend immutable tip138d6b4 (base8d4cfac), producttip729a66b. Master independently ran27 seed/CLI tests PASS. Scope includes only frontend/CLI/packaging/docs/ownplan/report. Existing tests and engine unchanged. Worker reports539 total512+27. Both developer checkouts clean when validated.
- Assembly expected core602 =512+63+27 unless meaningful new corrections add tests; rehearsal14 remains separate. Never add skipped or browser checks to unit-test counts.

## Pending mandatory proof

The frontend installed verifier discloses missing-backend UI stage as SKIPPED. This was permitted only before assembly: the assembled S5 release must run the actual installed module AND console UI HTTP assets/API/store-snapshot/shutdown path, not accept a SKIPPED PASS. Verify metadata, DTO names and all numeric/raw fields against finalbackend docs.

Actual browser desktop/narrow/offline/bilingual/filter/keyboard/manualrefresh/pollpause/empty/error/disconnected/XSS/hugeinteger/stale-response behavior remains pending. Browser smoke against a stand-in or source invariant scan is not acceptance. Independent integration owns actual browser evidence and screenshots. Product findings return through master to original owner.

Master HTTP suite passed but once emitted an incidental ConnectionResetError traceback when a test peer reset a keepalive connection; assess actual bounded-server/log behavior in independent review, do not claim logs cannot produce stacks solely from passing unit tests. No data/path content leaked in that observed stack.

## Release ownership

Task task_14f51c6944fa is ready; integration alone performs assembly, acceptance before main merge, merges and ordinary push. No main release until all six scenarios plus verbatim E5 DoD pass. Final remoteSHA equality and actualCI success at FINAL published SHA required (including any closing/evidence commit). Report finalCI in worker_done to avoid endless evidence-commit loops. Preserve dev worktrees and user sessions. Master opens main ui-demo after actual release, and continues roadmap under existing user authorization.
