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

Remaining closure gates: newest live fact reconciliation after canonical tie fix; native connector retry/page inspection or explicit permitted handoff; headline warehouse contract; final plot inspection; CI on Python 3.10/3.12; issue closure with actual evidence; main merge/push.
