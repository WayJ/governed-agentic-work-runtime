# Technical debt tracker

| id | date | severity | owner | description | repayment criteria | status | evidence commit |
|---|---|---|---|---|---|---|---|
| TD-1 | 2026-10-14 | medium | lifecycle / integration-boundary epic E2 | Privileged trusted-local accepted-source record_evidence can collide with a future operation-id proof, causing _resolve INSERT/reconcile rollback. Signed ingress excludes accepted; source-grounded review6bd11d6 D-4. | Reject conflicting reserved operation-id intake before proof insertion with meaningful tests of legitimate imports and actual accepted-effect reconciliation; document trusted-local limits and cite repayment commit. | open | Discovery6bd11d6; decisionD37 before S8code; no repayment yet |
