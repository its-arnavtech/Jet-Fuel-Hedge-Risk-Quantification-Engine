# Phase 2 repository audit

Date: 2026-10-10. Scope: entire repository including Phase 1 regression checks, operations data, six SQL analyses, publication/lineage, deployment scripts, tests, docs and CI. Status: in progress.

## A1 — Linear mark query misclassifies null position inputs

Severity: medium. `sql/03_hedge_mtm.sql` uses `NOT IN` and comparisons without NULL guards. Missing instrument/underlying/notional can reach `LINEAR_SPOT_PROXY` and even an in-the-money status while P&L is null. Python valuation rejects invalid notional and unsupported instruments.

Expected: invalid/unsupported positions are explicitly flagged; no linear valuation status for null or nonfinite inputs. Fix both NULL semantics and validity guards, then validate adversarial SQL fixtures alongside correct real-data marks.

GitHub: https://github.com/its-arnavtech/Jet-Fuel-Hedge-Risk-Quantification-Engine/issues/6. Resolution: explicit NULL/nonfinite guards implemented; live adversarial SQL fixture and correct mark reconciliation running.

## A2 — Gold readiness does not record the consumed Silver publication

Severity: medium. Phase 2 checks Silver status at start, but analytics quality omits its run ID and there is no source-watermark recheck before success. A concurrent Silver refresh can produce a Gold build assembled across source publications; consumers cannot detect it.

Expected: record consumed Silver run ID, check unchanged SUCCESS before declaring Gold success, and require verifier/Power BI readiness checks to match current upstream publication. Multi-table Gold is guarded by its own registry but also needs source lineage.

GitHub: https://github.com/its-arnavtech/Jet-Fuel-Hedge-Risk-Quantification-Engine/issues/7. Resolution: consumed Silver watermark recorded, rechecked before SUCCESS and compared in verifier. Live fixed run SUCCESS; final reconciliation running.

## Coverage and pending checks

- 22 local tests, Ruff and compile checks pass, including all Phase 1 regressions.
- Eight routes and 8,395 synthetic scheduled flights are reproducible, unique and labeled; canceled flights excluded.
- Route validity uses half-open effective/expiry dates; historical costs use last-known as-of marks with seven-day staleness limit and explicit observation date.
- Monthly scenario grain and reference-carrier versus fixture-fleet consumption distinguished.
- Correct unit-aware long-futures sign and 100-based fleet share implemented.
- All six SQL definitions present; risk query uses exact P95/mean/CVaR and explicit run grouping; empty raw table has no fabricated Phase 3 results.
- Initial live job `1122134599329967` and fixed run `498442545839233`: SUCCESS. Full Gold/adversarial/dashboard query reconciliation/CI pending.
- Published initial dashboard `01f1c50e22881d6ea243de94f87b3f46` with price trend, route ranking and hedge status. Widget schema follows Databricks' official reference; datasets independently executed by verifier. Browser rendering not yet inspected.
- Dedicated schemas, credentials, immutable staging and bounded APIs preserve Phase 1 protections.

## Closure

Pending issues, fixes, adversarial SQL checks, Gold data reconciliation, publication watermark, CI and main merge.
