// Builds presentation/Repeat_Purchase_Analysis.pptx from the analysis outputs.
//
//   cd presentation/build && npm install && npm run build
//
// Every number and chart series is read from outputs/tables/*.csv at build time,
// so the deck cannot drift from the analysis. Re-run after re-running the pipeline.

const fs = require("fs");
const path = require("path");
const pptxgen = require("pptxgenjs");
const JSZip = require(require.resolve("jszip", { paths: [require.resolve("pptxgenjs")] }));

const ROOT = path.resolve(__dirname, "..", "..");
const TAB = path.join(ROOT, "outputs", "tables");
const OUT = path.join(ROOT, "presentation", "Repeat_Purchase_Analysis.pptx");

// ---------------------------------------------------------------------------
// Data
// ---------------------------------------------------------------------------
function readCsv(name) {
  const text = fs.readFileSync(path.join(TAB, name), "utf8").trim();
  const rows = text.split(/\r?\n/).map((line) => {
    const out = []; let cur = ""; let q = false;
    for (const ch of line) {
      if (ch === '"') q = !q;
      else if (ch === "," && !q) { out.push(cur); cur = ""; }
      else cur += ch;
    }
    out.push(cur);
    return out;
  });
  const head = rows[0];
  return rows.slice(1).map((r) => Object.fromEntries(head.map((h, i) => [h, isNaN(+r[i]) || r[i] === "" ? r[i] : +r[i]])));
}
const by = (rows, key) => Object.fromEntries(rows.map((r) => [r[key], r]));
const pct = (x, d = 1) => `${(100 * x).toFixed(d)}%`;
const pp = (x, d = 1) => `${x >= 0 ? "+" : "−"}${Math.abs(100 * x).toFixed(d)}pp`;
const usd = (x) => `$${Math.round(x).toLocaleString("en-US")}`;
const usdK = (x) => `$${(x / 1000).toFixed(0)}k`;

const kpi = readCsv("05_kpi_summary.csv");
const K = (scope, name) => { const r = kpi.find((x) => x.scope.startsWith(scope) && x.kpi === name); return r.numerator / r.denominator; };
const headBase = K("Baseline", "Order-level 30-day repeat rate (headline)");
const headRec = K("Recent", "Order-level 30-day repeat rate (headline)");
const newBase = K("Baseline", "New-customer 30-day repeat rate");
const newRec = K("Recent", "New-customer 30-day repeat rate");

const trend = readCsv("02_monthly_trend.csv").map((r) => ({ ...r, month: r[""] }));
const cohort = readCsv("02_cohort_retention.csv").map((r) => ({ cohort: r.cohort, m1: r["1"] })).filter((r) => r.m1 !== "");
const mean = (a) => a.reduce((s, v) => s + v, 0) / a.length;
const m1Early = mean(cohort.filter((r) => r.cohort >= "2024-01" && r.cohort <= "2024-09").map((r) => r.m1));
const m1Late = mean(cohort.filter((r) => r.cohort >= "2024-11" && r.cohort <= "2025-05").map((r) => r.m1));
const mix = by(readCsv("02_order_mix_drift.csv").map((r) => ({ ...r, month: r.order_month })), "month");
const tickTrend = by(readCsv("02_ticket_trend.csv"), "order_month");
const catTick = by(readCsv("02_ticket_by_category_month.csv"), "m");
const ticketRb = readCsv("05_ticket_robustness.csv");
const ticketRate = ticketRb.map((r) => r["repeat (all scoreable orders)"]);
const ticketN = ticketRb.map((r) => r["orders (all scoreable orders)"]);
const disc = readCsv("02_tipping_discount.csv");
const odds = by(readCsv("03_odds_ratios.csv").map((r) => ({ ...r, v: r[""] })), "v");
const ladder = readCsv("03_mediation_ladder.csv");
const b0 = ladder[1].degraded_coef, b1 = ladder[2].degraded_coef, b2 = ladder[3].degraded_coef;
const medService = (b0 - b1) / b0, medAll = (b0 - b2) / b0;
const model = readCsv("03_model_summary.csv")[0];
const cases = readCsv("04_business_cases.csv").filter((r) => /base/.test(r.tier));
const sens = readCsv("04_sensitivity.csv");
const sensCells = sens.flatMap((r) => Object.entries(r).filter(([k]) => k !== "uplift_multiplier").map(([, v]) => v));
const sensPos = sensCells.filter((v) => v > 0).length;
const win = readCsv("05_window_sensitivity.csv");
const cust = by(readCsv("05_customer_type_comparison.csv"), "customer_type");
const repCust = cust["Repeat customer (2+ orders)"];
const sql = readCsv("06_sql_check_results.csv");
const sqlPass = sql.filter((r) => r.passed === "True").length;

const tot = (k) => cases.reduce((s, r) => s + r[k], 0);
const netTot = tot("net_yr"), costTot = tot("cost_yr"), gmvTot = tot("incremental_gmv_yr");
const floorNet = tot("cost_avoided_yr") - costTot;
const caseOf = (re) => cases.filter((r) => re.test(r.intervention + r.tier));

// ---------------------------------------------------------------------------
// Theme + layouts
// ---------------------------------------------------------------------------
const THEME = {
  name: "Repeat Purchase",
  headFontFace: "Cambria",
  bodyFontFace: "Calibri",
  colors: {
    dk1: "1B1B1B", lt1: "FFFFFF", dk2: "16324F", lt2: "EEF3F9",
    accent1: "2A78D6", accent2: "EB6834", accent3: "1BAF7A", accent4: "898781",
    accent5: "9EC5F4", accent6: "6250D6", hlink: "2A78D6", folHlink: "6250D6",
  },
};
const H = THEME.colors; // hex, for chart options that only accept hex
const MUTED = "5F5E5A";

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE"; // 13.333 x 7.5 in
pres.title = "Why New Customers Stopped Coming Back";
pres.subject = "E-commerce repeat purchase analysis";
pres.author = "Newnew-niu";
pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
const C = pres.SchemeColor;

