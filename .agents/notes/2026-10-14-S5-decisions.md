# S5 GUI pre-start decisions — 2026-10-14

## Background

User asked for GUI during autonomous development. E5/S5planned only, S4active and WIP1 preserved. Masterdraftbdfa1bc independently reviewed in controller01b93c3 with actualSQLite/WAL/bigint probes; report-only, no GUIcode.

## Decisions

D25 in [design](../../docs/superpowers/specs/2026-10-14-s5-gui-design.md) accepts decimalenvelopeversions/cursors and work-scoped events/fiveworkfixture. Correct reportnestedpayload "verbatim" claim: actualstatewholecolumn canbeverbatim, reconstructedsubobjects serialize inPython with exactintegers, no clientJSONparse. Add omittedpersistedcommandreceipts, actualrequirementid/contractgoal/op revisions; closurefield iscompletion, cancellationrequested_by, migrationevent only. Timeout alone doesn'tsetattention; seedrealreconcile unavailablelookup so attentionreflectsactualengine behavior. Plainlocalhostread-onlytool, no production/tenantauth orfakeclock/activitymetrics.

## Lessons

Inspect actualfields before DTOcontracts; summarylabels are not storedkeys. Python exactintegers survive serialization as JSONtext strings; clientnumericparse wouldroundlargebusinessvalues. Businessrequirementspending differsfromhistoricalactionblocker; UI mustshowactualdecisionreceipts, notinferauthorization.

## Handover

S4final integration publishes futuredesign/reviewplanning alongsideS4, thenmaster startsS5after S4mergedpush/CI. Backend andfrontend isolatedowners consume D25. Actualbrowserdesktop/narrow/XSS/offline checks and installedmodule/consoleHTTPproof requiredbeforeGUIrelease; mainpreview URL started only whenbuilt.
