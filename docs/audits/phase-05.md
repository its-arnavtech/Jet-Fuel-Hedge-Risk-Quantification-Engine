# Phase 5 whole-repository audit

Status: final live/native verification in progress. Branch phase-5-powerbi-insights; main merge is gated on evidence and both CI versions. Native rendering is not inferred from schema/TMDL passes.

## Scope and coverage

Read the complete Phase 5 request and all required baseline docs, every SQL definition, medallion/risk notebooks, simulation/Silver/operations modules and deployment/reporting verifiers before implementation. Reviewed all new source, generated report/model/queries, credentials/encoding boundaries, refresh lineage, market/return units, missing observations/weeks, calibration alignment, deterministic RNG, purchase averages, nonadditivity, fixture/reference labels, honest source dates, five-page design, dependency lock/CI and release handoff. Source PDD and the user's pre-existing untracked docs/CODEX_POWERBI_PROMPT.md are preserved.

| Finding | GitHub | Fix and evidence |
| --- | --- | --- |
| Price levels can be mistaken for proxy hedge tracking | [#12](https://github.com/its-arnavtech/Jet-Fuel-Hedge-Risk-Quantification-Engine/issues/12) | Separate named level/return facts, inclusive calendar RANGE/minimum pairs/gap suppression, annual/full-sample weekly R²; independent reconciliation and boundary tests |
| Drift extrapolation lacks historical validation and guarded publication | [#13](https://github.com/its-arnavtech/Jet-Fuel-Hedge-Risk-Quantification-Engine/issues/13) | Rolling realized purchases, 3 drift models, fat-tail frequency, append-only registry/quality/current-source row-count guards; live refresh/verifiers tracked below |
| Window zero loses middle seed entropy word | [#14](https://github.com/its-arnavtech/Jet-Fuel-Hedge-Risk-Quantification-Engine/issues/14) | Encode path IDs so SeedSequence is exactly [base,window,path], including zero; explicit zero/nonzero and repartition tests plus independent direct Box–Muller oracle |
| Visual QA exposes ANSI text corruption and clipped title | [#15](https://github.com/its-arnavtech/Jet-Fuel-Hedge-Risk-Quantification-Engine/issues/15) | Explicit UTF-8, mojibake scan, currency math parsing disabled, title wrapping, all 15 PNGs inspected/re-rendered; exact layered spec previews compiled |
| Native Import rejects navigator Kind keys | [#16](https://github.com/its-arnavtech/Jet-Fuel-Hedge-Risk-Quantification-Engine/issues/16) | GoldTable uniquely matches configured names; native retry pending. Original report opened and user authenticated through Desktop; no credentials copied into source |
| Float near-ties change crack rank across Arrow/SQL transport | [#17](https://github.com/its-arnavtech/Jet-Fuel-Hedge-Risk-Quantification-Engine/issues/17) | Canonical 12-decimal rank keys preserve raw prices and minimum-tie percentile semantics; near-tie test and new append-only live run 886166288914563 |
| Storyboards assume chronological SQL result order | [#18](https://github.com/its-arnavtech/Jet-Fuel-Hedge-Risk-Quantification-Engine/issues/18) | Sort all date/step/threshold keys explicitly; exact bridge assertion; rerendered and inspected all 15 live Gold plots |

## Numerical and publication checks

- 38 local tests, repository-wide Ruff, compilation and configured-credential/UTF-8/mojibake scan pass with workspace-local TEMP/TMP/UV_CACHE_DIR. No production simulation calibration/default changes.
- Independent offline oracle reconciles all seven facts, including all deterministic cells and 770×3 10K-path forecast summaries to 1e-9. SQL/Arrow near-ties were caught by live validation and are not waived by a broad tolerance.
- First standalone serverless insight run 809389860354170 SUCCESS, 285.986s. Correct inclusive-range managed refresh 906039088188452 SUCCESS for all seven sequential tasks. Source advanced from local 2026-10-06 to live 2026-10-20; numeric titles must move.
- Live reporting verifier passes analytics/risk/insights readiness; existing five source/publication/risk adversaries and new insight success/STARTED/stale-source/count-mismatch fixtures all pass without mutating production facts.
- Newest insight candidate source changes are append-only; STARTED blocks consumers until quality/count checks and SUCCESS. Managed schedule remains daily 18:00 America/Chicago, maximum one concurrent run. Manual publication is not run concurrently with the managed job.
- All JSON files use and validate their published Microsoft schemas; all model/visual field references are checked. Official Microsoft TOM serializer parses 22 tables/six one-way relationships. Four layered specifications (guarded bridge, calibration/IQR, fan, histogram) validate against Vega-Lite. Native zero-total waterfall behavior prompted a guarded bridge, and subtraction measures explicitly preserve BLANK when not ready.

## Visual and external evidence boundaries

Matplotlib storyboards and exact embedded-spec previews have conspicuous offline/verified-source badges and do not masquerade as Desktop screenshots. CVD QA includes normal/protan/deutan/tritan simulation with redundant labels/markers/dashes; signed heatmap values carry meaning independent of hue. Gold-extract final renders follow live reconciliation.

Power BI Desktop 2.159.883.0 opened the PBIP. The user authenticated in the credential dialog. Initial Import found a real navigator mismatch; a generated fix plus guarded bridge is available via Apply external changes. The native helper rejects clicks into a child WebView as a non-target process, so the user is applying changes/refreshing manually. No refreshed five-page screenshot or DAX evaluation pass is claimed yet. The exact failure and handoff are tracked; no authentication automation or filesystem-permission bypass was attempted.

Live canonical-tie verification passes: 4,223 decomposition rows, 4,223 correlations, 54 annual/ALL proxy rows, 4,120 historical hedge rows, 824 calibrations, 2,316 forecast rows (772 windows × three drift models), and three tail thresholds. Every deterministic and Monte Carlo cell reconciles to 1e-9. Current μ/σ match production simulation to 1e-9. Source Silver b88ebc88-6f08-4ee2-a72f-59a9a47ca873; insight run 22993b90-badc-4225-93d2-c95bee21dd48; observation date 2026-10-20. Evidence: docs/evidence/phase5_verification.json. All 50 warehouse headline equivalents reconcile; docs/evidence/powerbi_contract.json records this separately from DAX runtime.

All 15 final Gold storyboards and four exact embedded-spec previews were opened and inspected after correcting unordered exports. The bridge now ends at $4.632/gal, and the time-series plots use chronological dates. Readable titles, badges, table marks/status, signed heatmap, band layers and reference rules were checked. CVD preview inspected independently.

Milestone db0147d passed CI 39726018011 (and duplicate workflow 39726015400), including Python 3.10 and 3.12. Issues #12–#15, #17 and #18 are closed with committed live/test/visual evidence. Only #16 remains open pending native Import confirmation. Final verifier tightening also rejects empty/unready or duplicate headline result sets rather than allowing a vacuous pass. Remaining closure gates: native connector retry/DAX/page inspection or explicit permitted handoff; final changed-source CI; main merge/push.