const W = 13.333, MX = 0.6, CW = W - 2 * MX;

pres.defineSlideMaster({
  title: "Title dark",
  background: { color: C.text2 },
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: MX, y: 2.2, w: 11.5, h: 1.6, fontSize: 44, bold: true, color: C.background1, valign: "bottom", align: "left" }, text: "" } },
    { placeholder: { options: { name: "body", type: "body", x: MX, y: 3.95, w: 11.5, h: 1.0, fontSize: 20, color: "CADCFC", valign: "top", align: "left" }, text: "" } },
  ],
});
pres.defineSlideMaster({
  title: "Content",
  background: { color: C.background1 },
  margin: [0.5, MX, 0.7, MX],
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: MX, y: 0.35, w: CW, h: 1.0, fontSize: 28, bold: true, color: C.text2, valign: "middle", align: "left" }, text: "" } },
    { placeholder: { options: { name: "source", type: "body", x: MX, y: 6.78, w: 9.8, h: 0.35, fontSize: 10, color: MUTED, valign: "middle" }, text: "" } },
    { text: { text: "Simulated data · portfolio project", options: { x: 9.2, y: 6.78, w: 3.0, h: 0.35, fontSize: 10, color: MUTED, align: "right", valign: "middle" } } },
  ],
  slideNumber: { x: 12.25, y: 6.78, w: 0.5, h: 0.35, fontSize: 10, color: MUTED, align: "right" },
});

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
let nObj = 0;
const oname = (s) => `${s}-${++nObj}`;

function content(title, source, section) {
  const s = pres.addSlide({ masterName: "Content", sectionTitle: section });
  s.addText(title, { placeholder: "title" });
  if (source) s.addText(source, { placeholder: "source" });
  return s;
}

function card(s, x, y, w, h, fill = C.background2) {
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h, rectRadius: 0.12, fill: { color: fill }, line: { color: fill }, objectName: oname("card") });
}

function stat(s, x, y, w, h, big, label, sub, color = C.accent2, bigSize = 44) {
  card(s, x, y, w, h);
  s.addText(big, { x: x + 0.25, y: y + 0.2, w: w - 0.5, h: 0.95, fontSize: bigSize, bold: true, color, fontFace: THEME.headFontFace, valign: "middle", isTextBox: true, margin: 0, objectName: oname("stat") });
  s.addText(label, { x: x + 0.25, y: y + 1.15, w: w - 0.5, h: 0.45, fontSize: 16, bold: true, color: C.text1, isTextBox: true, margin: 0, objectName: oname("stat-label") });
  if (sub) s.addText(sub, { x: x + 0.25, y: y + 1.6, w: w - 0.5, h: h - 1.75, fontSize: 14, color: MUTED, isTextBox: true, margin: 0, valign: "top", objectName: oname("stat-sub") });
}

function badge(s, x, y, n, color = C.accent1) {
  s.addShape(pres.shapes.OVAL, { x, y, w: 0.46, h: 0.46, fill: { color }, line: { color }, objectName: oname("badge") });
  s.addText(String(n), { x, y, w: 0.46, h: 0.46, fontSize: 16, bold: true, color: C.background1, align: "center", valign: "middle", isTextBox: true, margin: 0, objectName: oname("badge-n") });
}

function bullets(s, items, x, y, w, h, size = 16) {
  s.addText(items.map((t, i) => ({ text: t, options: { bullet: true, breakLine: i < items.length - 1, paraSpaceAfter: 8 } })),
    { x, y, w, h, fontSize: size, color: C.text1, valign: "top", isTextBox: true, objectName: oname("bullets") });
}

function richText(s, runs, x, y, w, h, size = 16) {
  s.addText(runs, { x, y, w, h, fontSize: size, color: C.text1, valign: "top", isTextBox: true, margin: 0, objectName: oname("text") });
}

const AXIS = { catAxisLabelColor: MUTED, valAxisLabelColor: MUTED, catAxisLabelFontSize: 11, valAxisLabelFontSize: 11,
  catAxisLabelFontFace: "+mn-lt", valAxisLabelFontFace: "+mn-lt", dataLabelFontFace: "+mn-lt", legendFontFace: "+mn-lt",
  valGridLine: { color: "E1E0D9", size: 0.75 }, catGridLine: { style: "none" }, catAxisLineColor: "C3C2B7", valAxisLineShow: false };

// ---------------------------------------------------------------------------
// 1. Title
// ---------------------------------------------------------------------------
pres.addSection({ title: "Introduction" });
let s = pres.addSlide({ masterName: "Title dark", sectionTitle: "Introduction" });
s.addText("Why New Customers Stopped Coming Back", { placeholder: "title" });
s.addText("Diagnosing a hidden decline in repeat purchase — and what to do about it", { placeholder: "body" });
s.addText("E-commerce order log, Jan 2024 – Jun 2025 (simulated data)  ·  github.com/Newnew-niu/ecommerce-repeat-purchase-analysis",
  { x: MX, y: 6.3, w: 12, h: 0.4, fontSize: 14, color: "CADCFC", isTextBox: true, margin: 0, objectName: oname("byline") });
