# Portfolio Review

A candid assessment of this project as a portfolio piece for entry-level **Data Analyst** and **Business Analyst** roles, written after the October 2026 upgrade. Scores are relative to typical entry-level portfolios, not to professional production work. A strong portfolio project does not guarantee interviews or offers; it improves the odds that a reviewer reads further.

## 1. What changed in the upgrade

| Area | Before | After |
|---|---|---|
| Language | Bilingual Chinese/English README and report | English only, consistent terminology |
| KPI definitions | Spread across scripts and report text | One module (`src/kpis.py`) + [`kpi_definitions.md`](kpi_definitions.md) with numerator, denominator, window and unit |
| SQL | None | [`sql/kpi_queries.sql`](../sql/kpi_queries.sql) (window functions), cross-checked against pandas: 9/9 match |
| Robustness | Strong already (censoring, clustering, temporal holdout) | Added 30/60/90-day window test, imputed-data test, clustered test for the headline, power calculations for each proposed experiment |
| Traceability | Three hand-typed values in `04_roi.py` | Read from upstream tables; one reported figure corrected (users lost: 4,339 → 4,374) |
| Documentation accuracy | Log claimed comped orders were excluded from AOV (they were not) | Wording fixed to match the code |
| Dashboard | None | Streamlit dashboard, 6 tabs, filters, tested against analysis outputs, genuine screenshots |
| Presentation | None | 15-slide editable deck + PDF, generated from the output tables |
| Reproducibility | Five scripts run by hand | `src/run_all.py`, pinned dashboard dependencies, dashboard smoke tests, data dictionary |
| Experiment design | "Ship with a holdout" | Sample-size check showed a 10% holdout cannot detect Tier B's or Tier A's repeat uplift in reasonable time; tests redesigned (50/50 for Tier B, cost-mechanism metric for Tier A) |

## 2. Assessment

| Dimension | Rating | Evidence | Main gap |
|---|---|---|---|
| **Business relevance** | Strong | Clear business question, quantified stakes (repeat customers = 80% of GMV), recommendations tied to owners, metrics and tests | The business context (company, margins, costs) is invented, so stakeholders and constraints are assumed |
| **Analytical depth** | Strong | Metric-definition insight, cohort analysis, de-confounding, mediation ladder, two model families, break-even gates, sensitivity grid | Depth may exceed what an entry-level reviewer expects; the story must be told simply (the deck does this) |
| **Data quality & rigor** | Strong | Every dropped row counted; censoring; clustered SEs; forward-in-time validation; three self-corrected analytical traps documented; SQL cross-check | Patterns were planted by the author's own generator; rigor is demonstrated against a known answer, not an unknown one |
| **Technical implementation** | Good | Modular pipeline, deterministic, pinned versions, single KPI module, SQL, tests | No CI; tests cover the dashboard and SQL parity only; no notebook walkthrough for reviewers who prefer one |
| **Dashboard & visualization** | Good | Consistent palette, hover tooltips, captions that interpret each chart, definitions tab, honest data banner | Local only (not deployed); Streamlit look is generic; no BI tool (Tableau / Power BI) shown |
| **Business storytelling** | Good | Action titles, one message per slide, evidence-to-action chain, risks stated | Deck is long for a 10-minute interview slot; a 5-slide version would help |
| **Reproducibility** | Strong | One command rebuilds data and every output; README checksum (240,321); deck rebuilt from tables | PDF export needs Windows + PowerPoint; deck build needs Node.js |
| **Suitability for DA/BA roles** | Good to strong | Covers SQL, Python, KPI design, cohort analysis, A/B test design, dashboarding, stakeholder communication | Simulated data is the biggest credibility risk (see §4) |

## 3. What the project demonstrates to a hiring manager

- **Metric literacy**: understands that a KPI's counting unit and denominator can hide or reveal a problem. This is the project's central insight and a frequent interview topic.
- **Data cleaning discipline**: audit trail of every repair, sentinel handling with a stated bias direction, censoring.
- **Statistical judgement**: avoids naive p-values (clustering), avoids leakage (temporal split), recognises survivorship bias and mechanical confounding, and says plainly what is correlation rather than causation.
- **SQL**: window functions (`LEAD`, `ROW_NUMBER`), CTEs, cohort logic.
- **Business translation**: break-even thinking, honest downside (zero-uplift floor is negative), experiments sized against realistic volumes.
- **Communication**: report, executive deck and dashboard aimed at different audiences.

## 4. What it does not yet demonstrate

- **Work on real, unknown data.** The author generated the patterns, so the analysis "finds" what was put in. A sceptical reviewer will discount the findings themselves (though not the method).
- **SQL against a real warehouse** (joins across several tables, large data, a cloud dialect such as BigQuery or Snowflake). The current data is a single table.
- **A BI tool** (Tableau, Power BI, Looker). Many DA job postings list one explicitly.
- **Stakeholder requirements gathering** and iteration with a real business owner.
- **An executed experiment** with real results (only designed here).
- **Spreadsheet skills** (Excel modelling), which many BA roles screen for.

## 5. Recommended next improvements, ranked

| Rank | Improvement | Impact | Effort | Why |
|---|---|---|---|---|
| 1 | **Replicate the core pipeline on a real public dataset** (e.g. Olist Brazilian e-commerce, UCI Online Retail II): cleaning, the three repeat metrics, cohorts, drivers | Very high | Medium (3–5 days) | Removes the biggest credibility gap; `src/kpis.py` and `sql/` port directly |
| 2 | **Deploy the dashboard** (Streamlit Community Cloud) and link it from the README | High | Low (hours) | Recruiters click links; they rarely clone repos. Data can be built on first load (already supported). |
| 3 | **Add a Tableau Public or Power BI version** of the overview and cohort pages | High | Medium | Matches the tool keywords in many DA job postings |
| 4 | **5-slide interview version** of the deck + a 2-minute walkthrough script | Medium-high | Low | Fits typical case-presentation slots |
| 5 | **Multi-table SQL**: split the log into `orders`, `customers`, `tickets` tables and write the KPIs with joins | Medium | Low-medium | Shows realistic SQL beyond one table |
| 6 | **Walkthrough notebook** rendering the key charts inline on GitHub | Medium | Low | Some reviewers prefer notebooks to scripts |
| 7 | **CI (GitHub Actions)** running `run_all.py` and the tests on each push | Low-medium | Low | Signals engineering hygiene |
| 8 | Timestamp tickets/returns in the generator to remove outcome-window overlap | Low (for hiring) | Medium | Methodological completeness |

## 6. Readiness summary

**Ready to use in applications now**, with the simulated-data caveat stated up front, as it is throughout. The strongest talking points are the hidden-decline metric insight, the de-confounding corrections, and the honest business case (break-even gates, negative zero-uplift floor, power-checked test designs). Improvement #1 (real data) is the single change most likely to raise how seriously reviewers take it; #2 and #3 are the cheapest ways to make it easier to review.
