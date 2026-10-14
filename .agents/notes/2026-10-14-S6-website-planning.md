# S6 website planning — 2026-10-14

## Background

User explicitly requested developer introduction/showcase website after supplying DESIGN.md and asking for UI requirements in AGENTS. E6/S6/D26–D28 allocated after scanning all epics/stubs/sprints. S5 publication recovery remains in flight; website is planned only, no productcode or secondactive sprint.

## Decisions

Repository-owned static bilingual developer landing site. Originalprojectbrand, truthfulrecovery story/localGUIshowcase, exactquickstart/contributionlinks, DESIGNvisualgrammar. Planned GitHubPages target; publicrepo has_pages=false/homepage=null observed via ghAPI. No claim website deployed. IndependentClaude builder check before readiness/code.

## Lessons

S5 acceptance obstacles: actualbrowser catches firstrender and focus defects missed by sourcechecks. S5 release recovery: removing executioncarrier ends agent beforepublication; independentintegrationcontrol must stay outside teardowntarget. Raw/largeinteger/localtrust boundaries remain honest inpubliccopy.

## Handover

S5recoveryworker finishes S5release; do notfoldwebsitecode intoS5. Master nextratifiesdraftafterboundedbuilderreview, syncs savedDESIGN/AGENTS tofuturecarrier, thenready/startS6onlyafterS5actualremote+CI. No userwait required forroutinechoices.
