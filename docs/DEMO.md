# Five-minute walkthrough recording script

Use the published Databricks dashboard, `notebooks/walkthrough.ipynb`, the repository and Power BI Navigator. Do not show `.env`, access-token pages, secret values or raw EIA request URLs. Record with your preferred screen recorder; a Loom upload/link requires your Loom account. No Loom recording has been published by this project.

| Time | Screen and narration |
| --- | --- |
| 0:00–0:35 | README architecture. “We turn actual EIA jet fuel and proxy prices into revision-aware medallion data, synthetic route analytics and calibrated reference-carrier hedge risk on Free Edition.” |
| 0:35–1:20 | Catalog Bronze/Silver and quality. Show 4,213 daily / 874 weekly samples and observation watermark. Explain immutable redacted events, revision handling, quarantines, gallon/barrel conversion and calendar-gap flags. |
| 1:20–2:05 | Route costs and positions. Clearly identify synthetic routes/flights/positions. Show matching-underlying MTM and historical scenario costs; distinguish 29.58M fixture gallons from 1.5B reference-carrier gallons. |
| 2:05–3:05 | Walkthrough calibration and MLflow. Explain lambda .94, weekly annualization, latest S0, Box–Muller, partition-invariant seeds and source/code lineage. Show full 100K job and FINISHED experiment. |
| 3:05–4:10 | Price fan, histogram, tail metrics and sensitivity. Explain absolute P95 versus incremental VaR and CVaR. Show 80% hedge reduction is an affine model identity; highlight downside opportunity costs and unstable historical drift. |
| 4:10–4:40 | Refresh job's sequential tasks and guarded reporting readiness. Show the verified successful run and daily schedule. Mention Free Edition quotas and visible failure states. |
| 4:40–5:00 | Power BI hostname/path and guarded Gold views. Show single-select hedge scenario and non-additive risk measures. End on plan/changelog/audits and reproducibility commands. |

Before recording: open the relevant pages, collapse unrelated tabs and verify `reporting_readiness.analytics_ready` and `risk_ready`. Refresh the report only after the whole daily job succeeds. After recording: watch the entire video, confirm labels/units are readable, check no credentials appear, and add your approved Loom link to the README.
