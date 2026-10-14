---
epic: E6
status: open
date: 2026-10-14
---

# Developer introduction and showcase website

## Deliverables

| deliverable | note |
|---|---|
| Public developer landing website | Bilingual project introduction, quick start, architecture, recovery story, real GUI showcase and contribution links. |
| Design-system implementation | Apply user DESIGN.md and AGENTS UI agreement; original project identity, offline assets and responsive accessible presentation. |
| Reproducible static publishing | Repository-owned website files, preview/verification and GitHub Pages deployment with actual public URL checked. |

## Definition of Done

- [ ] English and Chinese entry pages explain the project, intended developers, architecture and current limits; quick-start commands reproduce actual demos and all documentation/repository/contribution links work.
- [ ] A clearly labeled demonstration of proposal, blocking, evidence verification, external acceptance, response loss and same-key query recovery uses verified project behavior; real GUI screenshots show actual demo records without fabricated customers, usage, metrics or guarantees.
- [ ] DESIGN.md tokens are implemented with documented adaptations, offline licensed/local font fallbacks and project-owned identity; actual desktop and 390px/320px browser checks verify visual layout, keyboard/focus, readable contrast, language/navigation and copy-command interactions.
- [ ] Static assets and interactions work under the repository subpath, with progressive content when JavaScript is disabled, no runtime/backend connection or external asset dependency, and no regression to core tests, demos, installed UI or local viewer.
- [ ] Independent acceptance precedes integration-owned main merge/non-force push; actual final-SHA CI and deployment succeed and the public HTTPS URL is checked against the released content, with honest evidence for any hosting permission blocker.

## Sprint Breakdown

| sprint | state | note |
|---|---|---|
| S6 | started | 2026-10-14 user explicitly requests a developer-facing showcase website. 2026-10-14 strategic ready: S5 published8db405a CI38515090420 verified; independent builder3673b44 and master ratification settle architecture/contrast/checker. Materialized 2026-10-14 after published UI agreement sync eff84d8; [S6](../sprints/2026-10-14-S6-plan.md), WIP1. [Design](../specs/2026-10-14-s6-developer-website-design.md). |

## Decisions (ADR)

| id | decision | rationale | date | evidence |
|---|---|---|---|---|
| D26 | Prioritize developer website after S5 | User explicitly asks for introduction/showcase site; open-source adoption needs a public understandable entry point. | 2026-10-14 | [Scope](../specs/2026-10-14-s6-developer-website-design.md) |
| D27 | Repository-owned static bilingual pages with GitHub Pages target | Works with Orca worktree ownership and no runtime dependencies; avoid unnecessary hosted app/server stack. Pages not yet enabled: actual public repo has_pages=false at planning time. | 2026-10-14 | [Hosting design](../specs/2026-10-14-s6-developer-website-design.md) |
| D28 | Apply DESIGN visual grammar while preserving real project semantics | Imported Cursor reference defines visual tokens, not brand identity, imagined agent stages or production guarantees. | 2026-10-14 | [Design adaptation](../specs/2026-10-14-s6-developer-website-design.md) |

| D29 | Ratify builder defaults and accessible design adaptations | Computed contrast, deterministic checker/subpath handling and real screenshot/browser/deployment proof pinned before code. | 2026-10-14 | [Ratification](../specs/2026-10-14-s6-developer-website-design.md#builder-ratification--2026-10-14-before-code) |

## Asset Disposition

| asset | disposition | note | date | evidence |
|---|---|---|---|---|
| Existing README/RFC/demos/contributor guide | reuse | Source verified copy and executable quick start; link authoritative docs rather than clone whole corpus. | 2026-10-14 | [README](../../../README.md) |
| Actual S5 GUI and acceptance screenshots | reuse | Capture sanitized demo screenshots for public showcase; label sample and local viewer. | 2026-10-14 | [S5 acceptance](../acceptances/2026-10-14-S5-acceptance.md) |
| DESIGN.md | reuse | User-selected visual reference; preserve document and derive CSS tokens. | 2026-10-14 | [Adaptation](../specs/2026-10-14-s6-developer-website-design.md) |

## Open Questions

| id | question | status | resolution |
|---|---|---|---|
| Q1 | Which public hostname for initial publication? | closed | D27: GitHub Pages project URL by default; custom domain deferred unless user supplies one. |
| Q2 | Does existing account permit Pages setup/deployment? | closed | Yes — proven 2026-10-14: integration enabled Pages via API (`POST /repos/WayJ/governed-agentic-work-runtime/pages`, `build_type=workflow`) with the authorized WayJ account (repo admin); deploy run [38527217416](https://github.com/WayJ/governed-agentic-work-runtime/actions/runs/38527217416) succeeded at `7b7e434`; live https://wayj.github.io/governed-agentic-work-runtime/ verified over HTTPS (EN/ZH pages and assets byte-equal to the release). [Close note](../../../.agents/notes/2026-10-14-S6-close.md). |

## Cross-cutting

| concern | owning epic | note |
|---|---|---|
| Authentic behavior/claims | E6 | No promise of 100K stars, distributed exactly-once, production authentication or real customer adoption. |
| Local operations viewer | E5 | Website links to reproducible local viewer; public site never connects to user SQLite/local APIs. |