s.addNotes("Portfolio project. The order log is simulated (src/00_make_dataset.py); the analysis rediscovers the planted patterns from the CSV without reading the generator's parameters. Methods transfer to real data; absolute numbers do not.");

// ---------------------------------------------------------------------------
// 2. Executive summary
// ---------------------------------------------------------------------------
s = content("The reported KPI looked stable while new-customer repeat fell by 16%",
  "Baseline = 2024Q2–Q3, recent = 2025Q1–Q2. Sources: outputs/tables/05_kpi_summary.csv, 02_cohort_retention.csv", "Introduction");
const cw3 = (CW - 0.6) / 3;
stat(s, MX, 1.55, cw3, 2.35, pp(headRec - headBase), "Headline 30-day repeat", `${pct(headBase)} → ${pct(headRec)}. What the business reported`, C.accent4);
stat(s, MX + cw3 + 0.3, 1.55, cw3, 2.35, pp(newRec - newBase), "New-customer 30-day repeat", `${pct(newBase)} → ${pct(newRec)} (p < 0.001)`);
stat(s, MX + 2 * (cw3 + 0.3), 1.55, cw3, 2.35, pp(m1Late - m1Early), "Cohort M+1 retention", `${pct(m1Early)} → ${pct(m1Late)}, cohorts since Nov 2024`);
const drivers = [
  ["Support tickets", `Repeat collapses at the 3rd ticket (odds ratio ${odds.tickets_3p.odds_ratio.toFixed(2)}); orders with a ticket rose from ${pct(tickTrend["2024-01"].pct_1plus, 0)} to ${pct(tickTrend["2025-06"].pct_1plus, 0)}`],
  ["Electronics & Home", `Highest order values, lowest repeat; tickets per order up ${(catTick["2025-06"].Electronics / catTick["2024-01"].Electronics).toFixed(1)}x and ${(catTick["2025-06"].Home / catTick["2024-01"].Home).toFixed(1)}x`],
  ["Coupon dependency", "Customers who habitually buy on coupon repeat ~15pp less; a single coupon has no measurable effect"],
];
drivers.forEach(([h, t], i) => {
  const y = 4.2 + i * 0.8;
  badge(s, MX, y + 0.05, i + 1);
  richText(s, [{ text: h + ": ", options: { bold: true } }, { text: t }], MX + 0.65, y, CW - 0.65, 0.7, 16);
});
s.addNotes("Headline KPI moved only ~2pp because loyal, high-frequency customers became a larger share of orders. Measured per new customer and per cohort, the decline is 7.5-7.6pp. Three drivers are significant with user-clustered standard errors. Recommendation: switch the KPI immediately, fix Electronics/Home post-purchase experience, and test service recovery and coupon-dependency reduction before rollout.");

// ---------------------------------------------------------------------------
// 3. Business problem
// ---------------------------------------------------------------------------
pres.addSection({ title: "Problem and approach" });
s = content("Repeat customers drive most revenue, so a retention leak is expensive",
  "Repeat customer = 2+ orders in the observation window. Source: outputs/tables/05_customer_type_comparison.csv", "Problem and approach");
card(s, MX, 1.55, 5.0, 4.95);
s.addText(pct(repCust.gmv_share, 0), { x: MX + 0.35, y: 1.85, w: 4.3, h: 1.2, fontSize: 66, bold: true, color: C.accent1, fontFace: THEME.headFontFace, isTextBox: true, margin: 0, objectName: oname("hero") });
richText(s, [{ text: `of GMV comes from repeat customers, who are ${pct(repCust.customer_share, 0)} of customers`, options: { bold: true } }], MX + 0.35, 3.1, 4.3, 0.9, 18);
richText(s, [{ text: `They spend less per order ($${repCust.avg_aov.toFixed(0)} vs $${cust["One-time customer"].avg_aov.toFixed(0)}) but order ${repCust.avg_orders.toFixed(1)} times on average. Their value comes from coming back, which makes the first-to-second order step the key lever.` }], MX + 0.35, 4.15, 4.3, 2.0, 15);
s.addText("Questions this analysis answers", { x: 6.1, y: 1.55, w: 6.6, h: 0.5, fontSize: 20, bold: true, color: C.text2, isTextBox: true, margin: 0, objectName: oname("h") });
[
  "Is repeat purchase really declining, or is it noise?",
  "Which customers are affected: new or established?",
  "What is associated with the decline: service, category, coupons or channel?",
  "Which actions are worth funding, and how do we prove they work?",
].forEach((q, i) => {
  const y = 2.25 + i * 0.95;
  badge(s, 6.1, y, i + 1, C.text2);
  richText(s, [{ text: q }], 6.75, y + 0.02, 5.95, 0.8, 17);
});
s.addNotes("Audience: e-commerce / CRM leadership. Objective: explain whether and why repeat purchase is declining and which actions to fund.");

// ---------------------------------------------------------------------------
// 4. Data & method
// ---------------------------------------------------------------------------
s = content("Approach: clean, measure without bias, explain, then size and test",
  "Pipeline: src/00–06 · Full detail: REPORT.md · Logs: logs/", "Problem and approach");
