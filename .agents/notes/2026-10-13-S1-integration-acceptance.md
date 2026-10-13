# S1 integration acceptance — 2026-10-13

## Background

The independent integration session (this session) assembled both S1 developer
branches into the carrier `WayJ/sprint-s1-preview`, reviewed them inline, ran
the ordered gates and the acceptance scenarios, and wrote the acceptance
record at
[docs/superpowers/acceptances/2026-10-13-S1-acceptance.md](../../docs/superpowers/acceptances/2026-10-13-S1-acceptance.md).
Carrier line: `75a0f47` → runbook `339dc21` → runtime merge `eb8cb0e` →
contributor merge `da18d0e` → coherence pass `a407323`.

## Decisions

Merge order runtime-then-contributor (behavior before the docs that describe
it, so the strict-zero contracts branch of the repo test applied immediately).
Developer worktrees and terminals are retained: Orca records them under
user/external ownership, so this session does not close or delete them — the
coordinator owns any later teardown. The docs-only coherence edit (`a407323`)
was made by the integration session, not returned to the developer, because it
exists only because integration happened.

## Lessons

When reviewing parallel branches, diff against the merge-base, not the carrier
tip: diffing against `75a0f47` made both developers look like they deleted
shared-file lines that post-date their branch point. When a doc describes a
temporary cross-worker condition, the integration that resolves it owes a
matching prose update in the same sprint — otherwise the published doc
contradicts itself (fixed in `a407323`, see the acceptance record's obstacles
log for the verbatim entry this note cites back).

## Handover

Merge/push of `main` follows the
[integration runbook](2026-10-13-S1-integration-runbook.md) exactly:
acceptance record and `state: acceptance` precede the merge; never force-push;
verify `git ls-remote origin refs/heads/main` equals the published local HEAD
before reporting completion. Developer branches are merged but their worktrees
stay; carrier teardown is deferred if it would kill this session before
`worker_done`.
