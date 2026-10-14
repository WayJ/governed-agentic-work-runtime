# S6 Website Implementation and Supervision Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans for scoped plans task-by-task. No nested workers; all sessions Orca Claude Code.

**Goal:** A public, truthful developer introduction/showcase website.
**Architecture:** Static bilingual HTML with local CSS/JS/assets; stdlib checker validates links/assets; dedicated Pages workflow publishes reviewed artifact. Independent control owns acceptance and release.
**Tech Stack:** Native HTML/CSS/JavaScript; Python>=3.9 unittest/stdlib; no runtime/build dependencies.
**Spec:** [Ratified D29](../specs/2026-10-14-s6-developer-website-design.md), [S6](../sprints/2026-10-14-S6-plan.md), root DESIGN.md/AGENTS.

## Global Constraints

No core/runtime/GUI changes; no CDN/fonts/dependencies/analytics/backend connection. Originalbrand, truthfulprealpha/sample labels. Development no merges/push; integration only. Scoped plans beforecode, meaningful behaviorRED/GREEN, visualbefore/after/screenshots/computedstyle evidence. No source-only/fakeDOM visualclaims.

## Review Focus

- Relative asset/link/anchor paths under projectsubpath and nested Chinese page: delivery fixturetests+actualbrowser.
- Firstload/noJS/empty or permissiondenied clipboard: page actualbrowserassertions; fulltext remains selectable.
- Keyboard/focus on responsive nav/recovery controls: page actualtrustedbrowserkeyevents desktop390/320.
- Contrast, CJK fallback and long code overflow: page computedstyles/screenshots plus integration verification.
- Fake/live semantics or unreleased capability claims: content review againstactualCLI and sample screenshots; no imaginaryusers/stars.

## Task 1 — website page owner

**Files:** website/index.html, zh/index.html, assets/styles.css/site.js/gui-*.png and optional architecture.svg; ownplan/report and focused browser regression artifact.
**Interfaces:** Relative localURLs, two languagepages, static six-stage demo visible noJS, local assets only; consume publicREADME/RFC/demo/output and realui-demo screenshots.
- [ ] Write scoped implementation plan exact behavioral assertions and visualtoken checks.
- [ ] Observe meaningful browserRED for copy/progress/focus behavior; implement minimally and GREEN with actualengine, keep noJScontent.
- [ ] Implement DESIGN tokens/contrastadaptation/responsive pages; freshsanitizedshots; actualdesktop390320/ENZH/clipboarddeny/noJS/subpath tests.
- [ ] Source/claim/license audit, syntax/docs checks, scopecommit and immutabletipreport with pendingdelivery checks disclosed.

## Task 2 — delivery owner

**Files:** scripts/check_site.py, tests/test_check_site.py, .github/workflows/pages.yml/ci.yml, docs/website.md, README.md/README.zh-CN.md, AGENTS sitegate/docsync rows; ownplan/report. No websiteasset edits.
**Interfaces:** Finding NamedTuple(file,line,kind,detail), scan(root:Path)->List[Finding], main(argv=None)->int, --root website exit0/1. Required index/zhindex/styles/sitejs, bounded localtargets/fragments/subpath/imagealt/langlinks; externalnavigationHTTPS/mailto only, assets local. ExactD29.
- [ ] Write scopedplan with realHTMLParserfixture unittestassertions.
- [ ] Observe failingchecker cases, minimalimplementation thenGREEN andscopedcommit; test nestedzh relative and out-of-root paths.
- [ ] CIsitegate, exactofficialPagesartifactworkflow, AGENTSgate/docsync owed docs samecommit; no actualPages enabling/deployment bydevowner.
- [ ] Testworkflow/packaging boundaries, checker onavailablefixtures, reportactualvs pendingassembledwebsitecheck (assetsnotyetpresent isnot success).

## Task 3 — independent integration

**Files:** carriermerges/acceptance/sprintledger/closeout/report; productcorrections originalowners.
**Interfaces:** Exactownertips intoCURRENTcarrier; reviewedwebsite artifact published onlyafteracceptance.
- [ ] Read source/evidence, assemble andverifyall sixscenarios/verbatimE6DoD actualbrowser and regressions; routefixes via master.
- [ ] Appendacceptance beforemainmerge; rungates/capturepremergetip, ordinarymainmerge/push/finalSHAactualCI.
- [ ] EnablePages authorizedexistingrepoaccount ifpermitted; actualdeploymentrun +publicHTTPSENZH/assets checks; closeQ2onlywithproof. No paidhost/domain fallback.
- [ ] Carrierteardown from separatecontrol (never deleteownsession), finalURL/SHAsCI/screenshotsreport one worker_done thenidle.

Self-review: allspecsections covered, ownershipdisjoint, exactinterfaces/pinnedvisualadaptations carried, fiveReviewFocus allocated. Ownerselaborate implementationtests beforecode.