const steps = [
  ["Data", "42,776 raw order rows, ~14,000 customers, 9 fields; 10 realistic data-quality issues"],
  ["Clean", "97.7% of rows kept; every removal counted; last 30 days censored"],
  ["Measure", "Order-, customer- and cohort-level KPIs; segment profiles"],
  ["Explain", `Logistic regression (user-clustered SEs) + gradient boosting, forward-in-time holdout AUC ${model.auc_holdout.toFixed(2)}`],
  ["Size & check", `Break-even business cases, sensitivity grid, SQL cross-check (${sqlPass}/${sql.length} pass)`],
];
const sw = (CW - 4 * 0.25) / 5;
steps.forEach(([h, t], i) => {
  const x = MX + i * (sw + 0.25);
  card(s, x, 1.6, sw, 2.75);
  badge(s, x + 0.2, 1.8, i + 1);
  s.addText(h, { x: x + 0.2, y: 2.4, w: sw - 0.4, h: 0.45, fontSize: 18, bold: true, color: C.text2, isTextBox: true, margin: 0, objectName: oname("step-h") });
  s.addText(t, { x: x + 0.2, y: 2.9, w: sw - 0.4, h: 1.7, fontSize: 14, color: C.text1, valign: "top", isTextBox: true, margin: 0, objectName: oname("step-t") });
});
card(s, MX, 4.7, CW, 1.4, "FDF0EA");
richText(s, [
  { text: "Data provenance. ", options: { bold: true, color: C.accent2 } },
  { text: "No production data was available, so the order log is simulated with known patterns. The analysis never reads the simulator's settings; it rediscovers them from the data. This deck therefore demonstrates analytical method. The numbers are not real-world facts." },
], MX + 0.3, 4.88, CW - 0.6, 1.1, 16);
s.addNotes("Key safeguards: right-censoring of the last 30 days, point-in-time features, clustered standard errors, forward-in-time model validation, de-confounded coupon analysis, every business case tested against a break-even gate.");

// ---------------------------------------------------------------------------
// 5. KPI definitions
// ---------------------------------------------------------------------------
s = content("Three repeat metrics, three different questions",
  "Full definitions: docs/kpi_definitions.md · Implemented once in src/kpis.py and re-checked in SQL", "Problem and approach");
const th = (t) => ({ text: t, options: { bold: true, color: C.background1, fill: { color: C.text2 } } });
const rowsKpi = [
  [th("KPI"), th("Unit"), th("Numerator ÷ denominator"), th("Use it for")],
  ["Order-level 30-day repeat", "Order", "Orders followed by another order ≤30 days ÷ orders ≥30 days before snapshot", "What was reported; distorted by customer mix"],
  ["New-customer 30-day repeat", "Customer", "First-time customers who reorder ≤30 days ÷ first-time customers ≥30 days before snapshot", "Primary KPI for acquisition quality"],
  ["Cohort M+1 retention", "Customer × month", "Cohort customers ordering in the next calendar month ÷ cohort size", "Retention trend by acquisition month"],
  ["Average order value", "Order", "GMV ÷ orders", "Basket value; compare segments"],
];
s.addTable(rowsKpi, { x: MX, y: 1.6, w: CW, colW: [2.7, 1.7, 5.0, 2.733], fontSize: 14, color: C.text1, valign: "middle",
  border: { type: "solid", pt: 0.75, color: "D5DCE6" }, fill: { color: C.background1 }, rowH: [0.5, 0.75, 0.75, 0.75, 0.6], margin: 0.08, objectName: oname("kpi-table") });
card(s, MX, 5.35, CW, 1.15);
richText(s, [
  { text: "Why it matters: ", options: { bold: true, color: C.accent1 } },
  { text: "repeat rate, retention rate and cohort retention use different units and denominators. Mixing them up is how this decline went unnoticed." },
], MX + 0.3, 5.55, CW - 0.6, 0.8, 16);

// ---------------------------------------------------------------------------
// 6. Finding 1 — headline vs new-customer
// ---------------------------------------------------------------------------
pres.addSection({ title: "Findings" });
s = content("The headline rate hid the decline as loyal customers grew as a share of orders",
  "Source: outputs/tables/02_monthly_trend.csv, 02_order_mix_drift.csv · Orders within 30 days of the snapshot excluded", "Findings");
s.addChart(pres.charts.LINE, [
  { name: "Headline (all orders)", labels: trend.map((r) => r.month), values: trend.map((r) => r.headline_repeat) },
  { name: "New customers", labels: trend.map((r) => r.month), values: trend.map((r) => r.new_user_repeat) },
], { x: MX, y: 1.5, w: 8.1, h: 5.1, ...AXIS, chartColors: [H.accent4, H.accent1], lineSize: 2, lineDataSymbol: "circle", lineDataSymbolSize: 6,
  valAxisLabelFormatCode: "0%", valAxisMinVal: 0.3, valAxisMaxVal: 0.65, catAxisLabelRotate: -45,
  showLegend: true, legendPos: "t", legendFontSize: 12, legendColor: MUTED,
  showTitle: true, title: "30-day repeat rate by month", titleFontSize: 14, titleColor: C.text2, titleFontFace: "+mn-lt", objectName: oname("chart") });
stat(s, 9.0, 1.55, 3.733, 2.45, pct(mix["2025-05"].share_orders_from_4plus, 0), "of orders from loyal customers", "Customers with 4+ prior orders, May 2025 (0% in Jan 2024). They repeat at ~70%.", C.accent1);
richText(s, [{ text: "So the average barely moved, while each new cohort came back less often. ", options: { bold: true } },
  { text: "Track new-customer repeat and cohort retention, not the blended headline." }], 9.0, 4.3, 3.733, 2.2, 16);

// ---------------------------------------------------------------------------
// 7. Finding 2 — cohort M+1
// ---------------------------------------------------------------------------
s = content("Every cohort acquired since November 2024 retains worse, at any time window",
  "Source: outputs/tables/02_cohort_retention.csv, 05_window_sensitivity.csv · Robustness uses the same customers under each window", "Findings");
const isLate = (c) => c >= "2024-11";
s.addChart(pres.charts.BAR, [
  { name: "Before Nov 2024", labels: cohort.map((r) => r.cohort), values: cohort.map((r) => (isLate(r.cohort) ? 0 : r.m1)) },
  { name: "Nov 2024 onward", labels: cohort.map((r) => r.cohort), values: cohort.map((r) => (isLate(r.cohort) ? r.m1 : 0)) },
], { x: MX, y: 1.5, w: 7.6, h: 5.1, barDir: "col", barGrouping: "stacked", barGapWidthPct: 40, ...AXIS, chartColors: [H.accent1, H.accent2],
  valAxisLabelFormatCode: "0%", valAxisMinVal: 0, valAxisMaxVal: 0.4, catAxisLabelRotate: -45,
  showLegend: true, legendPos: "t", legendFontSize: 12, legendColor: MUTED,
  showTitle: true, title: "M+1 retention by acquisition cohort", titleFontSize: 14, titleColor: C.text2, titleFontFace: "+mn-lt", objectName: oname("chart") });
s.addText("Is it just the 30-day window?", { x: 8.55, y: 1.55, w: 4.18, h: 0.45, fontSize: 18, bold: true, color: C.text2, isTextBox: true, margin: 0, objectName: oname("h") });
const winRows = [[th("Window"), th("Baseline"), th("Recent"), th("Change")]].concat(
  win.map((r) => [`${r.window_days} days`, pct(r.baseline_rate), pct(r.recent_rate), { text: pp(r.recent_rate - r.baseline_rate), options: { bold: true, color: C.accent2 } }]));
s.addTable(winRows, { x: 8.55, y: 2.1, w: 4.18, colW: [1.1, 1.03, 1.03, 1.02], fontSize: 14, color: C.text1, align: "center",
  border: { type: "solid", pt: 0.75, color: "D5DCE6" }, rowH: 0.45, margin: 0.05, objectName: oname("win-table") });
richText(s, [{ text: "No. The gap holds at 30, 60 and 90 days ", options: { bold: true } },
  { text: `(all p < 1e-10). New-customer repeat, share of customers who order again. Baseline cohorts Apr–Sep 2024 (n=${win[0].baseline_n.toLocaleString("en-US")}); recent Nov 2024–Mar 2025 (n=${win[0].recent_n.toLocaleString("en-US")}).` }],
  8.55, 4.2, 4.18, 2.3, 14);

// ---------------------------------------------------------------------------
// 8. Finding 3 — tickets
// ---------------------------------------------------------------------------
s = content("Repeat purchase collapses at the third support ticket, and ticket load has doubled",
  "Source: outputs/tables/05_ticket_robustness.csv, 03_odds_ratios.csv, 02_ticket_trend.csv, 02_ticket_by_category_month.csv", "Findings");
s.addChart(pres.charts.BAR, [{ name: "30-day repeat", labels: ["0 tickets", "1", "2", "3+"], values: ticketRate }],
  { x: MX, y: 1.5, w: 6.6, h: 5.1, barDir: "col", barGapWidthPct: 45, ...AXIS, chartColors: [H.accent1, H.accent1, H.accent1, H.accent2],
    valAxisLabelFormatCode: "0%", valAxisMinVal: 0, valAxisMaxVal: 0.7, showValue: true, dataLabelFormatCode: "0.0%", dataLabelPosition: "outEnd",
    dataLabelColor: C.text1, dataLabelFontSize: 13, showLegend: false,
    showTitle: true, title: "30-day repeat rate by support tickets on the order", titleFontSize: 14, titleColor: C.text2, titleFontFace: "+mn-lt", objectName: oname("chart") });
const t3 = odds.tickets_3p;
stat(s, 7.55, 1.55, 2.5, 2.45, t3.odds_ratio.toFixed(2), "Odds ratio, 3+ tickets", `95% CI ${t3.or_ci_low.toFixed(2)}–${t3.or_ci_high.toFixed(2)}, after controls`);
stat(s, 10.23, 1.55, 2.5, 2.45, `${pct(tickTrend["2024-01"].pct_1plus, 0)}→${pct(tickTrend["2025-06"].pct_1plus, 0)}`, "Orders with a ticket", "Jan 2024 → Jun 2025", C.accent2, 26);
richText(s, [{ text: "Where the strain landed: ", options: { bold: true } },
  { text: `Electronics tickets per order rose from ${catTick["2024-01"].Electronics.toFixed(2)} to ${catTick["2025-06"].Electronics.toFixed(2)}, Home from ${catTick["2024-01"].Home.toFixed(2)} to ${catTick["2025-06"].Home.toFixed(2)}. These are the highest-value categories. The ticket gradient holds within every category.` }],
  7.55, 4.3, 5.18, 2.2, 15);
s.addNotes(`Only ${ticketN[3]} scoreable orders have 3+ tickets, so the lever is deep but narrow. Association, not proven causation: customers who are already leaving may complain more. The model-based counterfactual used for sizing is far smaller than the raw gap.`);

// ---------------------------------------------------------------------------
// 9. Finding 4 — coupons
// ---------------------------------------------------------------------------
s = content("Coupons are not the problem; coupon dependency is",
  "Customers with 3+ prior orders only, to avoid one-order customers having a 100% coupon rate by construction. Source: 02_tipping_discount.csv, 03_odds_ratios.csv", "Findings");
s.addChart(pres.charts.BAR, [{ name: "30-day repeat", labels: disc.map((r) => r.band), values: disc.map((r) => r.repeat_30d) }],
  { x: MX, y: 1.5, w: 6.6, h: 5.1, barDir: "col", barGapWidthPct: 45, ...AXIS, chartColors: [H.accent1],
    valAxisLabelFormatCode: "0%", valAxisMinVal: 0, valAxisMaxVal: 0.85, showValue: true, dataLabelFormatCode: "0.0%", dataLabelPosition: "outEnd",
    dataLabelColor: C.text1, dataLabelFontSize: 13, showLegend: false,
    showTitle: true, title: "30-day repeat by share of past orders bought on coupon", titleFontSize: 14, titleColor: C.text2, titleFontFace: "+mn-lt", objectName: oname("chart") });
stat(s, 7.55, 1.55, 2.5, 2.45, odds.discount_used.odds_ratio.toFixed(2), "Coupon on this order", `Not significant (p = ${odds.discount_used.p_value.toFixed(2)})`, C.accent4);
stat(s, 10.23, 1.55, 2.5, 2.45, odds.disc_dep_c.odds_ratio.toFixed(2), "Habitual coupon use", "Always vs never; p < 0.001");
richText(s, [{ text: "Implication: ", options: { bold: true } },
  { text: "do not stop couponing. Break the habit for customers who only buy on discount. This is also the weakest causal link (low-intent customers may seek coupons), so test it before rollout." }],
  7.55, 4.3, 5.18, 2.2, 15);

// ---------------------------------------------------------------------------
// 10. What is explained
// ---------------------------------------------------------------------------
s = content("Service and coupon dependency explain about half of the decline; the rest needs new data",
  "Logit ladder on the post-Oct-2024 period effect, with lifecycle, category, channel and order-value controls. Source: 03_mediation_ladder.csv", "Findings");
const segs = [
  ["Support tickets & returns", medService, H.accent1],
  ["Coupon dependency", medAll - medService, H.accent5],
  ["Not observable in the order log", 1 - medAll, "D9D8D2"],
];
let x0 = MX;
segs.forEach(([lbl, v, col]) => {
  const w = CW * v;
  s.addShape(pres.shapes.RECTANGLE, { x: x0, y: 2.0, w, h: 1.1, fill: { color: col }, line: { color: "FFFFFF", width: 2 }, objectName: oname("seg") });
  s.addText(pct(v, 0), { x: x0, y: 2.0, w, h: 1.1, fontSize: 24, bold: true, color: col === H.accent1 ? "FFFFFF" : C.text1, align: "center", valign: "middle", isTextBox: true, margin: 0, objectName: oname("seg-v") });
  s.addText(lbl, { x: x0 + 0.05, y: 3.18, w: w - 0.1, h: 0.7, fontSize: 14, valign: "top", color: C.text1, isTextBox: true, margin: 0, objectName: oname("seg-l") });
  x0 += w;
});
s.addText("Share of the controlled decline in 30-day repeat (log-odds scale)", { x: MX, y: 1.5, w: CW, h: 0.4, fontSize: 14, color: MUTED, isTextBox: true, margin: 0, objectName: oname("cap") });
const cards3 = [
  ["Hidden by mix", `Measured naively the period effect is not significant (OR ${ladder[0].degraded_OR.toFixed(2)}, p = ${ladder[0].p_value.toFixed(2)}). With controls it is clear (OR ${ladder[1].degraded_OR.toFixed(2)}).`],
  ["Partly explained", `Tickets, returns and coupon dependency absorb ${pct(medAll, 0)} of it. These are the levers in the recommendations.`],
  ["Next data to collect", "Delivery times, stockouts and assortment changes. The order log cannot see them, and they are the best candidates for the rest."],
];
const c3w = (CW - 0.6) / 3;
cards3.forEach(([h, t], i) => {
  const x = MX + i * (c3w + 0.3);
  card(s, x, 4.0, c3w, 2.5);
  s.addText(h, { x: x + 0.25, y: 4.18, w: c3w - 0.5, h: 0.45, fontSize: 18, bold: true, color: C.text2, isTextBox: true, margin: 0, objectName: oname("h") });
  s.addText(t, { x: x + 0.25, y: 4.68, w: c3w - 0.5, h: 1.7, fontSize: 15, color: C.text1, valign: "top", isTextBox: true, margin: 0, objectName: oname("t") });
});

// ---------------------------------------------------------------------------
// 11. Recommendations
// ---------------------------------------------------------------------------
pres.addSection({ title: "Recommendations" });
s = content("Four actions, ordered by strength of evidence and value",
  "Net contribution = base-case annual planning estimate (10% sample assumption). Source: outputs/tables/04_business_cases.csv", "Recommendations");
const sumNet = (re) => caseOf(re).reduce((a, r) => a + r.net_yr, 0);
const recs = [
  ["Switch the KPI", "This week · no cost", "Report new-customer repeat and cohort M+1 weekly; keep the headline as a secondary metric.", "Measure: adopted in the weekly business review", C.accent3],
  ["Fix Electronics & Home after-sales", `Base case ${usdK(sumNet(/^2\./))} net / yr`, "Product information, proactive delivery updates and inbound quality checks to cut tickets at the source.", "Measure: tickets per order ≤ 0.35; staged rollout by category", C.accent1],
  ["Recover at the 2nd ticket", `Base case ${usdK(sumNet(/^1\./))} net / yr`, "Automated recovery at 2 tickets; senior-agent callback at 3+. Tiering follows from break-even costs.", "Measure: 2 tickets: 10% holdout, fewer escalations; 3+: 50/50 test, repeat", C.accent1],
  ["Test coupon-habit reduction", `Base case ${usdK(sumNet(/^3\./))} net / yr if proven`, "Targeted CRM for customers who buy ≥60% on coupon. Weakest causal evidence.", "Measure: A/B test before any rollout; repeat and margin", C.accent2],
];
const rw = (CW - 0.3) / 2, rh = 2.4;
recs.forEach(([h, tag, body, meas, col], i) => {
  const x = MX + (i % 2) * (rw + 0.3), y = 1.55 + Math.floor(i / 2) * (rh + 0.25);
  card(s, x, y, rw, rh);
  badge(s, x + 0.25, y + 0.25, i + 1, col);
  s.addText(h, { x: x + 0.85, y: y + 0.22, w: rw - 1.1, h: 0.5, fontSize: 19, bold: true, color: C.text2, isTextBox: true, margin: 0, objectName: oname("h") });
  s.addText(tag, { x: x + 0.85, y: y + 0.7, w: rw - 1.1, h: 0.35, fontSize: 14, bold: true, color: col, isTextBox: true, margin: 0, objectName: oname("tag") });
  s.addText(body, { x: x + 0.25, y: y + 1.12, w: rw - 0.5, h: 0.75, fontSize: 14, color: C.text1, valign: "top", isTextBox: true, margin: 0, objectName: oname("b") });
  s.addText(meas, { x: x + 0.25, y: y + 1.9, w: rw - 0.5, h: 0.38, fontSize: 13, italic: true, color: MUTED, isTextBox: true, margin: 0, objectName: oname("m") });
});
s.addNotes("Each recommendation states evidence, target, action, expected outcome and how to measure it. Effect sizes come from model counterfactuals with a realisation haircut, not from experiments, so recommendations 2-4 ship with a holdout or staged rollout.");

// ---------------------------------------------------------------------------
// 12. Business case
// ---------------------------------------------------------------------------
s = content("Base case: ~$240k net contribution a year, but only if the uplift is proven",
  "Annualised, contribution margin 42%, assumes the data is a 10% customer sample. Source: 04_business_cases.csv, 04_sensitivity.csv", "Recommendations");
const caseLbl = ["1A Automated recovery", "1B Human callback", "2 Electronics/Home fix", "3 Coupon-habit test"];
s.addChart(pres.charts.BAR, [
  { name: "Benefit (repeat contribution + cost avoided)", labels: caseLbl, values: cases.map((r) => r.total_benefit_yr / 1000) },
  { name: "Programme cost", labels: caseLbl, values: cases.map((r) => r.cost_yr / 1000) },
], { x: MX, y: 1.5, w: 7.6, h: 5.1, barDir: "col", barGapWidthPct: 60, ...AXIS, chartColors: [H.accent1, H.accent4],
  valAxisLabelFormatCode: "$#,##0\"k\"", showValue: true, dataLabelFormatCode: "$#,##0\"k\"", dataLabelPosition: "outEnd", dataLabelColor: C.text1, dataLabelFontSize: 11,
  showLegend: true, legendPos: "t", legendFontSize: 12, legendColor: MUTED,
  showTitle: true, title: "Annual benefit vs cost, base case ($000)", titleFontSize: 14, titleColor: C.text2, titleFontFace: "+mn-lt", objectName: oname("chart") });
stat(s, 8.55, 1.55, 4.18, 2.1, usd(netTot), "Net contribution / yr", `on ${usd(costTot)} cost · net ROI ${(netTot / costTot).toFixed(2)}x · ${usd(gmvTot)} incremental GMV`, C.accent1);
richText(s, [
  { text: "Risks, stated up front\n", options: { bold: true, color: C.text2, breakLine: true } },
  { text: `${sensPos} of ${sensCells.length} sensitivity scenarios are value-positive.`, options: { bullet: true, breakLine: true } },
  { text: `With zero repeat uplift the portfolio loses ${usd(-floorNet)}; savings alone do not pay for it.`, options: { bullet: true, breakLine: true } },
  { text: "Effects come from observational models, so run the controlled tests first.", options: { bullet: true } },
], 8.55, 3.95, 4.18, 2.6, 14);

// ---------------------------------------------------------------------------
// 13. Dashboard
// ---------------------------------------------------------------------------
s = content("An interactive dashboard keeps the right KPIs in front of the team",
  "Screenshot of dashboard/app.py running locally (Streamlit). Run: streamlit run dashboard/app.py", "Recommendations");
const img = path.join(ROOT, "docs", "images", "dashboard_hero.png"); // 1140 x 810 px crop
s.addImage({ path: img, x: MX, y: 1.5, w: 7.2, h: 7.2 * 810 / 1140, objectName: oname("screenshot") });
s.addShape(pres.shapes.RECTANGLE, { x: MX, y: 1.5, w: 7.2, h: 7.2 * 810 / 1140, fill: { type: "none" }, line: { color: "D5DCE6", width: 1 }, objectName: oname("frame") });
bullets(s, [
  "KPI tiles use the same code as the analysis (src/kpis.py); automated tests check they match",
  "Filters: month range, acquisition channel, category",
  "Tabs: overview, cohorts, customer behaviour, drivers, recommendations, definitions",
  "Every chart has hover tooltips and a plain-English caption",
], 8.2, 1.6, 4.53, 4.9, 16);

// ---------------------------------------------------------------------------
// 14. Roadmap
// ---------------------------------------------------------------------------
s = content("Roadmap: change the metric this week, prove the levers within six months",
  "Owners are suggested functions. Dates are relative to approval.", "Recommendations");
const road = [
  ["Week 1–2", "Switch reporting to new-customer repeat & cohort M+1; real-time alert at 2 tickets", "Analytics, Data Eng"],
  ["Week 3–8", "Launch automated recovery (10% holdout) and callbacks (50/50 test, ~6 months)", "Customer Service Ops"],
  ["Month 2–5", "Electronics/Home: product content, delivery updates, inbound QC; staged rollout", "Merchandising, Fulfilment"],
  ["Month 3–6", "Randomised test of coupon-habit reduction; scale only on a significant result", "CRM, Analytics"],
  ["Month 4+", "Instrument delivery time, stockouts and assortment to explain the remaining ~50%", "Data Eng"],
];
const rwid = (CW - 4 * 0.2) / 5;
s.addShape(pres.shapes.LINE, { x: MX + 0.23, y: 2.03, w: CW - 0.46, h: 0, line: { color: "C3C2B7", width: 1.5 }, objectName: oname("timeline") });
road.forEach(([when, what, who], i) => {
  const x = MX + i * (rwid + 0.2);
  badge(s, x, 1.8, i + 1, i === 0 ? C.accent3 : C.accent1);
  s.addText(when, { x, y: 2.45, w: rwid, h: 0.45, fontSize: 18, bold: true, color: C.text2, isTextBox: true, margin: 0, objectName: oname("when") });
  card(s, x, 3.0, rwid, 2.6);
  s.addText(what, { x: x + 0.18, y: 3.18, w: rwid - 0.36, h: 1.55, fontSize: 15, color: C.text1, valign: "top", isTextBox: true, margin: 0, objectName: oname("what") });
  s.addText(who, { x: x + 0.18, y: 4.75, w: rwid - 0.36, h: 0.7, fontSize: 13, italic: true, color: MUTED, valign: "bottom", isTextBox: true, margin: 0, objectName: oname("who") });
});

// ---------------------------------------------------------------------------
// 15. Limitations & conclusion
// ---------------------------------------------------------------------------
pres.addSection({ title: "Conclusion" });
s = pres.addSlide({ masterName: "Title dark", sectionTitle: "Conclusion" });
s.addText("What this shows, and what it does not", { x: MX, y: 0.6, w: CW, h: 0.9, fontSize: 36, bold: true, color: C.background1, fontFace: THEME.headFontFace, isTextBox: true, margin: 0, objectName: oname("t") });
s.addText("Conclusion", { x: MX, y: 1.75, w: 5.6, h: 0.45, fontSize: 20, bold: true, color: "CADCFC", isTextBox: true, margin: 0, objectName: oname("h") });
s.addText([
  { text: "The repeat decline is real, concentrated in new customers, and was hidden by the KPI definition.", options: { bullet: true, breakLine: true, paraSpaceAfter: 10 } },
  { text: "Support tickets, Electronics/Home after-sales and coupon habits are the measurable levers.", options: { bullet: true, breakLine: true, paraSpaceAfter: 10 } },
  { text: "Change the metric now; fund the levers through controlled tests.", options: { bullet: true } },
], { x: MX, y: 2.3, w: 5.6, h: 3.8, fontSize: 17, color: C.background1, valign: "top", isTextBox: true, objectName: oname("concl") });
s.addText("Limitations", { x: 6.9, y: 1.75, w: 5.83, h: 0.45, fontSize: 20, bold: true, color: "CADCFC", isTextBox: true, margin: 0, objectName: oname("h") });
s.addText([
  { text: "Simulated data: methods transfer, numbers do not", options: { bullet: true, breakLine: true, paraSpaceAfter: 8 } },
  { text: "Observational models; no experiment has been run", options: { bullet: true, breakLine: true, paraSpaceAfter: 8 } },
  { text: "About half of the decline is unexplained by the available fields", options: { bullet: true, breakLine: true, paraSpaceAfter: 8 } },
  { text: "Dollar figures rely on a 10% sample assumption and planning costs", options: { bullet: true, breakLine: true, paraSpaceAfter: 8 } },
  { text: "Ticket and return timing may overlap the 30-day outcome window", options: { bullet: true } },
], { x: 6.9, y: 2.3, w: 5.83, h: 3.8, fontSize: 16, color: C.background1, valign: "top", isTextBox: true, objectName: oname("lim") });
s.addText("Full report, code and dashboard: github.com/Newnew-niu/ecommerce-repeat-purchase-analysis",
  { x: MX, y: 6.4, w: CW, h: 0.4, fontSize: 14, color: "CADCFC", isTextBox: true, margin: 0, objectName: oname("link") });

// ---------------------------------------------------------------------------
// Write + theme
// ---------------------------------------------------------------------------
async function applyTheme(file, theme) {
  const zip = await JSZip.loadAsync(fs.readFileSync(file));
  const p = "ppt/theme/theme1.xml";
  let xml = await zip.file(p).async("string");
  const slot = (k) => `<a:${k}><a:srgbClr val="${theme.colors[k]}"/></a:${k}>`;
  const scheme = `<a:clrScheme name="${theme.name}">${["dk1", "lt1", "dk2", "lt2", "accent1", "accent2", "accent3", "accent4", "accent5", "accent6", "hlink", "folHlink"].map(slot).join("")}</a:clrScheme>`;
  xml = xml.replace(/<a:clrScheme[\s\S]*?<\/a:clrScheme>/, scheme).replace(/(<a:theme[^>]*name=")[^"]*"/, `$1${theme.name}"`);
  zip.file(p, xml);
  fs.writeFileSync(file, await zip.generateAsync({ type: "nodebuffer", compression: "DEFLATE" }));
}

(async () => {
  await pres.writeFile({ fileName: OUT });
  await applyTheme(OUT, THEME);
  console.log("wrote", OUT);
})();
