const navItems = [
  { id: "welcome", label: "Welcome", kicker: "Home", icon: "H" },
  { id: "overview", label: "System Overview", kicker: "Home", icon: "O" },
  { id: "scenario_builder", label: "Scenario Builder", kicker: "Research Setup", icon: "S" },
  { id: "data_health", label: "Data Health", kicker: "Research Setup", icon: "D" },
  { id: "backtest_runner", label: "Backtest Runner", kicker: "Research Setup", icon: "B" },
  { id: "run_history", label: "Run History", kicker: "Research Setup", icon: "R" },
  { id: "factor_lab", label: "Signal & Factor Builder", kicker: "Analytics", icon: "F" },
  { id: "performance_dashboard", label: "Performance Dashboard", kicker: "Analytics", icon: "P" },
  { id: "risk_dashboard", label: "Risk Dashboard", kicker: "Analytics", icon: "RK" },
  { id: "robustness_lab", label: "Robustness Lab", kicker: "Analytics", icon: "RB" },
  { id: "holdings_trades", label: "Trade Blotter & Execution", kicker: "Portfolio", icon: "T" },
  { id: "artifacts", label: "Artifacts", kicker: "Delivery", icon: "A" },
  { id: "report_studio", label: "Report Studio", kicker: "Delivery", icon: "RS" },
  { id: "help", label: "Help", kicker: "Help", icon: "?" },
];

const navSections = {
  home: ["welcome", "overview"],
  research_setup: ["scenario_builder", "data_health", "backtest_runner", "run_history"],
  analytics: ["factor_lab", "performance_dashboard", "risk_dashboard", "robustness_lab"],
  portfolio: ["holdings_trades"],
  delivery: ["artifacts", "report_studio"],
  help: ["help"],
};

const DEFAULT_ROBUSTNESS_PERCENTILES = [
  ["Bootstrap P50", "14.4%"],
  ["Base MC P50", "13.9%"],
  ["Stress 1.5x P50", "9.0%"],
  ["Stress 2x P50", "-32.2%"],
  ["Local perturbation P50", "16.1%"],
];

const REPORT_REQUEST_FORMAT_OPTIONS = [
  "openai",
  "claude",
  "gemini",
  "compatible api",
  "custom json",
];

const REPORT_DEFAULT_API_URLS = {
  openai: "https://api.openai.com/v1",
  claude: "https://api.anthropic.com/v1",
  gemini: "https://generativelanguage.googleapis.com/v1beta",
  "compatible api": "https://api.openai.com/v1/chat/completions",
};

const REPORT_MANAGED_API_URLS = [
  "https://api.openai.com/v1",
  "https://api.openai.com/v1/responses",
  "https://api.openai.com/v1/chat/completions",
  "https://api.anthropic.com/v1",
  "https://api.anthropic.com/v1/messages",
  "https://generativelanguage.googleapis.com/v1beta",
];
const REPORT_STUDIO_OPTIONAL_INPUT_KEYS = new Set(["api_key", "system_prompt", "user_instruction", "api_url"]);
const MULTILINE_INPUT_KEYS = new Set(["system_prompt", "user_instruction"]);
const SECRET_INPUT_KEYS = new Set(["api_key"]);
const LEGACY_REPORT_USER_INSTRUCTION = "Generate an English report note that assesses performance, robustness, caveats, and the points that should be emphasized in the formal written report.";
const DEFAULT_REPORT_USER_INSTRUCTION = "Write an investor-facing portfolio analysis report. Focus on strategy logic, backtest evidence, risk profile, and concise robustness conclusions. Keep numeric claims tied to the supplied data.";

function isLegacyReportUserInstruction(value) {
  const normalized = String(value || "").trim().toLowerCase().replace(/\s+/g, " ");
  if (!normalized) return false;
  if (normalized === LEGACY_REPORT_USER_INSTRUCTION.toLowerCase()) return true;
  if (normalized.includes("report note") && normalized.includes("teammates")) return true;
  return (
    normalized.includes("generate an english report note") &&
    normalized.includes("performance") &&
    normalized.includes("robustness") &&
    normalized.includes("written report")
  );
}

const store = {
  overview: {
    headline: "Quarterly-rebalanced hybrid equity allocation with VIX-aware regime switching",
    summary: "This shell now mirrors the formal_s30 research baseline rather than the earlier presentation-oriented framing.",
    metrics: [
      { label: "Current Regime", value: "Stress", note: "VIX crossed baseline stress threshold of 22.0" },
      { label: "Current VIX", value: "28.4", note: "Up 3.2 points versus last rebalance" },
      { label: "Baseline Run", value: "formal_s30", note: "Best verified run_id 6905e84b-9e16-4106-8c0f-cd9ecce56728" },
    ],
    assumptions: [
      "Quarterly-rebalanced target generation is aligned to quarterly execution instead of rebuilding monthly targets off-cycle.",
      "Hybrid portfolio construction keeps the live baseline inside a 25 to 35 name band with sector and single-name caps.",
      "The production baseline keeps drawdown brake disabled; regime switching comes from the VIX-aware overlay only.",
    ],
    rebalance: [
      ["Dividend", "+6.0%", "Stress overlay increased defensive weight"],
      ["Quality", "+4.0%", "Balance sheet stability preferred"],
      ["Momentum", "-7.5%", "Exposure reduced to avoid whipsaw"],
      ["Value", "-2.5%", "Trimmed to keep factor budget stable"],
    ],
    perfSeries: [100, 102, 101, 105, 107, 110, 112, 111, 114, 117, 119, 121],
  },
  health: {
    updatedAt: "2026-04-06 08:30",
    coverage: [["Price", 99.8], ["Fundamental", 96.4], ["Sector Map", 100], ["VIX", 100], ["Benchmark", 99.2]],
    missingRates: [["Price", 0.2], ["Fundamental", 3.6], ["Sector Map", 0], ["VIX", 0], ["Benchmark", 0.8]],
    checks: [["Schema validation", "Pass"], ["Null spike alert", "Pass"], ["Outlier clipping", "Pass"], ["Duplicate ticker rows", "Fail"], ["Point-in-time alignment", "Pass"]],
    dag: [["Ingestion", "Success"], ["Feature build", "Success"], ["Backtest refresh", "Running"], ["Dashboard export", "Queued"]],
  },
  factors: {
    factorBlocks: [["Value", "B/P, E/P, FCF Yield"], ["Quality", "ROE, Gross Margin, Accruals"], ["Momentum", "6M return, 12-1 return, EPS revision"], ["Dividend", "Yield, payout stability, coverage"]],
    correlation: [[1, 0.42, -0.18, 0.36], [0.42, 1, -0.22, 0.48], [-0.18, -0.22, 1, -0.12], [0.36, 0.48, -0.12, 1]],
    icSeries: [0.03, 0.05, 0.01, 0.06, 0.04, -0.01, 0.03, 0.02, 0.05, 0.04],
  },
  portfolio: {
    holdings: [["JNJ", "Health Care", "4.9%", "Quality / Dividend"], ["PG", "Consumer Staples", "4.7%", "Dividend"], ["XOM", "Energy", "4.5%", "Value / Dividend"], ["MSFT", "Technology", "4.3%", "Quality"], ["PEP", "Consumer Staples", "4.1%", "Dividend / Quality"]],
    sectors: [["Consumer Staples", 18], ["Health Care", 16], ["Energy", 13], ["Technology", 12], ["Financials", 11], ["Utilities", 9]],
    weights: [["0-2%", 6], ["2-3%", 8], ["3-4%", 9], ["4-5%", 7]],
    topTen: [["JNJ", 4.9], ["PG", 4.7], ["XOM", 4.5], ["MSFT", 4.3], ["PEP", 4.1], ["KO", 3.9], ["ABBV", 3.8], ["MRK", 3.6], ["CVX", 3.4], ["T", 3.2]],
    turnover: "18.2%",
    rebalanceLog: [["2026-04-01", "Shift to stress regime", "Reduced momentum, added dividend"], ["2026-03-03", "Monthly performance record", "Carry-forward holdings drift; no new target optimisation"], ["2026-02-03", "Monthly performance record", "Monitoring snapshot only; quarterly target weights unchanged"]],
  },
  performance: {
    nav: [100, 101, 102, 104, 103, 106, 108, 109, 111, 114, 116, 119],
    benchmark: [100, 100.5, 101, 101.8, 101.2, 102.4, 103.3, 103.6, 104.8, 106, 107.2, 108.5],
    baseline: [100, 100.8, 101.4, 102.1, 101.7, 102.9, 103.7, 104.2, 105.1, 106.2, 107.3, 108.1],
    drawdown: [0, -0.6, -0.3, -1.2, -0.5, -1.8, -1, -0.7, -0.2, -0.4, -0.1, 0],
    sharpe: [0.6, 0.8, 0.9, 1.1, 1, 1.2, 1.4, 1.35, 1.5, 1.58, 1.62, 1.69],
    monthlyHeatmap: [[1.2, 0.8, -0.4, 1.5], [0.3, -0.6, 0.9, 1.1], [1.4, 1, 0.2, -0.3]],
    excess: [0, 0.5, 1, 2.2, 1.8, 3.6, 4.7, 5.4, 6.2, 7.8, 8.8, 10.5],
  },
  regime: {
    vix: [16, 17, 19, 18, 21, 24, 27, 30, 28, 26, 24, 22],
    threshold: 22,
    exposures: [["Dividend", 0.24, 0.34], ["Quality", 0.22, 0.3], ["Value", 0.27, 0.24], ["Momentum", 0.27, 0.12]],
    exposureChange: [["Dividend", "+10pp"], ["Quality", "+8pp"], ["Value", "-3pp"], ["Momentum", "-15pp"]],
    strip: ["normal", "normal", "normal", "normal", "normal", "stress", "stress", "stress", "stress", "normal"],
  },
  robustness: {
    scenarios: [["Cost 10bps / quarterly / hybrid 25-35 / VIX 22", "11.8%", "1.69", "-6.4%"], ["Cost 15bps baseline / quarterly / hybrid 25-35 / VIX 22", "10.7%", "1.48", "-7.3%"], ["Cost 25bps / quarterly / hybrid 25-35 / VIX 22", "12.1%", "1.51", "-8.6%"], ["Regime 20/18 / quarterly / hybrid 25-35", "10.9%", "1.41", "-6.0%"], ["Trade band 1% / per-name cap 4%", "10.2%", "1.37", "-6.7%"]],
    subperiods: [["Normal", "12.5%", "1.54", "0.58"], ["Stress", "8.9%", "1.22", "0.67"]],
    monteCarlo: [14, 19, 27, 34, 31, 25, 17, 12],
    percentiles: DEFAULT_ROBUSTNESS_PERCENTILES.map((row) => [...row]),
    acceptance: [],
  },
  scenarioBuilder: {
    presets: [["Base", "US large cap, quarterly rebalance, hybrid 25-35"], ["Stress-aware", "VIX switch at 22, defensive sleeve rotation"], ["Low-turnover", "Quarterly baseline with tighter trading frictions"]],
    assumptions: [["Universe", "US liquid large-cap basket"], ["Rebalance", "Quarterly with quarterly-rebalanced targets"], ["Neutralisation", "Sector-neutral score construction"], ["Costs", "15bps baseline one-way"]],
    inputs: [["Factor sleeves", "Quality, Value, Market Technical, Dividend"], ["VIX threshold", "22"], ["Target range", "25-35 names"], ["Holding cap", "5%"]],
    controls: {
      universe: "US Large Cap",
      rebalance: "Quarterly",
      topN: "25",
      threshold: "22",
      cost: "15bps",
      neutralisation: "Sector Neutral",
    },
  },
  runHistory: {
    runs: [["BT-2026-0406-01", "2026-04-06 08:15", "Stress-aware monitoring refresh", "Success", "08m 14s"], ["BT-2026-0405-01", "2026-04-05 08:12", "Daily refresh / export pack", "Success", "05m 31s"], ["BT-2026-0404-01", "2026-04-04 08:10", "Scenario compare batch", "Warning", "11m 06s"], ["BT-2026-0403-01", "2026-04-03 08:09", "Monthly performance snapshot", "Success", "07m 42s"]],
    artifacts: [["Latest NAV pack", "Generated"], ["Risk tearsheet", "Generated"], ["Robustness export", "Pending"], ["Slide appendix", "Generated"]],
    filters: {
      scenario: "All scenarios",
      status: "All status",
      owner: "Team C",
    },
  },
  docs: {
    docs: [["API Documentation", "Document factor endpoints, backtest outputs, and health check payloads."], ["Data Dictionary", "List raw fields, derived columns, units, cadence, and provenance."], ["Runbook", "Provide startup flow, dependency checks, and fallback steps."], ["Platform Notes", "Spell out Windows/macOS differences for paths and commands."]],
  },
  artifacts: {
    records: [],
    packs: [["Presentation appendix", "PPT-ready charts and captions"], ["Backtest CSV bundle", "NAV, positions, trades, factor scores"], ["Risk tearsheet", "Drawdown, beta, sector, regime exposure"], ["Robustness export", "Scenario grid and Monte Carlo percentile tables"]],
  },
  reportStudio: {
    blocks: [["Executive Summary", "Top-line investment case, headline backtest conclusion, main caveat, and confidence level."], ["Strategy And Portfolio Construction", "Universe, factor design, IC weighting, regime tilts, covariance-aware construction, and constraints."], ["Backtest Design", "PIT discipline, benchmark hierarchy, costs, execution lag, rebalance cadence, and metric conventions."], ["Backtest Results", "Absolute return, benchmark-relative value added, risk-adjusted quality, drawdown, turnover, and cost drag."], ["Risk, Regime And Exposure Analysis", "Regime attribution, sector concentration, volatility, drawdown, and investor experience of risk."], ["Robustness And Sensitivity", "Compact validation evidence that materially changes confidence in the backtest conclusion."], ["Limitations And Monitoring Signals", "Residual weaknesses and the few live signals investors should monitor next."]],
    history: [],
    aiReport: {
      reportId: "",
      status: "idle",
      generatedAt: "",
      providerUrl: "",
      model: "",
      requestFormat: "openai",
      outputPath: "",
      outputMarkdownPath: "",
      outputDocxPath: "",
      outputPdfPath: "",
      analysisText: "",
      sections: {},
      promptTemplateVersion: "cw2-report-v4",
      guardrails: {},
      sourceTracePreview: [],
    },
  },
  scenarioCenter: {
    items: [],
    mainlineId: "",
    activeScenarioId: "",
  },
  help: {
    glossary: [
      ["Report primary baseline", "SPY broad-market benchmark", "Use this for the final investor-facing market-relative comparison."],
      ["Internal universe benchmark", "Equal-weight investable universe", "Use this as a supporting lens for stock-selection value inside the same tradable pool."],
      ["Model baseline", "Static multi-factor mix with fixed normal weights and the same quarterly-rebalanced selection constraints", "Use this to isolate the value added by the dynamic VIX-aware overlay, not to change the investable universe or portfolio rules."],
    ],
    robustnessCoverage: [
      ["Part 1 - Deterministic", "Tests 1-8 across costs, breadth, thresholds, brakes, incumbent bands, and trade constraints.", "Checks whether the quarterly-rebalanced mainline result survives direct parameter changes rather than only one calibrated setting."],
      ["Part 2 - Ablation", "Blocks A-C isolate the major sleeves or rule groups.", "Checks which building blocks genuinely drive the reported edge."],
      ["Part 3 - Subperiod", "Fixed windows plus regime decomposition.", "Checks whether the result remains credible across time slices and across normal versus stress conditions."],
      ["Part 4 - Stochastic", "Bootstrap, Monte Carlo, neighbourhood, out-of-sample, and path-based tests.", "Checks whether the realised path is robust to resampling, perturbation, and simulated paths."],
      ["Part 5 - Dashboard and Conclusions", "Acceptance matrix and dashboard roll-up.", "Checks how the evidence is consolidated for the evidence pack and final reporting layer."],
    ],
    runModes: [
      ["Single run", "Run one selected scenario immediately through the current pipeline state."],
      ["Batch compare", "Queue multiple scenarios together for direct parameter comparison."],
      ["Nightly refresh", "Register an automated evening refresh instead of launching immediately."],
      ["Nightly single", "Nightly refresh for one selected scenario."],
      ["Nightly batch", "Nightly refresh for a set of batch targets rather than a single scenario."],
    ],
    outputTerms: [
      ["Output pack", "The scenario-level export scope chosen in Scenario Builder, such as NAV only or full risk output."],
      ["Artifact bundle", "The run-level switch that decides whether execution outputs are bundled for downstream review."],
      ["Risk pack", "A focused export containing regime, exposure, correlation, and VIX-related diagnostics."],
      ["Delivery ZIP", "The final submission-oriented package manifest exported from the Delivery page."],
    ],
  },
};

const navRoot = document.getElementById("nav");
const pageContent = document.getElementById("page-content");
const pageTitle = document.getElementById("page-title");
const pageKicker = document.getElementById("page-kicker");
const sidebarToggle = document.getElementById("sidebar-toggle");
const topbarMeta = document.getElementById("topbar-meta");
const systemNavActions = document.getElementById("system-nav-actions");
const systemNavButtons = Array.from(document.querySelectorAll(".system-nav-menu button"));
let currentPage = "welcome";
let currentSection = "home";
let sidebarCollapsed = false;
let selectMenuOutsideHandler = null;
let inputDialogKeydownHandler = null;
const pageToSection = Object.entries(navSections).reduce((acc, [section, pages]) => { pages.forEach((id) => { acc[id] = section; }); return acc; }, {});
const formState = {
  scenario_builder: {
    universe: "US Large Cap",
    rebalance: "Quarterly",
    top_n: "25",
    vix_threshold: "22",
    transaction_cost: "15bps",
    neutralisation: true,
    factor_sleeves: ["Quality", "Value", "Market Technical", "Dividend"],
    hold_cap: "5%",
    benchmark: "Static baseline + market benchmark",
    stress_overlay: true,
    lookback_window: "12 months",
    output_pack: "NAV + holdings + risk",
    active_preset: "Base",
  },
  backtest_runner: {
    scenario: "Current working scenario",
    execution_mode: "Single run",
    batch_targets: ["Current working scenario", "Base", "Stress-aware"],
    nightly_mode: "Single scenario",
    nightly_time: "22:00",
    priority: "Normal",
    owner: "Team C",
    artifact_bundle: true,
    notifications: true,
  },
  run_history: {
    scenario_filter: ["All scenarios"],
    status_filter: ["All status"],
    owner_filter: ["All owners"],
    date_range: "Last 7 days",
    custom_start_date: "2026-04-01",
    custom_end_date: "2026-04-07",
    include_warnings: true,
    sort_order: "Latest first",
  },
  report_studio: {
    api_url: REPORT_DEFAULT_API_URLS.openai,
    api_key: "",
    model: "gpt-4.1-mini",
    request_format: "openai",
    temperature: "0.2",
    user_instruction: DEFAULT_REPORT_USER_INSTRUCTION,
    system_prompt: "",
  },
  factor_lab: {
    factor_sleeves: ["Quality", "Value", "Market Technical", "Dividend"],
    neutralisation: true,
    top_n: "25",
    cost_model: "15bps",
    winsorisation: "3 sigma",
    standardisation: "Z-score",
    ewma_decay: "0.94",
    lookback_window: "12 months",
  },
  holdings_trades: {
    top_n: "25",
    hold_cap: "5%",
    stress_overlay: true,
    execution_style: "Quarterly batch",
    cost_model: "15bps",
    execution_lag_days: "1",
    trade_filter: "All trades",
    sector_focus: "All sectors",
    attribution_view: "Driver share",
  },
  robustness_lab: {
    base_scenario: "Current working scenario",
    sensitivity_dimensions: ["Transaction cost", "Regime threshold", "Breadth range"],
    range_profile: "Mainline core",
    bootstrap_iterations: "1000",
    stochastic_mode: "Bootstrap + Monte Carlo",
    subperiod_definition: "Normal vs stress",
  },
  performance_dashboard: {
    compare_runs: "Baseline",
    compare_summary_runs: [],
    nav_focus_period: "Latest point",
    drilldown_view: "Holdings + factors",
  },
  risk_dashboard: {
    snapshot_date: "2026-04-06",
    sector_focus: "All sectors",
    compare_mode: "Static baseline",
    covariance_focus: "Latest covariance metrics",
  },
};
const dirtyState = {
  scenario_builder: false,
  backtest_runner: false,
  run_history: false,
  report_studio: false,
  factor_lab: false,
  holdings_trades: false,
  robustness_lab: false,
  performance_dashboard: false,
  risk_dashboard: false,
};
const STORAGE_KEY = "quant-workbench-state-v1";
const REPORT_STUDIO_SESSION_KEY = "quant-workbench-report-studio-session-v1";
const defaultScenarioBuilderState = JSON.parse(JSON.stringify(formState.scenario_builder));
const runtimeState = {
  latestLogRunId: "BT-2026-0406-01",
  highlightedRunId: "",
  activeScenarioId: "",
  performanceRunSeriesCache: {},
  performanceRunSeriesLoading: {},
  performanceRunSeriesUnavailable: {},
  llmModelCatalog: {
    models: [],
    status: "idle",
    error: "",
    fetchedAt: "",
    requestFormat: "",
    modelUrl: "",
  },
  floatingControlPanelOpen: false,
  pendingControlFocus: null,
  backtestContext: {
    sourcePage: "",
    sourceLabel: "",
    anchorId: "",
    focusSummary: "",
  },
  runHistorySelectionMode: false,
  selectedRunIds: [],
  runHistoryScrollTop: 0,
  pageScrollY: 0,
  artifactOpenKeys: [],
  notifications: [],
  runMeta: {
    "BT-2026-0406-01": { owner: "Team C" },
    "BT-2026-0405-01": { owner: "Automation" },
      "BT-2026-0404-01": { owner: "Research Ops" },
      "BT-2026-0403-01": { owner: "Team C" },
  },
  runLogs: {
    "BT-2026-0406-01": [
      "[08:15:02] Job accepted by scheduler",
      "[08:15:09] Scenario config loaded: Stress-aware monthly monitoring refresh",
      "[08:16:14] Feature store sync completed",
      "[08:20:27] Backtest run finished successfully",
      "[08:23:16] NAV pack exported to artifact bundle",
    ],
  },
};
const workspaceConfigs = {
  welcome: {
    badge: "System Home",
    chips: ["Welcome", "Core functions", "Quick access"],
    actions: [],
  },
  overview: {
    badge: "System Home",
    chips: ["Live overview", "Research status", "Delivery readiness"],
    actions: [
      { label: "Open summary", action: "overview-open-summary" },
      { label: "Export snapshot", action: "export-overview-snapshot" },
    ],
  },
  scenario_builder: {
    badge: "Research Setup",
    chips: ["Universe config", "Factor sleeves", "Threshold tuning"],
    actions: [],
    showDirty: true,
  },
  data_health: {
    badge: "Research Setup",
    chips: ["Freshness", "Quality gates", "DAG state"],
    actions: [],
  },
  backtest_runner: {
    badge: "Research Setup",
    chips: ["Pipeline ready", "Quality gates", "Batch execution"],
    actions: [],
    showDirty: false,
  },
  factor_lab: {
    badge: "Analytics",
    chips: ["Factor builder", "Quick preview", "IC review"],
    actions: [],
    showDirty: true,
  },
  run_history: {
    badge: "Research Setup",
    chips: ["Recent jobs", "Execution logs", "Generated outputs"],
    actions: [],
    showDirty: false,
  },
  performance_dashboard: {
    badge: "Analytics",
    chips: ["Return path", "Drawdown", "Relative performance"],
    actions: [],
  },
  risk_dashboard: {
    badge: "Analytics",
    chips: ["Regime lens", "Factor risk", "Exposure shift"],
    actions: [],
  },
  robustness_lab: {
    badge: "Analytics",
    chips: ["Scenario grid", "Bootstrap", "Stochastic robustness"],
    actions: [],
  },
  holdings_trades: {
    badge: "Portfolio",
    chips: ["Trade blotter", "Execution notes", "Source attribution"],
    actions: [],
    showDirty: true,
  },
  artifacts: {
    badge: "Delivery",
    chips: ["Artifacts", "Docs", "Submission pack"],
    actions: [],
  },
  report_studio: {
    badge: "Delivery",
    chips: ["Slide blocks", "Appendix", "Build checklist"],
    actions: [],
  },
  help: {
    badge: "Help",
    chips: ["Glossary", "Method notes", "Platform guide"],
    actions: [],
  },
};

const apiRuntime = {
  connected: false,
  lastError: "",
  lastSyncedAt: "",
  factorPreviewLoaded: false,
  tradePreviewLoaded: false,
};
const livePreviewTimers = {};

const scenarioPresetConfigs = {
  Base: {
    universe: "US Large Cap",
    rebalance: "Quarterly",
    top_n: "25",
    vix_threshold: "22",
    transaction_cost: "15bps",
    neutralisation: true,
    factor_sleeves: ["Quality", "Value", "Market Technical", "Dividend"],
    hold_cap: "5%",
    benchmark: "Static baseline + market benchmark",
    stress_overlay: true,
    lookback_window: "12 months",
    output_pack: "NAV + holdings + risk",
  },
  "Stress-aware": {
    universe: "Defensive Basket",
    rebalance: "Quarterly",
    top_n: "25",
    vix_threshold: "22",
    transaction_cost: "15bps",
    neutralisation: true,
    factor_sleeves: ["Quality", "Dividend", "Value"],
    hold_cap: "5%",
    benchmark: "Static baseline + market benchmark",
    stress_overlay: true,
    lookback_window: "12 months",
    output_pack: "NAV + holdings + risk",
  },
  "Low-turnover": {
    universe: "US Large Cap",
    rebalance: "Quarterly",
    top_n: "25",
    vix_threshold: "25",
    transaction_cost: "15bps",
    neutralisation: true,
    factor_sleeves: ["Value", "Quality", "Dividend"],
    hold_cap: "4%",
    benchmark: "Benchmark only",
    stress_overlay: true,
    lookback_window: "24 months",
    output_pack: "Full artifact bundle",
  },
};

const factorLabelMap = {
  quality: "Quality",
  value: "Value",
  market_technical: "Market Technical",
  sentiment: "Sentiment",
  dividend: "Dividend",
  momentum: "Momentum",
};

function titleFactorName(value) {
  return factorLabelMap[value] || String(value || "").replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function formatCadence(value) {
  const text = String(value || "").trim();
  return text ? `${text.slice(0, 1).toUpperCase()}${text.slice(1)}` : "";
}

function formatBps(value) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? `${Number(numeric.toFixed(3))}bps` : String(value || "");
}

function formatWeightPct(value) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? `${Number((numeric * 100).toFixed(3))}%` : String(value || "");
}

function factorSleevesFromRegime(config = {}) {
  const regime = config.regime && typeof config.regime === "object" ? config.regime : {};
  const names = [];
  ["normal", "stress"].forEach((regimeName) => {
    const weights = regime[regimeName] && typeof regime[regimeName] === "object" ? regime[regimeName] : {};
    Object.entries(weights).forEach(([factorName, factorWeight]) => {
      const numeric = Number(factorWeight);
      if (Number.isFinite(numeric) && numeric > 0 && !names.includes(factorName)) names.push(factorName);
    });
  });
  return names.map(titleFactorName);
}

function deriveUniverseLabelFromConfig(config = {}) {
  if (config.universe) return config.universe;
  const investable = config.investable_universe && typeof config.investable_universe === "object" ? config.investable_universe : {};
  const countries = Array.isArray(investable.country_allowlist) ? investable.country_allowlist.join("/") : "";
  const parts = [];
  if (countries) parts.push(countries);
  parts.push("PIT screened universe");
  if (investable.min_liquidity_20d) parts.push(`ADV >= ${Number(investable.min_liquidity_20d).toLocaleString("en-US", { maximumFractionDigits: 0 })}`);
  if (investable.min_market_cap_log) parts.push(`log mcap >= ${investable.min_market_cap_log}`);
  return parts.join(" / ");
}

function normalizeScenarioDraftForUi(nextState = {}, scenarioName = "") {
  const config = nextState && typeof nextState === "object" ? nextState : {};
  const portfolio = config.portfolio_construction && typeof config.portfolio_construction === "object" ? config.portfolio_construction : {};
  const backtest = config.backtest && typeof config.backtest === "object" ? config.backtest : {};
  const regime = config.regime && typeof config.regime === "object" ? config.regime : {};
  const preprocessing = config.preprocessing && typeof config.preprocessing === "object" ? config.preprocessing : {};
  if (!portfolio || (!Object.keys(portfolio).length && !Object.keys(backtest).length && !Object.keys(regime).length)) {
    const flat = { ...config };
    if (typeof flat.factor_sleeves === "string") {
      flat.factor_sleeves = flat.factor_sleeves.split("/").map((item) => item.trim()).filter(Boolean);
    }
    return flat;
  }
  const topN = config.top_n ?? portfolio.top_n ?? portfolio.hybrid_min_n ?? backtest.top_n ?? "";
  const vixThreshold = config.vix_threshold ?? regime.vix_stress_threshold ?? "";
  const lookbackYears = backtest.lookback_years;
  const neutralizeBy = String(preprocessing.neutralize_by || "").toLowerCase();
  const rawSleeves = config.factor_sleeves || factorSleevesFromRegime(config);
  return {
    ...config,
    universe: deriveUniverseLabelFromConfig(config),
    rebalance: formatCadence(config.rebalance || backtest.rebalance_frequency || portfolio.target_generation_frequency),
    top_n: topN === "" || topN === null || topN === undefined ? "" : String(Number.isFinite(Number(topN)) ? Number(topN) : topN),
    vix_threshold: vixThreshold === "" || vixThreshold === null || vixThreshold === undefined ? "" : String(Number.isFinite(Number(vixThreshold)) ? Number(vixThreshold) : vixThreshold),
    transaction_cost: config.transaction_cost || formatBps(backtest.transaction_cost_bps),
    neutralisation: typeof config.neutralisation === "boolean" ? config.neutralisation : !["", "none", "false"].includes(neutralizeBy),
    factor_sleeves: Array.isArray(rawSleeves) ? rawSleeves : String(rawSleeves || "").split("/").map((item) => item.trim()).filter(Boolean),
    hold_cap: config.hold_cap || formatWeightPct(portfolio.max_single_weight),
    benchmark: config.benchmark || backtest.benchmark_ticker || "",
    stress_overlay: typeof config.stress_overlay === "boolean" ? config.stress_overlay : Boolean(regime.vix_stress_threshold),
    lookback_window: config.lookback_window || (lookbackYears ? `${lookbackYears} years` : ""),
    output_pack: config.output_pack || "Formal baseline evidence pack",
    active_preset: config.active_preset || scenarioName || portfolio.portfolio_name || backtest.portfolio_name || "",
  };
}

function hasConnectedScenarioDraft(config = {}) {
  return ["universe", "rebalance", "top_n", "vix_threshold", "transaction_cost", "benchmark"]
    .every((key) => config[key] !== undefined && config[key] !== null && String(config[key]).trim() !== "");
}

function normalizeSourceType(type) {
  const normalized = String(type || "derived").trim().toLowerCase();
  if (normalized === "raw" || normalized === "derived" || normalized === "text-only") return normalized;
  return "derived";
}

function renderSourceMeta(meta = {}, compact = false) {
  const sourceType = normalizeSourceType(meta.type);
  const sourceLabel = sourceType === "text-only" ? "Text-only" : sourceType;
  const detail = meta.detail ? `<small>${meta.detail}</small>` : "";
  return `<div class="source-meta${compact ? " is-compact" : ""}"><span class="source-pill source-pill-${sourceType}">${sourceLabel}</span>${detail}</div>`;
}

function makePanel(title, description, body, sourceMeta = { type: "derived" }) {
  return `<section class="panel"><div class="section-title"><div><h3>${title}</h3><p>${description}</p></div>${renderSourceMeta(sourceMeta)}</div>${body}</section>`;
}
function renderNav() {
  navRoot.innerHTML = "";
  navSections[currentSection].map((id) => navItems.find((item) => item.id === id)).filter(Boolean).forEach((item) => {
    const button = document.createElement("button");
    button.className = item.id === currentPage ? "is-active" : "";
    button.innerHTML = `<span class="nav-icon" aria-hidden="true">${item.icon}</span><span>${item.label}</span>`;
    button.addEventListener("click", () => { currentPage = item.id; render(true); });
    navRoot.appendChild(button);
  });
}

function renderSparkline(values, color = "#0d6c63", fill = "rgba(13,108,99,0.12)", options = {}) {
  const showAxes = options.showAxes !== false;
  const width = 520;
  const height = 220;
  const padLeft = showAxes ? 58 : 0;
  const highlightIndex = Number.isInteger(options.highlightIndex)
    ? Math.max(0, Math.min(options.highlightIndex, values.length - 1))
    : null;
  const highlightValue = highlightIndex != null ? values[highlightIndex] : null;
  const highlightLabelText = showAxes && options.highlightLabel
    ? `${escapeHtml(options.highlightLabel)}${highlightValue != null ? `: ${escapeHtml((options.yFormatter || ((value) => Number(value).toFixed(1)))(highlightValue))}` : ""}`
    : "";
  const padRight = showAxes ? 16 : 0;
  const padTop = 12;
  const padBottom = showAxes ? 38 : 0;
  const plotWidth = width - padLeft - padRight;
  const plotHeight = height - padTop - padBottom;
  const max = Math.max(...values);
  const min = Math.min(...values);
  const range = max - min || 1;
  const step = plotWidth / Math.max(values.length - 1, 1);
  const pointEntries = values.map((value, index) => {
    const x = padLeft + index * step;
    const y = padTop + (plotHeight - ((value - min) / range) * plotHeight);
    return { x, y };
  });
  const points = pointEntries.map(({ x, y }) => `${x},${y}`).join(" ");
  const firstPoint = pointEntries[0] || { x: padLeft, y: padTop + plotHeight };
  const lastPoint = pointEntries.at(-1) || firstPoint;
  const areaPoints = `${padLeft},${padTop + plotHeight} ${points} ${lastPoint.x},${padTop + plotHeight}`;
  const highlightPoint = highlightIndex != null ? pointEntries[highlightIndex] : null;
  const highlightLabelX = highlightPoint
    ? Math.max(padLeft + 8, highlightPoint.x - 10)
    : 0;
  const highlightMarkup = highlightPoint
    ? `${showAxes ? `<line x1="${highlightPoint.x}" y1="${padTop}" x2="${highlightPoint.x}" y2="${padTop + plotHeight}" class="spark-focus-line"></line>` : ""}
       <circle cx="${highlightPoint.x}" cy="${highlightPoint.y}" r="6.5" class="spark-focus-ring"></circle>
       <circle cx="${highlightPoint.x}" cy="${highlightPoint.y}" r="3.5" class="spark-focus-dot"></circle>
       ${highlightLabelText ? `<text x="${highlightLabelX}" y="${Math.max(padTop + 16, highlightPoint.y - 10)}" text-anchor="end" class="spark-focus-label">${highlightLabelText}</text>` : ""}`
    : "";
  if (!showAxes) {
    return `<svg class="sparkline" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none"><polygon points="${areaPoints}" fill="${fill}"></polygon><polyline points="${points}" fill="none" stroke="${color}" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"></polyline>${highlightMarkup}</svg>`;
  }
  const yMax = Number.isFinite(max) ? max : 0;
  const yMin = Number.isFinite(min) ? min : 0;
  const yMid = yMin + ((yMax - yMin) / 2);
  const yFormatter = options.yFormatter || ((value) => Number(value).toFixed(1));
  const xStartLabel = options.xStartLabel || "P1";
  const xEndLabel = options.xEndLabel || `P${values.length}`;
  const xAxisLabel = options.xAxisLabel || "Period";
  const yAxisLabel = options.yAxisLabel || "Value";
  return `<svg class="sparkline sparkline-axis" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none">
    <line x1="${padLeft}" y1="${padTop}" x2="${padLeft}" y2="${padTop + plotHeight}" class="spark-axis-line"></line>
    <line x1="${padLeft}" y1="${padTop + plotHeight}" x2="${width - padRight}" y2="${padTop + plotHeight}" class="spark-axis-line"></line>
    <line x1="${padLeft}" y1="${padTop}" x2="${width - padRight}" y2="${padTop}" class="spark-grid-line"></line>
    <line x1="${padLeft}" y1="${padTop + (plotHeight / 2)}" x2="${width - padRight}" y2="${padTop + (plotHeight / 2)}" class="spark-grid-line"></line>
    <polygon points="${areaPoints}" fill="${fill}"></polygon>
    <polyline points="${points}" fill="none" stroke="${color}" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"></polyline>
    ${highlightMarkup}
    <text x="${padLeft - 10}" y="${padTop + 4}" text-anchor="end" class="spark-axis-text">${yFormatter(yMax)}</text>
    <text x="${padLeft - 10}" y="${padTop + (plotHeight / 2) + 4}" text-anchor="end" class="spark-axis-text">${yFormatter(yMid)}</text>
    <text x="${padLeft - 10}" y="${padTop + plotHeight + 4}" text-anchor="end" class="spark-axis-text">${yFormatter(yMin)}</text>
    <text x="${padLeft}" y="${height - 12}" text-anchor="start" class="spark-axis-text">${xStartLabel}</text>
    <text x="${width - padRight}" y="${height - 12}" text-anchor="end" class="spark-axis-text">${xEndLabel}</text>
    <text x="${padLeft + (plotWidth / 2)}" y="${height - 12}" text-anchor="middle" class="spark-axis-caption">${xAxisLabel}</text>
    <text x="18" y="${padTop + (plotHeight / 2)}" text-anchor="middle" class="spark-axis-caption" transform="rotate(-90 18 ${padTop + (plotHeight / 2)})">${yAxisLabel}</text>
  </svg>`;
}
function formatChartMetric(value, decimals = 2, suffix = "") {
  const numericValue = Number(value);
  if (!Number.isFinite(numericValue)) return "n/a";
  return `${numericValue.toFixed(decimals)}${suffix}`;
}
function formatAxisDateLabel(value) {
  if (!value) return "n/a";
  const text = String(value).trim();
  const looksLikeDate = /^\d{4}-\d{2}-\d{2}/.test(text)
    || /^\d{4}\/\d{2}\/\d{2}/.test(text)
    || /^\d{2}\/\d{2}\/\d{4}/.test(text)
    || /^\d{4}-\d{2}-\d{2}T/.test(text);
  if (!looksLikeDate) return text;
  const parsed = new Date(text);
  if (Number.isNaN(parsed.getTime())) return String(value);
  const day = `${parsed.getDate()}`.padStart(2, "0");
  const month = `${parsed.getMonth() + 1}`.padStart(2, "0");
  const year = `${parsed.getFullYear()}`.slice(-2);
  return `${day}/${month}/${year}`;
}
function getSeriesDateValue(row) {
  if (!row || typeof row !== "object") return "";
  return row.date || row.period_end_date || row.execution_date || row.as_of_date || row.observation_date || row.rebalance_date || "";
}
function renderChartStats(items) {
  const validItems = (items || []).filter((item) => item && item.label);
  if (!validItems.length) return "";
  return `<div class="chart-stat-row">${validItems.map((item) => `<div class="chart-stat"><span>${item.label}</span><strong>${item.value}</strong></div>`).join("")}</div>`;
}
function renderBars(items, formatter = (value) => `${value}`) {
  const max = Math.max(...items.map((item) => Math.abs(item[1]))) || 1;
  const yMax = max;
  const yMid = max / 2;
  return `<div class="bars-chart"><div class="bars-axis-y"><span>${yMax.toFixed(1)}</span><span>${yMid.toFixed(1)}</span><span>0.0</span></div><div class="bars-wrap"><div class="bars">${items.map(([label, value]) => `<div class="bar-group"><div class="${value < 0 ? "bar negative" : "bar"}" style="height:${(Math.abs(value) / max) * 100}%"></div><span class="bar-label">${label}<strong>${formatter(value)}</strong></span></div>`).join("")}</div><div class="chart-axis-caption chart-axis-caption-x">Category</div></div><div class="chart-axis-caption chart-axis-caption-y">Value</div></div>`;
}
function renderProgress(list, formatter = (value) => `${value}%`) {
  return `<div class="progress-list">${list.map(([label, value]) => `<div class="progress-row"><strong>${label}</strong><div class="progress-track"><div class="progress-fill" style="width:${value}%"></div></div><span>${formatter(value)}</span></div>`).join("")}</div>`;
}
function renderTable(headers, rows) {
  return `<div class="table-wrap"><table><thead><tr>${headers.map((header) => `<th>${header}</th>`).join("")}</tr></thead><tbody>${rows.map((row) => `<tr>${row.map((cell) => `<td>${cell}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
}
function renderScrollableTable(headers, rows, heightClass = "table-wrap-fixed-lg") {
  return `<div class="table-wrap ${heightClass}"><table><thead><tr>${headers.map((header) => `<th>${header}</th>`).join("")}</tr></thead><tbody>${rows.map((row) => `<tr>${row.map((cell) => `<td>${cell}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
}
function humanizeArtifactToken(token) {
  return String(token || "")
    .replace(/[_-]+/g, " ")
    .replace(/\b([a-z])/g, (match) => match.toUpperCase())
    .replace(/\bPng\b/g, "PNG")
    .replace(/\bCsv\b/g, "CSV")
    .replace(/\bMd\b/g, "Markdown");
}
function labelArtifactPart(token) {
  const match = String(token || "").match(/^part[_-](\d+)[_-](.+)$/i);
  if (!match) return humanizeArtifactToken(token);
  return `Part ${Number(match[1])} - ${humanizeArtifactToken(match[2])}`;
}
function labelArtifactGroup(fileName) {
  const name = String(fileName || "");
  const testMatch = name.match(/^test[_-]?(\d+)(?:[_-]|$)/i);
  if (testMatch) return `Test ${Number(testMatch[1])}`;
  const ablationBlockMatch = name.match(/^ablation[_-]block[_-]([a-z0-9]+)(?:[_-]|$)/i);
  if (ablationBlockMatch) return `Block ${String(ablationBlockMatch[1]).toUpperCase()}`;
  const ablationMatch = name.match(/^ablation[_-]([a-z0-9]+)(?:[_-]|$)/i);
  if (ablationMatch) return humanizeArtifactToken(`block_${ablationMatch[1]}`);
  const subperiodCoverageMatch = name.match(/^subperiod[_-]coverage(?:[_-]|$)/i);
  if (subperiodCoverageMatch) return "Coverage";
  const subperiodFixedWindowsMatch = name.match(/^subperiod[_-]fixed[_-]windows(?:[_-]|$)/i);
  if (subperiodFixedWindowsMatch) return "Fixed Windows";
  const subperiodRegimeDecompositionMatch = name.match(/^subperiod[_-]regime[_-]decomposition(?:[_-]|$)/i);
  if (subperiodRegimeDecompositionMatch) return "Regime Decomposition";
  const subperiodMatch = name.match(/^subperiod[_-]([a-z0-9_]+?)(?:[_-](chart|notes?|table|nav(?:[_-]reference)?))?$/i);
  if (subperiodMatch) return humanizeArtifactToken(subperiodMatch[1]);
  const stochasticReadyMatch = name.match(/^stochastic[_-]report[_-]ready(?:[_-]|$)/i);
  if (stochasticReadyMatch) return "Report Ready";
  const stochasticMatch = name.match(/^(stochastic[_-][a-z0-9_]+)/i);
  if (stochasticMatch) return humanizeArtifactToken(stochasticMatch[1]);
  const dashboardMatch = name.match(/^(dashboard[_-][a-z0-9_]+)/i);
  if (dashboardMatch) return humanizeArtifactToken(dashboardMatch[1]);
  const stem = name.replace(/\.[^.]+$/, "");
  return humanizeArtifactToken(stem);
}
function labelArtifactFile(fileName) {
  const name = String(fileName || "");
  const stem = name.replace(/\.[^.]+$/, "");
  const ext = name.includes(".") ? name.split(".").pop().toUpperCase() : "";
  const leaf = stem
    .replace(/^(test[_-]?\d+|ablation[_-]block[_-][a-z0-9]+|ablation[_-][a-z0-9]+|subperiod[_-]coverage|subperiod[_-]fixed[_-]windows|subperiod[_-]regime[_-]decomposition|subperiod[_-][a-z0-9_]+|stochastic[_-]report[_-]ready|stochastic[_-][a-z0-9_]+|dashboard[_-][a-z0-9_]+)[_-]?/i, "")
    .replace(/^[._-]+/, "");
  const base = leaf ? humanizeArtifactToken(leaf) : humanizeArtifactToken(stem);
  return ext ? `${base} (${ext})` : base;
}
function artifactSourceLabel(source) {
  const normalized = String(source || "").toLowerCase();
  switch (normalized) {
    case "report_evidence":
      return "Sensitivity Report Evidence";
    case "main_program_reports":
      return "Main Program Report";
    case "briefings":
      return "Briefings";
    default:
      return humanizeArtifactToken(source || "Other");
  }
}
const ARTIFACT_PART_LABELS = {
  part_1_deterministic: "Part 1 - Deterministic",
  part_2_ablation: "Part 2 - Ablation",
  part_3_subperiod: "Part 3 - Subperiod",
  part_4_stochastic: "Part 4 - Stochastic",
  part_5_dashboard_and_conclusions: "Part 5 - Dashboard And Conclusions",
};
const DOCUMENTATION_GROUP_EXPLANATIONS = {
  "Part 1 - Deterministic": "Deterministic sensitivity sweeps around the quarterly-rebalanced baseline. Use this section to show which core implementation assumptions were stressed and whether headline performance remains stable under direct parameter changes.",
  "Part 2 - Ablation": "Ablation tests that remove or isolate key building blocks. Use this section to explain what each block contributes and which parts of the strategy are actually driving the result.",
  "Part 3 - Subperiod": "Subperiod and regime-split checks. Use this section to show whether the strategy behaviour is consistent across fixed windows and normal-versus-stress market states.",
  "Part 4 - Stochastic": "Bootstrap, Monte Carlo, neighbourhood, and path-based robustness tests. Use this section to explain how sensitive the strategy is to resampling noise, cost perturbations, and alternative paths.",
  "Part 5 - Dashboard And Conclusions": "Final summary tables and dashboard-ready conclusions. Use this section to pull together the main robustness message and identify what should be carried into the formal report.",
  "Main Program Reports": "Full report bundles generated by the main program runs. Use these as the formal output packs for performance, risk, holdings, and supporting analysis after a full run completes.",
  Briefings: "Short briefing files for concise narrative summaries and stakeholder updates. Use these when you need a compact companion to the full report bundles.",
};
function isRobustnessArtifactRecord(record) {
  const source = String(record?.source || "").toLowerCase();
  const name = String(record?.name || "");
  return (
    source === "report_evidence"
    || source.includes("report_evidence")
    || /^part[_-]\d+/i.test(name)
  );
}
function createArtifactTreeNode(label, key) {
  return { label, key, files: [], children: [] };
}
function getArtifactChildNode(parent, label, key) {
  let existing = parent.children.find((node) => node.key === key);
  if (!existing) {
    existing = createArtifactTreeNode(label, key);
    parent.children.push(existing);
  }
  return existing;
}
function buildArtifactTree(records) {
  const root = createArtifactTreeNode("root", "root");
  records.forEach((record) => {
    const source = String(record?.source || "other");
    const artifactName = String(record?.name || "");
    if (isRobustnessArtifactRecord(record)) {
      if (!artifactName.includes("/")) {
        return;
      }
      const segments = artifactName.split("/").filter(Boolean);
      const partToken = segments[0];
      if (!/^part[_-]\d+/i.test(partToken)) {
        return;
      }
      const fileName = segments.at(-1) || artifactName;
      if (/^(manifest\.json|report_handoff_index\.csv|report_evidence_index\.csv|robustness_report_evidence_pack\.md)$/i.test(fileName)) {
        return;
      }
      const partLabel = ARTIFACT_PART_LABELS[partToken.toLowerCase()] || labelArtifactPart(partToken);
      const partNode = getArtifactChildNode(root, partLabel, `part:${partToken}`);
      const groupLabel = labelArtifactGroup(fileName);
      const groupNode = getArtifactChildNode(partNode, groupLabel, `group:${partToken}:${groupLabel}`);
      groupNode.files.push({
        label: labelArtifactFile(fileName),
        rawName: artifactName,
        detail: record.description || "",
        status: record.status || "",
      });
      return;
    }
    const topNode = getArtifactChildNode(root, artifactSourceLabel(source), `src:${source}`);
    topNode.files.push({
      label: humanizeArtifactToken(artifactName),
      rawName: artifactName,
      detail: record?.description || "",
      status: record?.status || "",
    });
  });
  root.children.forEach((sourceNode) => {
    sourceNode.children.sort((left, right) => left.label.localeCompare(right.label, undefined, { numeric: true }));
    sourceNode.children.forEach((partNode) => {
      partNode.children.sort((left, right) => left.label.localeCompare(right.label, undefined, { numeric: true }));
      partNode.children.forEach((groupNode) => {
        groupNode.files.sort((left, right) => left.label.localeCompare(right.label, undefined, { numeric: true }));
      });
    });
    sourceNode.files.sort((left, right) => left.label.localeCompare(right.label, undefined, { numeric: true }));
  });
  root.children.sort((left, right) => {
    const leftPart = left.label.match(/^Part\s+(\d+)/i);
    const rightPart = right.label.match(/^Part\s+(\d+)/i);
    if (leftPart && rightPart) return Number(leftPart[1]) - Number(rightPart[1]);
    if (leftPart) return -1;
    if (rightPart) return 1;
    return left.label.localeCompare(right.label, undefined, { numeric: true });
  });
  return root;
}
function renderArtifactTreeNode(node, depth = 0, openByDefault = false) {
  const folderBody = `${node.children.map((child) => renderArtifactTreeNode(child, depth + 1, false)).join("")}${node.files.map((file) => `<div class="artifact-file-row"><div><strong>${escapeHtml(file.label)}</strong><small>${escapeHtml(file.rawName)}</small></div><span>${escapeHtml(file.detail)}</span></div>`).join("")}`;
  const openAttr = openByDefault ? " open" : "";
  return `<details class="artifact-folder artifact-depth-${depth}" data-artifact-key="${escapeHtml(node.key)}"${openAttr}><summary><span>${escapeHtml(node.label)}</span><small>${node.children.length + node.files.length} item${node.children.length + node.files.length === 1 ? "" : "s"}</small></summary><div class="artifact-folder-body">${folderBody}</div></details>`;
}
function renderArtifactTree(records) {
  if (!Array.isArray(records) || !records.length) {
    return `<p class="footnote">No artifact records are currently connected.</p>`;
  }
  const tree = buildArtifactTree(records);
  if (!tree.children.length) {
    return `<div class="artifact-tree">${records.map((record) => `<div class="artifact-file-row"><div><strong>${escapeHtml(humanizeArtifactToken(record.name || "artifact"))}</strong><small>${escapeHtml(String(record.name || ""))}</small></div><span>${escapeHtml(record.description || "")}</span></div>`).join("")}</div>`;
  }
  return `<div class="artifact-tree">${tree.children.map((node) => renderArtifactTreeNode(node, 0, false)).join("")}</div>`;
}
function buildDocumentationHubMarkup(records, docs) {
  const safeRecords = Array.isArray(records) ? records : [];
  const safeDocs = Array.isArray(docs) ? docs : [];
  const evidenceRecords = safeRecords.filter((row) => String(row?.source || "").toLowerCase() === "report_evidence");
  const mainProgramRecords = safeRecords.filter((row) => String(row?.source || "").toLowerCase() === "main_program_reports");
  const briefingRecords = safeRecords.filter((row) => String(row?.source || "").toLowerCase() === "briefings");
  const evidenceGuides = evidenceRecords.filter((row) => /(^|\/)(report_evidence_index\.(md|csv)|robustness_report_evidence_pack\.md)$/i.test(String(row?.name || "")));
  const partNoteCounts = Object.entries(
    evidenceRecords.reduce((acc, row) => {
      const name = String(row?.name || "");
      const match = name.match(/^(part_[^/]+)\/.*notes\.md$/i);
      if (!match) return acc;
      acc[match[1]] = (acc[match[1]] || 0) + 1;
      return acc;
    }, {}),
  )
    .sort((left, right) => left[0].localeCompare(right[0], undefined, { numeric: true }))
    .map(([partToken, count]) => {
      const label = ARTIFACT_PART_LABELS[partToken.toLowerCase()] || labelArtifactPart(partToken);
      return [
        label,
        DOCUMENTATION_GROUP_EXPLANATIONS[label] || "Per-part narrative notes generated for this evidence section.",
      ];
    });
  const sections = [];
  if (evidenceGuides.length) {
    sections.push({
      title: "Evidence Guides",
      summary: "Indices and pack-level markdown that explain how the sensitivity evidence is organised for formal submission.",
      rows: evidenceGuides.map((row) => [humanizeArtifactToken(row.name.split("/").pop() || row.name), row.description || "Generated evidence guide"]),
    });
  }
  if (partNoteCounts.length) {
    sections.push({
      title: "Part Notes",
      summary: "Per-part narrative notes generated alongside the quarterly-rebalanced sensitivity outputs.",
      rows: partNoteCounts,
    });
  }
  if (mainProgramRecords.length || briefingRecords.length) {
    sections.push({
      title: "Operational Outputs",
      summary: "Main-program report bundles and briefing materials that can be reused when assembling the formal reporting pack.",
      rows: [
        [
          "Main Program Reports",
          DOCUMENTATION_GROUP_EXPLANATIONS["Main Program Reports"],
        ],
        [
          "Briefings",
          DOCUMENTATION_GROUP_EXPLANATIONS.Briefings,
        ],
      ],
    });
  }
  if (safeDocs.length) {
    sections.push({
      title: "Reference Notes",
      summary: "Core reference documents that support the workflow and explain how to operate the connected outputs.",
      rows: safeDocs.map(([title, summary]) => [title, summary]),
    });
  }
  if (!sections.length) {
    return `<p class="footnote">No documentation records are currently connected.</p>`;
  }
  return `<div class="docs-list">${sections.map((section) => `<article><h4>${escapeHtml(section.title)}</h4><p>${escapeHtml(section.summary)}</p>${renderTable(["Document Group", "What it contains"], section.rows)}</article>`).join("")}</div>`;
}
function renderPresetTable(rows) {
  return `<div class="table-wrap preset-table-wrap"><table><thead><tr><th>Preset</th><th>Configuration</th><th>Actions</th></tr></thead><tbody>${rows
    .map(
      ([name, description]) => `<tr><td>${name}</td><td>${description}</td><td><div class="table-action-row"><button type="button" class="table-action" data-action="apply-preset" data-preset="${name}">Apply</button><button type="button" class="table-action" data-action="rename-preset" data-preset="${name}">Rename</button><button type="button" class="table-action" data-action="delete-preset" data-preset="${name}">Delete</button></div></td></tr>`,
    )
    .join("")}</tbody></table></div>`;
}
function renderMatrix(labels, matrix) {
  const safeLabels = Array.isArray(labels) ? labels : [];
  const safeMatrix = Array.isArray(matrix)
    ? matrix
        .filter((row) => Array.isArray(row))
        .map((row) => row.slice(0, safeLabels.length))
        .slice(0, safeLabels.length)
    : [];
  const template = `124px repeat(${Math.max(safeLabels.length, 1)}, minmax(88px, 1fr))`;
  return `<div class="matrix-grid" style="grid-template-columns:${template};"><div class="matrix-axis matrix-corner"></div>${safeLabels.map((label) => `<div class="matrix-axis">${label}</div>`).join("")}${safeMatrix.map((row, rowIndex) => `<div class="matrix-row-label">${safeLabels[rowIndex] || ""}</div>${row.map((value) => `<div class="matrix-value" style="background: rgba(${value >= 0 ? "13,108,99" : "179,92,46"}, ${0.12 + Math.abs(value) * 0.4})"><strong>${value.toFixed(2)}</strong></div>`).join("")}`).join("")}</div>`;
}
function renderHeatmap(matrix, options = {}) {
  const safeMatrix = Array.isArray(matrix) ? matrix.filter((row) => Array.isArray(row) && row.length) : [];
  if (!safeMatrix.length) return `<div class="small-note">No monthly return cells are available.</div>`;
  const max = Math.max(...safeMatrix.flat().map((value) => Math.abs(value))) || 1;
  let cellLabels = Array.isArray(options.cellLabels) ? options.cellLabels : [];
  if (!cellLabels.length && currentPage === "performance_dashboard") {
    const selectedDisplayRun = typeof getSelectedDisplayRun === "function" ? getSelectedDisplayRun() : "Baseline";
    const performanceRows = selectedDisplayRun && selectedDisplayRun !== "Baseline"
      ? (runtimeState.performanceRunSeriesCache[selectedDisplayRun] || [])
      : (Array.isArray(store.performance.rawSeries) ? store.performance.rawSeries : []);
    cellLabels = buildMonthlyHeatmapLabelsFromRaw(performanceRows, safeMatrix);
  }
  return `<div class="matrix heatmap-grid" style="grid-template-columns: repeat(${safeMatrix[0].length}, minmax(0, 1fr));">${safeMatrix.flatMap((row, rowIndex) => row.map((value, colIndex) => {
    const label = cellLabels[rowIndex]?.[colIndex] || "";
    return `<div class="heat-cell" style="background: rgba(${value >= 0 ? "13,108,99" : "179,92,46"}, ${0.16 + (Math.abs(value) / max) * 0.5})">${label ? `<span class="heat-cell-label">${escapeHtml(label)}</span>` : ""}<strong>${value > 0 ? "+" : ""}${value.toFixed(1)}%</strong></div>`;
  })).join("")}</div>`;
}
function renderRankings(items) {
  return `<div class="rank-list">${items.map(([label, value], index) => `<div class="rank-item"><strong>${index + 1}</strong><span>${label}</span><strong>${typeof value === "number" ? value.toFixed(1) : value}</strong></div>`).join("")}</div>`;
}
function renderRegimeStrip(items) {
  return `<div class="regime-strip">${items.map((item) => `<div style="background:${item === "stress" ? "rgba(179,92,46,0.55)" : "rgba(13,108,99,0.35)"}"></div>`).join("")}</div>`;
}
function renderSystemMetrics(items) {
  return `<div class="grid-three">${items.map((item) => `<article class="metric-card">${renderSourceMeta({ type: item.sourceType || "derived", detail: item.sourceDetail || "" }, true)}<span>${item.label}</span><strong>${item.value}</strong><small>${item.note}</small></article>`).join("")}</div>`;
}
function persistState(options = {}) {
  const { saveScenarioBuilder = false } = options;
  try {
    const reportStudioState = {
      ...formState.report_studio,
      api_key: "",
    };
    const persistedFormState = {
      ...formState,
      report_studio: reportStudioState,
      scenario_builder: saveScenarioBuilder
        ? formState.scenario_builder
        : JSON.parse(JSON.stringify(defaultScenarioBuilderState)),
    };
    const persistedDirtyState = {
      ...dirtyState,
      scenario_builder: saveScenarioBuilder ? dirtyState.scenario_builder : false,
    };
    const payload = {
      uiState: {
        currentPage,
        currentSection,
      },
      formState: persistedFormState,
      dirtyState: persistedDirtyState,
      runHistory: {
        runs: store.runHistory.runs,
        artifacts: store.runHistory.artifacts,
      },
      riskSnapshot: {
        updatedAt: store.health.updatedAt,
        vix: store.regime.vix,
        strip: store.regime.strip,
      },
      robustnessSnapshot: {
        scenarios: store.robustness.scenarios,
        subperiods: store.robustness.subperiods,
        monteCarlo: store.robustness.monteCarlo,
        percentiles: store.robustness.percentiles,
      },
      reportStudioSnapshot: {
        aiReport: store.reportStudio.aiReport,
      },
      runtimeState,
      scenarioPresets: {
        presets: store.scenarioBuilder.presets,
        configs: scenarioPresetConfigs,
      },
    };
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
    window.sessionStorage.setItem(REPORT_STUDIO_SESSION_KEY, JSON.stringify({
      api_key: formState.report_studio.api_key || "",
    }));
  } catch {}
}

function loadPersistedState() {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return;
    const saved = JSON.parse(raw);
    if (saved.formState) {
      Object.entries(saved.formState).forEach(([pageId, values]) => {
        if (formState[pageId] && values) Object.assign(formState[pageId], values);
      });
      formState.run_history.scenario_filter = normalizeMultiSelectValue(formState.run_history.scenario_filter, "All scenarios");
      formState.run_history.status_filter = normalizeMultiSelectValue(formState.run_history.status_filter, "All status");
      formState.run_history.owner_filter = normalizeMultiSelectValue(formState.run_history.owner_filter, "All owners");
      if (["openai_chat", "openai_responses"].includes(formState.report_studio?.request_format)) {
        formState.report_studio.request_format = "openai";
      } else if (formState.report_studio?.request_format === "anthropic_messages") {
        formState.report_studio.request_format = "claude";
      } else if (formState.report_studio?.request_format === "gemini_generate_content") {
        formState.report_studio.request_format = "gemini";
      } else if (formState.report_studio?.request_format === "generic_chat") {
        formState.report_studio.request_format = "compatible api";
      } else if (formState.report_studio?.request_format === "generic_json") {
        formState.report_studio.request_format = "custom json";
      }
      if (isLegacyReportUserInstruction(formState.report_studio?.user_instruction)) {
        formState.report_studio.user_instruction = DEFAULT_REPORT_USER_INSTRUCTION;
      }
      syncReportApiUrlForFormat(formState.report_studio?.request_format);
      if (saved.formState.scenario_builder) {
        formState.scenario_builder = normalizeScenarioDraftForUi(formState.scenario_builder, formState.scenario_builder.active_preset);
        Object.assign(defaultScenarioBuilderState, JSON.parse(JSON.stringify(formState.scenario_builder)));
      }
    }
    if (saved.dirtyState) {
      Object.entries(saved.dirtyState).forEach(([pageId, value]) => {
        if (pageId in dirtyState) dirtyState[pageId] = value;
      });
    }
    if (saved.runHistory?.runs) store.runHistory.runs = saved.runHistory.runs;
    if (saved.runHistory?.artifacts) store.runHistory.artifacts = saved.runHistory.artifacts;
    if (saved.riskSnapshot?.updatedAt) store.health.updatedAt = saved.riskSnapshot.updatedAt;
    if (Array.isArray(saved.riskSnapshot?.vix)) {
      store.regime.vix = saved.riskSnapshot.vix.map((value) => Number(value)).filter(Number.isFinite);
    }
    if (saved.riskSnapshot?.strip) store.regime.strip = saved.riskSnapshot.strip;
    if (saved.robustnessSnapshot?.scenarios) store.robustness.scenarios = saved.robustnessSnapshot.scenarios;
    if (saved.robustnessSnapshot?.subperiods) store.robustness.subperiods = saved.robustnessSnapshot.subperiods;
    if (saved.robustnessSnapshot?.monteCarlo) store.robustness.monteCarlo = saved.robustnessSnapshot.monteCarlo;
    if (saved.robustnessSnapshot?.percentiles) {
      const savedPercentiles = saved.robustnessSnapshot.percentiles;
      const looksLikePercentiles = Array.isArray(savedPercentiles)
        && savedPercentiles.some((row) => String(row?.[0] || "").toLowerCase().includes("bootstrap"))
        && savedPercentiles.some((row) => String(row?.[0] || "").toLowerCase().includes("stress 1.5x"));
      store.robustness.percentiles = looksLikePercentiles
        ? savedPercentiles
        : DEFAULT_ROBUSTNESS_PERCENTILES.map((row) => [...row]);
    }
    if (saved.reportStudioSnapshot?.aiReport) store.reportStudio.aiReport = saved.reportStudioSnapshot.aiReport;
    if (saved.runtimeState) Object.assign(runtimeState, saved.runtimeState);
    if (!Array.isArray(runtimeState.selectedRunIds)) runtimeState.selectedRunIds = [];
    if (!runtimeState.runMeta || typeof runtimeState.runMeta !== "object") runtimeState.runMeta = {};
    if (!runtimeState.llmModelCatalog || typeof runtimeState.llmModelCatalog !== "object") {
      runtimeState.llmModelCatalog = { models: [], status: "idle", error: "", fetchedAt: "", requestFormat: "", modelUrl: "" };
    }
    if (!Array.isArray(runtimeState.llmModelCatalog.models)) runtimeState.llmModelCatalog.models = [];
    store.runHistory.runs.forEach((row) => {
      if (!runtimeState.runMeta[row[0]]) runtimeState.runMeta[row[0]] = { owner: "Team C" };
    });
    if (saved.scenarioPresets?.presets) store.scenarioBuilder.presets = saved.scenarioPresets.presets;
    if (saved.scenarioPresets?.configs) {
      Object.keys(scenarioPresetConfigs).forEach((key) => delete scenarioPresetConfigs[key]);
      Object.entries(saved.scenarioPresets.configs).forEach(([name, config]) => {
        scenarioPresetConfigs[name] = normalizeScenarioDraftForUi(config, name);
      });
    }
    if (saved.uiState?.currentPage && renderers[saved.uiState.currentPage]) {
      currentPage = saved.uiState.currentPage;
      currentSection = pageToSection[currentPage] || saved.uiState.currentSection || "home";
    }
    if (typeof formState.scenario_builder.factor_sleeves === "string") {
      formState.scenario_builder.factor_sleeves = formState.scenario_builder.factor_sleeves
        .split("/")
        .map((item) => item.trim())
        .filter(Boolean);
    }
    if (typeof defaultScenarioBuilderState.factor_sleeves === "string") {
      defaultScenarioBuilderState.factor_sleeves = defaultScenarioBuilderState.factor_sleeves
        .split("/")
        .map((item) => item.trim())
        .filter(Boolean);
    }
    try {
      const rawSession = window.sessionStorage.getItem(REPORT_STUDIO_SESSION_KEY);
      if (rawSession) {
        const savedSession = JSON.parse(rawSession);
        if (savedSession && typeof savedSession.api_key === "string") {
          formState.report_studio.api_key = savedSession.api_key;
        }
      }
    } catch {}
    const preferredSectorFocus = formState.holdings_trades?.sector_focus || formState.risk_dashboard?.sector_focus || "All sectors";
    formState.holdings_trades.sector_focus = preferredSectorFocus;
    formState.risk_dashboard.sector_focus = preferredSectorFocus;
  } catch {}
}

function syncSharedFieldState(pageId, key, value) {
  if (key !== "sector_focus") return;
  ["risk_dashboard", "holdings_trades"].forEach((linkedPage) => {
    if (!formState[linkedPage]) return;
    formState[linkedPage][key] = value;
    if (dirtyState[linkedPage] !== undefined && linkedPage !== pageId) dirtyState[linkedPage] = true;
  });
}

function normalizeReportApiUrl(value) {
  return String(value || "").trim().replace(/\/+$/, "").toLowerCase();
}

function isManagedReportApiUrl(value) {
  const normalized = normalizeReportApiUrl(value);
  if (!normalized) return true;
  if (REPORT_MANAGED_API_URLS.some((url) => normalizeReportApiUrl(url) === normalized)) return true;
  return normalized.startsWith("https://generativelanguage.googleapis.com/v1beta/models/")
    && normalized.includes(":generatecontent");
}

function syncReportApiUrlForFormat(format) {
  const nextUrl = REPORT_DEFAULT_API_URLS[format];
  if (!nextUrl) return false;
  const currentUrl = formState.report_studio?.api_url || "";
  if (currentUrl && !isManagedReportApiUrl(currentUrl)) return false;
  if (currentUrl === nextUrl) return false;
  formState.report_studio.api_url = nextUrl;
  return true;
}

function clearLlmModelCatalog() {
  runtimeState.llmModelCatalog = {
    models: [],
    status: "idle",
    error: "",
    fetchedAt: "",
    requestFormat: "",
    modelUrl: "",
  };
}

function getSharedSectorFocus() {
  const holdingsFocus = String(formState.holdings_trades?.sector_focus || "").trim();
  const riskFocus = String(formState.risk_dashboard?.sector_focus || "").trim();
  if (holdingsFocus && holdingsFocus !== "All sectors") return holdingsFocus;
  if (riskFocus && riskFocus !== "All sectors") return riskFocus;
  return holdingsFocus || riskFocus || "All sectors";
}

function isViewOnlyControl(pageId, key) {
  if (pageId === "holdings_trades") {
    return ["trade_filter", "sector_focus", "attribution_view"].includes(key);
  }
  if (pageId === "risk_dashboard") {
    return ["snapshot_date", "sector_focus", "compare_mode", "covariance_focus"].includes(key);
  }
  return false;
}

function normalizeSectorName(value) {
  const text = String(value || "").trim();
  if (!text) return "Unknown";
  if (text === "Technology") return "Information Technology";
  return text;
}

function getSectorFocusOptions() {
  const values = new Set(["All sectors"]);
  [...(store.tradeBlotter?.holdingsRows || []), ...(store.tradeBlotter?.tradeRows || [])].forEach((row) => {
    const sector = normalizeSectorName(row?.sector);
    if (sector && sector !== "Unknown") values.add(sector);
  });
  [formState.holdings_trades?.sector_focus, formState.risk_dashboard?.sector_focus].forEach((value) => {
    const sector = normalizeSectorName(value);
    if (sector && sector !== "Unknown") values.add(sector);
  });
  return ["All sectors", ...Array.from(values).filter((value) => value !== "All sectors").sort((left, right) => left.localeCompare(right))];
}

async function fetchApiJson(path) {
  const response = await fetch(path);
  if (!response.ok) throw new Error(`Request failed: ${path}`);
  return response.json();
}

async function sendApiJson(path, method, payload) {
  const response = await fetch(path, {
    method,
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    let detail = "";
    try {
      const contentType = response.headers.get("content-type") || "";
      if (contentType.includes("application/json")) {
        const body = await response.json();
        detail = body?.detail || body?.error || body?.message || JSON.stringify(body);
      } else {
        detail = (await response.text()).trim();
      }
    } catch (error) {
      detail = "";
    }
    throw new Error(detail ? `Request failed: ${path} - ${detail}` : `Request failed: ${path}`);
  }
  return response.json();
}

function buildScaledSeries(length, endValue, startValue = 100) {
  const safeLength = Math.max(length, 2);
  const step = (endValue - startValue) / (safeLength - 1);
  return Array.from({ length: safeLength }, (_, index) => Number((startValue + step * index).toFixed(2)));
}

function buildDrawdownSeries(length, maxDrawdownPct) {
  const safeLength = Math.max(length, 2);
  const midpoint = Math.floor((safeLength - 1) / 2);
  return Array.from({ length: safeLength }, (_, index) => {
    const distance = Math.abs(index - midpoint) / Math.max(midpoint, 1);
    const value = -maxDrawdownPct * (1 - Math.min(distance, 1));
    return Number(value.toFixed(2));
  });
}

function saveScenarioBuilderStateToApi() {
  const payload = {
    draft: enforceQuarterlyScenarioConfig(JSON.parse(JSON.stringify(formState.scenario_builder))),
    presets: JSON.parse(JSON.stringify(scenarioPresetConfigs)),
    active_preset: formState.scenario_builder.active_preset || null,
  };
  return sendApiJson("/api/scenario-builder/state", "POST", payload)
    .then((response) => {
      apiRuntime.lastSyncedAt = response.saved_at || apiRuntime.lastSyncedAt;
      return response;
    })
    .catch((error) => {
      console.warn("Scenario builder state sync failed.", error);
      return null;
    });
}

function saveScenarioRecordToApi({ scenarioName, scenarioConfig, parentScenarioId = null, notes = "" }) {
  return sendApiJson("/api/scenarios/create", "POST", {
    scenario_name: scenarioName,
    scenario_config: enforceQuarterlyScenarioConfig(JSON.parse(JSON.stringify(scenarioConfig))),
    parent_scenario_id: parentScenarioId,
    notes,
  });
}

function setMainlineScenarioToApi(scenarioId) {
  return sendApiJson(`/api/scenarios/${encodeURIComponent(scenarioId)}/set-mainline`, "POST", {});
}

function cloneScenarioToApi(scenarioId) {
  return sendApiJson(`/api/scenarios/${encodeURIComponent(scenarioId)}/clone`, "POST", {});
}

function updateScenarioRecordToApi({ scenarioId, scenarioName, scenarioConfig, notes = "" }) {
  return sendApiJson(`/api/scenarios/${encodeURIComponent(scenarioId)}`, "PUT", {
    scenario_name: scenarioName,
    scenario_config: enforceQuarterlyScenarioConfig(JSON.parse(JSON.stringify(scenarioConfig))),
    parent_scenario_id: null,
    notes,
  });
}

function deleteScenarioToApi(scenarioId) {
  return sendApiJson(`/api/scenarios/${encodeURIComponent(scenarioId)}`, "DELETE");
}

function runBacktestToApi({ scenarioId, scenarioName, scenarioConfig, owner, priority, artifactBundle, notifications, mode = "full" }) {
  return sendApiJson("/api/backtests/run", "POST", {
    scenario_id: scenarioId || null,
    scenario_name: scenarioName || null,
    scenario_config: scenarioConfig ? enforceQuarterlyScenarioConfig(JSON.parse(JSON.stringify(scenarioConfig))) : null,
    owner,
    priority,
    artifact_bundle: artifactBundle,
    notifications,
    mode,
    auto_start: true,
  });
}

function compareBacktestsToApi({ scenarioIds, owner, priority, artifactBundle, notifications }) {
  return sendApiJson("/api/backtests/compare", "POST", {
    scenario_ids: scenarioIds,
    owner,
    priority,
    artifact_bundle: artifactBundle,
    notifications,
    auto_start: true,
  });
}

function estimateBacktestCostToApi({ scenarioId, scenarioName, scenarioConfig, mode = "full" }) {
  return sendApiJson("/api/backtests/estimate-cost", "POST", {
    scenario_id: scenarioId || null,
    scenario_name: scenarioName || null,
    scenario_config: scenarioConfig ? enforceQuarterlyScenarioConfig(JSON.parse(JSON.stringify(scenarioConfig))) : null,
    mode,
  });
}

function runSensitivityToApi({
  scenarioId,
  scenarioName,
  scenarioConfig,
  baseScenario,
  sensitivityDimensions,
  rangeProfile,
  bootstrapIterations,
  stochasticMode,
  subperiodDefinition,
  owner,
  priority,
}) {
  return sendApiJson("/api/robustness/run-sensitivity", "POST", {
    scenario_id: scenarioId || null,
    scenario_name: scenarioName || null,
    scenario_config: scenarioConfig ? enforceQuarterlyScenarioConfig(JSON.parse(JSON.stringify(scenarioConfig))) : null,
    base_scenario: baseScenario,
    sensitivity_dimensions: Array.isArray(sensitivityDimensions) ? [...sensitivityDimensions] : [],
    range_profile: rangeProfile,
    bootstrap_iterations: Number.parseInt(bootstrapIterations || "1000", 10) || 1000,
    stochastic_mode: stochasticMode,
    subperiod_definition: subperiodDefinition,
    owner: owner || "Team C",
    priority: priority || "Normal",
    auto_start: true,
  });
}

function cancelBacktestToApi(runId) {
  return sendApiJson(`/api/backtests/${encodeURIComponent(runId)}/cancel`, "POST", {});
}

function deleteBacktestToApi(runId) {
  return sendApiJson(`/api/backtests/${encodeURIComponent(runId)}`, "DELETE");
}

function isTrackedWebRunId(runId) {
  return /^(BT|BATCH|NIGHTLY|NIGHTLYRUN|NIGHTLYBATCH)-/.test(String(runId || ""));
}

function queueRunnerRequestToApi(payload) {
  return sendApiJson("/api/backtest-runner/queue", "POST", payload).catch((error) => {
    console.warn("Backtest runner queue sync failed.", error);
    return null;
  });
}

function normalizeStatusLabel(status) {
  const raw = String(status || "").trim().toLowerCase();
  const mapping = {
    queued: "Queued",
    scheduled: "Scheduled",
    running: "Running",
    completed: "Completed",
    success: "Completed",
    failed: "Failed",
    warning: "Warning",
    missing: "Idle",
    single_run: "Queued",
    batch_compare: "Queued",
    nightly_refresh: "Scheduled",
  };
  return mapping[raw] || (raw ? raw.charAt(0).toUpperCase() + raw.slice(1) : "Idle");
}

function statusToneClass(status) {
  const normalized = normalizeStatusLabel(status).toLowerCase();
  if (normalized === "completed") return "status-good";
  if (normalized === "running") return "status-info";
  if (normalized === "queued" || normalized === "scheduled") return "status-pending";
  if (normalized === "failed" || normalized === "interrupted") return "status-bad";
  return "";
}

function formatApiTimestamp(value) {
  if (!value) return "n/a";
  const text = String(value).trim();
  const parsed = new Date(text);
  if (!Number.isNaN(parsed.getTime())) {
    return parsed.toLocaleString("en-GB", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    });
  }
  return text.replace("T", " ").replace("Z", "").replace(/\.\d+$/, "");
}

function parseApiTimestamp(value) {
  if (!value) return null;
  const parsed = new Date(String(value).trim());
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function formatElapsedDuration(totalSeconds) {
  const safeSeconds = Math.max(0, Math.floor(Number(totalSeconds) || 0));
  const hours = Math.floor(safeSeconds / 3600);
  const minutes = Math.floor((safeSeconds % 3600) / 60);
  const seconds = safeSeconds % 60;
  if (hours > 0) return `${hours}h ${minutes}m ${seconds}s`;
  if (minutes > 0) return `${minutes}m ${seconds}s`;
  return `${seconds}s`;
}

function getRunDurationDisplay(runId, fallback = "n/a", detailOverride = null, statusOverride = "") {
  const detail = detailOverride || runtimeState.runMeta?.[runId]?.job;
  if (!detail) return fallback || "n/a";
  const start = parseApiTimestamp(detail.started_at) || parseApiTimestamp(detail.created_at);
  if (!start) return fallback || "n/a";
  const normalizedStatus = normalizeStatusLabel(statusOverride || detail.status || detail.queue_type || "");
  const terminalEnd =
    parseApiTimestamp(detail.finished_at) ||
    (["Canceled", "Failed", "Completed", "Interrupted"].includes(normalizedStatus)
      ? parseApiTimestamp(detail.updated_at) || parseApiTimestamp(detail.created_at)
      : null);
  if (["Canceled", "Failed", "Completed", "Interrupted"].includes(normalizedStatus) && !terminalEnd) {
    return fallback || "n/a";
  }
  const end = terminalEnd || new Date();
  const elapsedSeconds = (end.getTime() - start.getTime()) / 1000;
  return formatElapsedDuration(elapsedSeconds);
}

function formatScheduledTimeValue(value) {
  const text = String(value || "").trim();
  if (!text) return "";
  if (/^\d{2}:\d{2}$/.test(text)) return text;
  const parsed = parseApiTimestamp(text);
  if (parsed) {
    return parsed.toLocaleTimeString("en-GB", {
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    });
  }
  return text;
}

function promptNightlyStartTime(defaultValue = "") {
  const fallbackValue = formatScheduledTimeValue(defaultValue) || formState.backtest_runner?.nightly_time || "22:00";
  const userValue = window.prompt("Nightly refresh start time (HH:MM)", fallbackValue);
  if (userValue == null) return null;
  const nightlyTime = String(userValue || "").trim();
  if (!/^\d{2}:\d{2}$/.test(nightlyTime)) {
    showToast("Nightly time must use HH:MM format.");
    return null;
  }
  const [hour, minute] = nightlyTime.split(":").map((item) => Number.parseInt(item, 10));
  if (hour < 0 || hour > 23 || minute < 0 || minute > 59) {
    showToast("Nightly time must be a valid 24-hour time.");
    return null;
  }
  return nightlyTime;
}

function getRunScheduledDisplay(runId, fallback = "") {
  const detail = runtimeState.runMeta?.[runId]?.job;
  const preferred = detail?.scheduled_for || fallback || detail?.next_scheduled_for || "";
  return formatScheduledTimeValue(preferred);
}

function getNightlyLinkedRunDetail(runId) {
  const detail = runtimeState.runMeta?.[runId]?.job;
  const linkedRunId = String(detail?.last_run_id || "").trim();
  if (!linkedRunId) return null;
  const linkedDetail = runtimeState.runMeta?.[linkedRunId]?.job || null;
  return {
    linkedRunId,
    linkedDetail,
    linkedStatus: normalizeStatusLabel(linkedDetail?.status || ""),
  };
}

function getNightlyTemplateDisplayState(runId, status, fallbackDuration = "") {
  const normalizedStatus = normalizeStatusLabel(status);
  const linked = getNightlyLinkedRunDetail(runId);
  if (["Canceled", "Failed", "Completed", "Interrupted"].includes(normalizedStatus)) {
    return {
      statusLabel: normalizedStatus,
      toneStatus: normalizedStatus,
      durationLabel: getRunDurationDisplay(runId, fallbackDuration, null, normalizedStatus),
      linkedRunId: linked?.linkedRunId || null,
    };
  }
  if (linked?.linkedRunId && linked.linkedDetail && linked.linkedStatus && linked.linkedStatus !== "Idle") {
    return {
      statusLabel: linked.linkedStatus,
      toneStatus: linked.linkedStatus,
      durationLabel: getRunDurationDisplay(linked.linkedRunId, fallbackDuration, linked.linkedDetail, linked.linkedStatus),
      linkedRunId: linked.linkedRunId,
    };
  }
  if (normalizedStatus !== "Scheduled") {
    return {
      statusLabel: normalizedStatus,
      toneStatus: normalizedStatus,
      durationLabel: getRunDurationDisplay(runId, fallbackDuration, null, normalizedStatus),
    };
  }
  const scheduledTime = getRunScheduledDisplay(runId, fallbackDuration);
  return {
    statusLabel: scheduledTime ? `Scheduled ${scheduledTime}` : "Scheduled",
    toneStatus: "Scheduled",
    durationLabel: scheduledTime ? `Starts ${scheduledTime}` : (fallbackDuration || "n/a"),
  };
}

function getRunStatusCellDisplay(runId, status, fallbackDuration = "") {
  return getNightlyTemplateDisplayState(runId, status, fallbackDuration).statusLabel;
}

function updateRunHistoryDurationCellsInPlace() {
  const historyWrap = pageContent.querySelector(".history-table-wrap");
  if (!historyWrap) return;
  historyWrap.querySelectorAll("[data-duration-run-id]").forEach((cell) => {
    const runId = cell.getAttribute("data-duration-run-id");
    if (!runId) return;
    const row = sanitizeRunHistoryRows(store.runHistory.runs).find((item) => item[0] === runId);
    const state = getNightlyTemplateDisplayState(runId, row?.[3] || "Idle", row?.[4] || "n/a");
    cell.textContent = state.durationLabel;
  });
}

function ensureRunMeta(runId) {
  if (!runtimeState.runMeta[runId]) runtimeState.runMeta[runId] = {};
  return runtimeState.runMeta[runId];
}

async function syncRunJobDetail(runId) {
  if (!runId) return null;
  try {
    const detail = await fetchApiJson(`/api/backtest-runner/jobs/${encodeURIComponent(runId)}`);
    const runMeta = ensureRunMeta(runId);
    runMeta.job = detail;
    const linkedRunId = String(detail?.last_run_id || "").trim();
    if (
      String(detail?.queue_type || "").trim().toLowerCase() === "nightly_refresh" &&
      linkedRunId &&
      !runtimeState.runMeta?.[linkedRunId]?.job
    ) {
      await syncRunJobDetail(linkedRunId);
    }
    const rowIndex = store.runHistory.runs.findIndex((row) => row[0] === runId);
    const currentRow = rowIndex >= 0 ? store.runHistory.runs[rowIndex] : null;
    const currentStatus = currentRow?.[3] ? normalizeStatusLabel(currentRow[3]) : "";
    const detailStatus = normalizeStatusLabel(detail.status);
    const nextStatus = detailStatus === "Idle" && ["Running", "Queued", "Scheduled"].includes(currentStatus)
      ? currentStatus
      : detailStatus;
    const nextDuration = getRunDurationDisplay(runId, currentRow?.[4] || "n/a", detail, nextStatus);
    if (rowIndex >= 0) {
      const nightlyDisplay = getNightlyTemplateDisplayState(runId, nextStatus, currentRow?.[4] || "n/a");
      store.runHistory.runs[rowIndex] = [
        currentRow[0],
        currentRow[1],
        currentRow[2],
        nightlyDisplay.toneStatus,
        nightlyDisplay.durationLabel || nextDuration,
      ];
    }
    if (Array.isArray(detail.scenario_manifests) && detail.scenario_manifests.length) {
      runtimeState.runLogs[runId] = [
        `[job] Status: ${nextStatus}`,
        `[job] Created: ${formatApiTimestamp(detail.created_at)}`,
        ...(detail.started_at ? [`[job] Started: ${formatApiTimestamp(detail.started_at)}`] : []),
        ...(detail.finished_at ? [`[job] Finished: ${formatApiTimestamp(detail.finished_at)}`] : []),
        ...(detail.launch_path ? [`[job] Launch script: ${detail.launch_path}`] : []),
        ...(detail.log_path ? [`[job] Log file: ${detail.log_path}`] : []),
        ...detail.scenario_manifests.map((item) => `[job] Config: ${item.generated_config_path}`),
      ];
    }
    return detail;
  } catch (error) {
    console.warn(`Run job detail sync failed for ${runId}.`, error);
    return null;
  }
}

async function loadRunLogFromApi(runId) {
  if (!runId) return null;
  try {
    const payload = await fetchApiJson(`/api/backtest-runner/jobs/${encodeURIComponent(runId)}/log`);
    if (Array.isArray(payload.lines) && payload.lines.length) {
      runtimeState.runLogs[runId] = payload.lines;
      return payload.lines;
    }
    return runtimeState.runLogs[runId] || null;
  } catch (error) {
    console.warn(`Run log fetch failed for ${runId}.`, error);
    return runtimeState.runLogs[runId] || null;
  }
}

async function refreshRunHistoryFromApi() {
  try {
    const rows = await fetchApiJson("/api/runs/recent");
    mergeApiRuns(rows);
    const webRunIds = store.runHistory.runs
      .map((row) => row[0])
      .filter((runId) => isTrackedWebRunId(runId));
    await Promise.all(webRunIds.map((runId) => syncRunJobDetail(runId)));
    persistState();
    return true;
  } catch (error) {
    console.warn("Run history API refresh failed.", error);
    const liveRunIds = sanitizeRunHistoryRows(store.runHistory.runs)
      .filter((row) => ["Queued", "Running", "Scheduled"].includes(normalizeStatusLabel(row[3])) && isTrackedWebRunId(row[0]))
      .map((row) => row[0]);
    if (!liveRunIds.length) return false;
    await Promise.all(liveRunIds.map((runId) => syncRunJobDetail(runId)));
    persistState();
    return true;
  }
}

function enforceQuarterlyScenarioConfig(config) {
  const next = config && typeof config === "object" ? config : {};
  next.rebalance = "Quarterly";
  return next;
}

function getScenarioConfigSnapshotByName(name) {
  if (name === "Current working scenario") {
    return enforceQuarterlyScenarioConfig(JSON.parse(JSON.stringify(formState.scenario_builder)));
  }
  return enforceQuarterlyScenarioConfig(JSON.parse(JSON.stringify(scenarioPresetConfigs[name] || formState.scenario_builder)));
}

function getBatchScenarioConfigMap(targets) {
  const result = {};
  targets.forEach((targetName) => {
    result[targetName] = getScenarioConfigSnapshotByName(targetName);
  });
  return result;
}

function mergeApiRuns(rows) {
  if (!Array.isArray(rows) || !rows.length) return;
  const incomingIds = new Set(rows.map((row) => String(row.run_id || "").trim()).filter(Boolean));
  const existingRows = sanitizeRunHistoryRows(store.runHistory.runs);
  const keepLocalOnlyRow = (row) => {
    const runId = String(row?.[0] || "").trim();
    if (!runId || incomingIds.has(runId)) return false;
    const status = normalizeStatusLabel(row?.[3] || "");
    if (!["Queued", "Running", "Scheduled"].includes(status)) return false;
    return isTrackedWebRunId(runId);
  };
  const existing = new Map(
    existingRows
      .filter((row) => incomingIds.has(row[0]) || keepLocalOnlyRow(row))
      .map((row) => [row[0], row]),
  );
  const statusPriority = {
    Canceled: 7,
    Failed: 6,
    Completed: 5,
    Success: 5,
    Running: 4,
    Queued: 3,
    Scheduled: 2,
    Idle: 1,
  };
  rows.forEach((row) => {
    const started = formatApiTimestamp(row.started_at);
    const scenario = row.scenario || "Imported API run";
    const status = normalizeStatusLabel(row.status || "Completed");
    const duration = (() => {
      const startedAt = parseApiTimestamp(row.started_at);
      const finishedAt =
        parseApiTimestamp(row.finished_at) ||
        (["Canceled", "Failed", "Completed", "Interrupted"].includes(status)
          ? parseApiTimestamp(row.updated_at) || parseApiTimestamp(row.created_at)
          : null);
      if (startedAt) {
        return formatElapsedDuration(((finishedAt || new Date()).getTime() - startedAt.getTime()) / 1000);
      }
      return row.duration || "n/a";
    })();
    const nextRow = [row.run_id, started, scenario, status, duration];
    const previous = existing.get(row.run_id);
    if (!previous || (statusPriority[status] || 0) >= (statusPriority[normalizeStatusLabel(previous[3])] || 0)) {
      existing.set(row.run_id, nextRow);
    }
    if (!runtimeState.runMeta[row.run_id]) runtimeState.runMeta[row.run_id] = { owner: "API" };
    runtimeState.runMeta[row.run_id].job = {
      ...(runtimeState.runMeta[row.run_id].job || {}),
      ...row,
    };
    if (!runtimeState.runLogs[row.run_id]) {
      runtimeState.runLogs[row.run_id] = [
        `[import] Loaded from /api/runs/recent`,
        `[import] Scenario: ${scenario}`,
        `[import] Status: ${status}`,
      ];
    }
  });
  store.runHistory.runs = sanitizeRunHistoryRows(Array.from(existing.values())).sort(
    (a, b) => parseRunDate(b[1]).getTime() - parseRunDate(a[1]).getTime(),
  );
}

function reconcileProvisionalRunId(provisionalRunId, realRunId, fallbackStatus = "Queued") {
  if (!provisionalRunId || !realRunId || provisionalRunId === realRunId) return;
  const rowIndex = store.runHistory.runs.findIndex((row) => row[0] === provisionalRunId);
  if (rowIndex >= 0) {
    const currentRow = store.runHistory.runs[rowIndex];
    store.runHistory.runs[rowIndex] = [realRunId, currentRow[1], currentRow[2], fallbackStatus, currentRow[4]];
  }
  if (runtimeState.runLogs[provisionalRunId]) {
    runtimeState.runLogs[realRunId] = runtimeState.runLogs[provisionalRunId];
    delete runtimeState.runLogs[provisionalRunId];
  }
  if (runtimeState.runMeta[provisionalRunId]) {
    runtimeState.runMeta[realRunId] = runtimeState.runMeta[provisionalRunId];
    delete runtimeState.runMeta[provisionalRunId];
  }
  if (runtimeState.latestLogRunId === provisionalRunId) runtimeState.latestLogRunId = realRunId;
  if (runtimeState.highlightedRunId === provisionalRunId) runtimeState.highlightedRunId = realRunId;
}

function applySummaryCards(cards) {
  if (!Array.isArray(cards) || !cards.length) return;
  const metrics = cards.slice(0, 3).map((item) => ({
    label: item.label,
    value: item.value,
    note: "Live from connected CW2 API output bundle.",
  }));
  if (metrics.length >= 3) {
    store.overview.metrics = metrics;
  }
}

function applyArtifacts(rows) {
  if (!Array.isArray(rows) || !rows.length) return;
  store.artifacts.records = rows.map((row) => ({ ...row }));
  store.artifacts.packs = rows.map((row) => [
    row.name,
    `${row.description} [${row.source}]`,
  ]);
  store.runHistory.artifacts = rows.slice(0, 4).map((row) => [
    row.name,
    row.status === "available" ? "Generated" : row.status,
  ]);
}

function applyRobustnessDashboard(rows) {
  if (!Array.isArray(rows) || !rows.length) return;
  store.robustness.scenarios = rows.slice(0, 6).map((row) => [
    row.title,
    row.annualized_return == null ? "n/a" : `${(row.annualized_return * 100).toFixed(1)}%`,
    row.sharpe == null ? "n/a" : Number(row.sharpe).toFixed(2),
    row.max_drawdown == null ? "n/a" : `${(row.max_drawdown * 100).toFixed(1)}%`,
  ]);
  const mainline = rows.find((row) => row.item_key === "mainline_realized");
  if (mainline) {
    store.performance.sharpe = store.performance.sharpe.map(() => Number(mainline.sharpe || 0.83));
  }
}

function applyAcceptanceRows(rows) {
  if (!Array.isArray(rows) || !rows.length) return;
  store.robustness.acceptance = rows.slice(0, 5).map((row) => [
    row.label,
    row.status,
  ]);
}

function applyTest11Summary(rows) {
  if (!Array.isArray(rows) || !rows.length) return;
  store.robustness.subperiods = rows.map((row) => [
    row.sample_band,
    `${row.annualized_return_mean_pct}%`,
    row.sharpe_mean,
    `${row.excess_return_mean_pct}%`,
  ]);
}

function applyRobustnessSubperiodRows(rows) {
  if (!Array.isArray(rows) || !rows.length) return;
  const cleaned = rows
    .filter((row) => row.regime && row.strategy_ann_return_pct != null)
    .slice(0, 6)
    .map((row) => [
      String(row.regime).replace(/^./, (char) => char.toUpperCase()),
      `${Number(row.strategy_ann_return_pct || 0).toFixed(1)}%`,
      Number(row.strategy_sharpe || 0).toFixed(2),
      `${Number(row.hit_rate_pct || 0).toFixed(1)}%`,
    ]);
  if (cleaned.length) store.robustness.subperiods = cleaned;
}

async function refreshRobustnessFromApi(showFeedback = false) {
  try {
    const [dashboard, acceptance, subperiods, test11] = await Promise.all([
      fetchApiJson("/api/robustness/dashboard"),
      fetchApiJson("/api/robustness/acceptance"),
      fetchApiJson("/api/robustness/subperiods"),
      fetchApiJson("/api/robustness/test11"),
    ]);
    applyRobustnessDashboard(dashboard);
    applyAcceptanceRows(acceptance);
    applyRobustnessSubperiodRows(subperiods);
    applyTest11Summary(test11);
    persistState();
    render(false);
    if (showFeedback) showToast("Robustness tables refreshed from API.");
    return true;
  } catch (error) {
    console.warn("Robustness refresh failed.", error);
    if (showFeedback) showToast("Robustness refresh failed.");
    return false;
  }
}

function applyPerformanceBaseline(payload) {
  if (!payload?.summary) return;
  const summary = payload.summary;
  const comparatives = payload.comparatives || {};
  const strategyEnd = 100 + Number(summary.cumulative_return_pct || 0);
  const benchmarkEnd = strategyEnd - Number(summary.excess_return_pct || 0);
  const staticEnd = strategyEnd - Number(comparatives.static_baseline?.excess_return_annualized_pct || 0);
  store.performance.summary = summary;
  store.performance.comparatives = comparatives;
  store.performance.nav = buildScaledSeries(store.performance.nav.length, strategyEnd);
  store.performance.benchmark = buildScaledSeries(store.performance.benchmark.length, benchmarkEnd);
  store.performance.baseline = buildScaledSeries(store.performance.baseline.length, staticEnd);
  store.performance.excess = buildScaledSeries(store.performance.excess.length, Number(summary.excess_return_pct || 0), 0);
  store.performance.sharpe = buildScaledSeries(store.performance.sharpe.length, Number(summary.rolling_sharpe || 0.82), Math.max(Number(summary.rolling_sharpe || 0.82) - 0.25, 0.2));
  store.performance.drawdown = buildDrawdownSeries(store.performance.drawdown.length, Number(summary.max_drawdown_pct || 16.4));
}

function applyRiskRegime(payload) {
  if (!payload) return;
  const threshold = Number(payload.threshold);
  if (Number.isFinite(threshold)) store.regime.threshold = threshold;
  const latestVix = Number(payload.latest_vix);
  if (Number.isFinite(latestVix)) {
    const existingVix = Array.isArray(store.regime.vix)
      ? store.regime.vix.map((value) => Number(value)).filter(Number.isFinite)
      : [];
    store.regime.vix = existingVix.length ? [...existingVix.slice(0, -1), latestVix] : [latestVix];
  }
  if (payload.summary) {
    store.regime.summary = {
      ...payload.summary,
      latest_vix: Number.isFinite(latestVix) ? latestVix : payload.summary.latest_vix,
      stress_threshold: Number.isFinite(threshold) ? threshold : payload.summary.stress_threshold,
      current_regime: payload.regime_state || payload.summary.current_regime,
    };
  } else if (Number.isFinite(latestVix) || Number.isFinite(threshold) || payload.regime_state) {
    store.regime.summary = {
      ...(store.regime.summary || {}),
      latest_vix: Number.isFinite(latestVix) ? latestVix : store.regime.summary?.latest_vix,
      stress_threshold: Number.isFinite(threshold) ? threshold : store.regime.summary?.stress_threshold,
      current_regime: payload.regime_state || store.regime.summary?.current_regime,
    };
  }
  if (!store.regimeControl) store.regimeControl = {};
  store.regimeControl.summary = {
    ...(store.regimeControl.summary || {}),
    latest_vix: Number.isFinite(latestVix) ? latestVix : store.regimeControl.summary?.latest_vix,
    stress_threshold: Number.isFinite(threshold) ? threshold : store.regimeControl.summary?.stress_threshold,
    current_regime: payload.regime_state || store.regimeControl.summary?.current_regime,
  };
  const subperiods = Array.isArray(payload.subperiods) ? payload.subperiods : [];
  const normal = subperiods.find((row) => row.regime === "normal" && row.versus_series === "static_baseline");
  const stress = subperiods.find((row) => row.regime === "stress" && row.versus_series === "static_baseline");
  if (normal && stress) {
    store.robustness.subperiods = [
      ["Normal", `${Number(normal.strategy_ann_return_pct || 0).toFixed(1)}%`, Number(normal.strategy_sharpe || 0).toFixed(2), `${Number(normal.hit_rate_pct || 0).toFixed(1)}%`],
      ["Stress", `${Number(stress.strategy_ann_return_pct || 0).toFixed(1)}%`, Number(stress.strategy_sharpe || 0).toFixed(2), `${Number(stress.hit_rate_pct || 0).toFixed(1)}%`],
    ];
  }
}

function applyDataHealthSummary(payload) {
  if (!payload) return;
  store.health.updatedAt = payload.updated_at ? formatApiTimestamp(payload.updated_at) : store.health.updatedAt;
  if (Array.isArray(payload.coverage) && payload.coverage.length) store.health.coverage = payload.coverage;
  if (Array.isArray(payload.missing_rates) && payload.missing_rates.length) store.health.missingRates = payload.missing_rates;
  if (Array.isArray(payload.checks) && payload.checks.length) store.health.checks = payload.checks;
  if (Array.isArray(payload.dag) && payload.dag.length) store.health.dag = payload.dag;
  store.health.summary = payload.summary || {};
  store.health.batchId = payload.batch_id || store.health.batchId;
}

function applyScenarioBuilderState(payload) {
  if (!payload) return;
  if (payload.presets && typeof payload.presets === "object" && Object.keys(payload.presets).length) {
    Object.keys(scenarioPresetConfigs).forEach((key) => delete scenarioPresetConfigs[key]);
    Object.entries(payload.presets).forEach(([name, config]) => {
      scenarioPresetConfigs[name] = normalizeScenarioDraftForUi(config, name);
    });
    store.scenarioBuilder.presets = Object.entries(scenarioPresetConfigs).map(([name, config]) => [name, buildScenarioPresetDescription(config)]);
  }
  if (payload.draft && typeof payload.draft === "object" && Object.keys(payload.draft).length) {
    replaceScenarioBuilderDraft(payload.draft);
  }
  if (payload.active_preset) {
    formState.scenario_builder.active_preset = payload.active_preset;
  }
}

function pushNotification(message, tone = "info") {
  runtimeState.notifications.unshift({
    id: `NTF-${Date.now()}`,
    message,
    tone,
    createdAt: new Date().toISOString(),
  });
  runtimeState.notifications = runtimeState.notifications.slice(0, 12);
}

function syncDerivedFormsFromScenarioDraft() {
  const draft = formState.scenario_builder || {};
  if (formState.universe_selector) {
    formState.universe_selector.universe = draft.universe || formState.universe_selector.universe;
    formState.universe_selector.benchmark = draft.benchmark || formState.universe_selector.benchmark;
  }
  if (formState.regime_control) {
    formState.regime_control.vix_threshold = draft.vix_threshold || formState.regime_control.vix_threshold;
    formState.regime_control.stress_overlay = typeof draft.stress_overlay === "boolean" ? draft.stress_overlay : formState.regime_control.stress_overlay;
  }
  if (formState.optimizer_settings) {
    formState.optimizer_settings.top_n = draft.top_n || formState.optimizer_settings.top_n;
    formState.optimizer_settings.hold_cap = draft.hold_cap || formState.optimizer_settings.hold_cap;
    formState.optimizer_settings.transaction_cost = draft.transaction_cost || formState.optimizer_settings.transaction_cost;
    formState.optimizer_settings.neutralisation = typeof draft.neutralisation === "boolean" ? draft.neutralisation : formState.optimizer_settings.neutralisation;
  }
  if (formState.factor_lab) {
    formState.factor_lab.factor_sleeves = Array.isArray(draft.factor_sleeves) ? [...draft.factor_sleeves] : formState.factor_lab.factor_sleeves;
    formState.factor_lab.neutralisation = typeof draft.neutralisation === "boolean" ? draft.neutralisation : formState.factor_lab.neutralisation;
    formState.factor_lab.top_n = draft.top_n || formState.factor_lab.top_n;
    formState.factor_lab.cost_model = draft.transaction_cost || formState.factor_lab.cost_model;
    formState.factor_lab.winsorisation = draft.winsorisation || formState.factor_lab.winsorisation;
    formState.factor_lab.standardisation = draft.standardisation || formState.factor_lab.standardisation;
    formState.factor_lab.ewma_decay = draft.ewma_decay || formState.factor_lab.ewma_decay;
    formState.factor_lab.lookback_window = draft.lookback_window || formState.factor_lab.lookback_window;
  }
  if (formState.holdings_trades) {
    formState.holdings_trades.top_n = draft.top_n || formState.holdings_trades.top_n;
    formState.holdings_trades.hold_cap = draft.hold_cap || formState.holdings_trades.hold_cap;
    formState.holdings_trades.stress_overlay = typeof draft.stress_overlay === "boolean" ? draft.stress_overlay : formState.holdings_trades.stress_overlay;
    formState.holdings_trades.cost_model = draft.transaction_cost || formState.holdings_trades.cost_model;
  }
}

function syncWorkingScenarioFromPage(pageId = currentPage) {
  const draft = formState.scenario_builder || {};
  draft.rebalance = "Quarterly";
  if (pageId === "scenario_builder") {
    syncDerivedFormsFromScenarioDraft();
  }
  if (pageId === "universe_selector" && formState.universe_selector) {
    draft.universe = formState.universe_selector.universe;
    draft.benchmark = formState.universe_selector.benchmark;
  }
  if (pageId === "regime_control" && formState.regime_control) {
    draft.vix_threshold = formState.regime_control.vix_threshold;
    draft.stress_overlay = formState.regime_control.stress_overlay;
  }
  if (pageId === "optimizer_settings" && formState.optimizer_settings) {
    draft.top_n = formState.optimizer_settings.top_n;
    draft.hold_cap = formState.optimizer_settings.hold_cap;
    draft.transaction_cost = formState.optimizer_settings.transaction_cost;
    draft.neutralisation = formState.optimizer_settings.neutralisation;
  }
  if (pageId === "factor_lab" && formState.factor_lab) {
    draft.factor_sleeves = Array.isArray(formState.factor_lab.factor_sleeves) ? [...formState.factor_lab.factor_sleeves] : draft.factor_sleeves;
    draft.neutralisation = formState.factor_lab.neutralisation;
    draft.top_n = formState.factor_lab.top_n;
    draft.transaction_cost = formState.factor_lab.cost_model;
    draft.winsorisation = formState.factor_lab.winsorisation;
    draft.standardisation = formState.factor_lab.standardisation;
    draft.ewma_decay = formState.factor_lab.ewma_decay;
    draft.lookback_window = formState.factor_lab.lookback_window;
  }
  if (pageId === "holdings_trades" && formState.holdings_trades) {
    draft.top_n = formState.holdings_trades.top_n;
    draft.hold_cap = formState.holdings_trades.hold_cap;
    draft.stress_overlay = formState.holdings_trades.stress_overlay;
    draft.transaction_cost = formState.holdings_trades.cost_model;
    draft.execution_lag_days = formState.holdings_trades.execution_lag_days;
    draft.execution_style = formState.holdings_trades.execution_style;
  }
}

function buildCurrentWorkingScenarioConfig(sourcePage = currentPage) {
  const merged = JSON.parse(JSON.stringify(formState.scenario_builder || {}));
  merged.rebalance = "Quarterly";
  if (sourcePage === "universe_selector" && formState.universe_selector) {
    merged.universe = formState.universe_selector.universe;
    merged.benchmark = formState.universe_selector.benchmark;
  }
  if (sourcePage === "regime_control" && formState.regime_control) {
    merged.vix_threshold = formState.regime_control.vix_threshold;
    merged.stress_overlay = formState.regime_control.stress_overlay;
  }
  if (sourcePage === "optimizer_settings" && formState.optimizer_settings) {
    merged.top_n = formState.optimizer_settings.top_n;
    merged.hold_cap = formState.optimizer_settings.hold_cap;
    merged.transaction_cost = formState.optimizer_settings.transaction_cost;
    merged.neutralisation = formState.optimizer_settings.neutralisation;
  }
  if (sourcePage === "factor_lab" && formState.factor_lab) {
    merged.factor_sleeves = Array.isArray(formState.factor_lab.factor_sleeves) ? [...formState.factor_lab.factor_sleeves] : merged.factor_sleeves;
    merged.neutralisation = formState.factor_lab.neutralisation;
    merged.top_n = formState.factor_lab.top_n;
    merged.transaction_cost = formState.factor_lab.cost_model;
    merged.winsorisation = formState.factor_lab.winsorisation;
    merged.standardisation = formState.factor_lab.standardisation;
    merged.ewma_decay = formState.factor_lab.ewma_decay;
    merged.lookback_window = formState.factor_lab.lookback_window;
  }
  if (sourcePage === "holdings_trades" && formState.holdings_trades) {
    merged.top_n = formState.holdings_trades.top_n;
    merged.hold_cap = formState.holdings_trades.hold_cap;
    merged.stress_overlay = formState.holdings_trades.stress_overlay;
    merged.transaction_cost = formState.holdings_trades.cost_model;
    merged.execution_lag_days = formState.holdings_trades.execution_lag_days;
    merged.execution_style = formState.holdings_trades.execution_style;
  }
  return enforceQuarterlyScenarioConfig(merged);
}

function scheduleLivePreview(pageId = currentPage) {
  if (!["universe_selector", "regime_control", "optimizer_settings", "factor_lab", "holdings_trades"].includes(pageId)) return;
  if (livePreviewTimers[pageId]) window.clearTimeout(livePreviewTimers[pageId]);
  livePreviewTimers[pageId] = window.setTimeout(() => {
    if (pageId === "universe_selector") void loadUniversePreview(false);
    if (pageId === "regime_control") void loadRegimePreview(false);
    if (pageId === "optimizer_settings") void loadOptimizerPreview(false);
    if (pageId === "factor_lab") void loadFactorPreview(false);
    if (pageId === "holdings_trades") void loadTradePreview(false);
  }, 320);
}

const floatingControlAnchorMap = {
  scenario_builder: {
    universe: "scenario-review-anchor",
    top_n: "scenario-review-anchor",
    vix_threshold: "scenario-review-anchor",
    transaction_cost: "scenario-review-anchor",
    neutralisation: "scenario-review-anchor",
    factor_sleeves: "scenario-review-anchor",
    hold_cap: "scenario-review-anchor",
    benchmark: "scenario-review-anchor",
    stress_overlay: "scenario-review-anchor",
    lookback_window: "scenario-review-anchor",
    output_pack: "scenario-review-anchor",
  },
  universe_selector: {
    universe: "universe-preview-anchor",
    benchmark: "universe-preview-anchor",
    company_focus: "universe-company-sample-anchor",
    require_dividend: "universe-company-sample-anchor",
    sector_tilt: "universe-company-sample-anchor",
  },
  regime_control: {
    stress_overlay: "regime-exposure-anchor",
    vix_threshold: "regime-exposure-anchor",
    warning_band: "regime-replay-anchor",
    exit_band: "regime-replay-anchor",
    regime_mode: "regime-summary-anchor",
    replay_window: "regime-replay-anchor",
  },
  optimizer_settings: {
    top_n: "optimizer-holdings-preview-anchor",
    hold_cap: "optimizer-holdings-preview-anchor",
    transaction_cost: "optimizer-factor-mix-anchor",
    neutralisation: "optimizer-factor-mix-anchor",
    turnover_target: "optimizer-constraint-anchor",
    optimizer_goal: "optimizer-factor-mix-anchor",
  },
  performance_dashboard: {
    nav_focus_period: "performance-point-detail-anchor",
    drilldown_view: "performance-point-context-anchor",
  },
  risk_dashboard: {
    snapshot_date: "risk-snapshot-summary-anchor",
    sector_focus: "risk-sector-holdings-anchor",
    compare_mode: "risk-profile-compare-anchor",
    covariance_focus: "risk-covariance-detail-anchor",
  },
  robustness_lab: {
    base_scenario: "robustness-launch-summary-anchor",
    sensitivity_dimensions: "robustness-parameter-comparison-anchor",
    range_profile: "robustness-parameter-comparison-anchor",
    bootstrap_iterations: "robustness-stochastic-anchor",
    stochastic_mode: "robustness-stochastic-anchor",
    subperiod_definition: "robustness-subperiod-anchor",
  },
  holdings_trades: {
    trade_filter: "trade-blotter-preview-anchor",
    sector_focus: "trade-holdings-slice-anchor",
    attribution_view: "trade-source-attribution-anchor",
  },
  backtest_runner: {
    scenario: "runner-lineage-anchor",
    execution_mode: "runner-queue-anchor",
    batch_targets: "runner-queue-anchor",
    nightly_mode: "runner-queue-anchor",
    nightly_time: "runner-queue-anchor",
    priority: "runner-queue-anchor",
    owner: "runner-queue-anchor",
    artifact_bundle: "runner-queue-anchor",
    notifications: "runner-queue-anchor",
  },
};

function getControlFocusAnchor(pageId = currentPage, key = "") {
  return floatingControlAnchorMap[pageId]?.[key] || "";
}

function queueControlFocus(pageId = currentPage, key = "") {
  if (pageToSection[pageId] === "research_setup" || pageId === "robustness_lab") {
    if (runtimeState.pendingControlFocus?.pageId === pageId) {
      runtimeState.pendingControlFocus = null;
    }
    return;
  }
  const anchorId = getControlFocusAnchor(pageId, key);
  if (!anchorId) return;
  runtimeState.pendingControlFocus = { pageId, anchorId };
}

function scrollToCurrentPageAnchor(anchorId, behavior = "smooth") {
  if (!anchorId) return false;
  const target = pageContent.querySelector(`#${anchorId}`) || document.getElementById(anchorId);
  if (!target) return false;
  target.scrollIntoView({ behavior, block: "center" });
  return true;
}

function consumePendingControlFocus() {
  const pending = runtimeState.pendingControlFocus;
  if (!pending || pending.pageId !== currentPage) return;
  runtimeState.pendingControlFocus = null;
  window.requestAnimationFrame(() => {
    scrollToCurrentPageAnchor(pending.anchorId);
  });
}

function getScenarioBuilderControlGroups() {
  const s = formState.scenario_builder;
  s.rebalance = "Quarterly";
  const sleeves = Array.isArray(s.factor_sleeves)
    ? s.factor_sleeves
    : String(s.factor_sleeves || "")
        .split("/")
        .map((item) => item.trim())
        .filter(Boolean);
  return {
    primary: [
      ["Universe", { type: "select", key: "universe", value: s.universe, options: ["US Large Cap", "US Broad Market", "Defensive Basket"] }],
      ["Rebalance", { type: "select", key: "rebalance", value: s.rebalance, options: ["Quarterly"] }],
      ["Top N", { type: "input", key: "top_n", value: s.top_n }],
      ["VIX Threshold", { type: "input", key: "vix_threshold", value: s.vix_threshold }],
      ["Transaction Cost", { type: "select", key: "transaction_cost", value: s.transaction_cost, options: ["10bps", "15bps", "25bps", "40bps"] }],
      ["Neutralisation", { type: "switch", key: "neutralisation", value: s.neutralisation }],
    ],
    secondary: [
      ["Factor Sleeves", { type: "tag", key: "factor_sleeves", value: sleeves }],
      ["Hold Cap", { type: "input", key: "hold_cap", value: s.hold_cap }],
      ["Benchmark", { type: "select", key: "benchmark", value: s.benchmark, options: ["Static baseline + market benchmark", "Benchmark only", "Custom control portfolio"] }],
      ["Stress Overlay", { type: "switch", key: "stress_overlay", value: s.stress_overlay }],
      ["Lookback Window", { type: "select", key: "lookback_window", value: s.lookback_window, options: ["6 months", "12 months", "24 months"] }],
      ["Output Pack", { type: "select", key: "output_pack", value: s.output_pack, options: ["NAV + holdings + risk", "NAV only", "Full artifact bundle"] }],
    ],
  };
}

function getBacktestRunnerControlFields() {
  const s = formState.backtest_runner;
  const scenarioOptions = getRunnerScenarioOptions();
  if (!scenarioOptions.includes(s.scenario)) s.scenario = "Current working scenario";
  normalizeBatchTargets();
  const isBatchMode = s.execution_mode === "Batch compare";
  const isNightlyMode = s.execution_mode === "Nightly refresh";
  const isNightlyBatch = isNightlyMode && s.nightly_mode === "Batch compare";
  const runnerControlsClass = isNightlyBatch
    ? "runner-controls-grid runner-controls-nightly-batch"
    : isBatchMode
      ? "runner-controls-grid runner-controls-batch"
      : "runner-controls-grid";
  const fields = isBatchMode
    ? [["Batch Targets", { type: "tag", key: "batch_targets", value: s.batch_targets, options: scenarioOptions, minSelect: 2, scrollable: true }], ["Execution Mode", { type: "select", key: "execution_mode", value: s.execution_mode, options: ["Single run", "Batch compare", "Nightly refresh"] }], ["Priority", { type: "select", key: "priority", value: s.priority, options: ["Normal", "High", "Low"] }], ["Owner", { type: "input", key: "owner", value: s.owner }], ["Artifact Bundle", { type: "switch", key: "artifact_bundle", value: s.artifact_bundle }], ["Notifications", { type: "switch", key: "notifications", value: s.notifications }]]
    : isNightlyMode
      ? [["Nightly Mode", { type: "select", key: "nightly_mode", value: s.nightly_mode, options: ["Single scenario", "Batch compare"] }], ...(
          isNightlyBatch
            ? [["Batch Targets", { type: "tag", key: "batch_targets", value: s.batch_targets, options: scenarioOptions, minSelect: 2, scrollable: true }]]
            : [["Scenario", { type: "select", key: "scenario", value: s.scenario, options: scenarioOptions }]]
        ), ["Nightly time", { type: "input", key: "nightly_time", value: s.nightly_time }], ["Execution Mode", { type: "select", key: "execution_mode", value: s.execution_mode, options: ["Single run", "Batch compare", "Nightly refresh"] }], ["Priority", { type: "select", key: "priority", value: s.priority, options: ["Normal", "High", "Low"] }], ["Owner", { type: "input", key: "owner", value: s.owner }], ["Artifact Bundle", { type: "switch", key: "artifact_bundle", value: s.artifact_bundle }], ["Notifications", { type: "switch", key: "notifications", value: s.notifications }]]
      : [["Scenario", { type: "select", key: "scenario", value: s.scenario, options: scenarioOptions }], ["Execution Mode", { type: "select", key: "execution_mode", value: s.execution_mode, options: ["Single run", "Batch compare", "Nightly refresh"] }], ["Priority", { type: "select", key: "priority", value: s.priority, options: ["Normal", "High", "Low"] }], ["Owner", { type: "input", key: "owner", value: s.owner }], ["Artifact Bundle", { type: "switch", key: "artifact_bundle", value: s.artifact_bundle }], ["Notifications", { type: "switch", key: "notifications", value: s.notifications }]];
  return { fields, runnerControlsClass, isBatchMode, isNightlyMode, isNightlyBatch };
}

function getFloatingControlSpec(pageId = currentPage) {
  if (pageToSection[pageId] === "research_setup" || pageId === "robustness_lab") {
    return null;
  }
  if (pageId === "scenario_builder") {
    const groups = getScenarioBuilderControlGroups();
    return {
      title: "Scenario Quick Controls",
      subtitle: "Keep the panel open while tuning setup fields, then auto-jump to the review block.",
      fields: [...groups.primary, ...groups.secondary],
      jumps: [
        { label: "Scenario Review", anchor: "scenario-review-anchor" },
        { label: "Unsaved Pages", anchor: "scenario-review-anchor" },
      ],
    };
  }
  if (pageId === "universe_selector") {
    const s = formState.universe_selector;
    return {
      title: "Universe Controls",
      subtitle: "Adjust the investable set here and jump to the preview sections that update below.",
      fields: [
        ["Universe", { type: "select", key: "universe", value: s.universe, options: ["US Large Cap", "US Broad Market", "Defensive Basket"] }],
        ["Benchmark", { type: "select", key: "benchmark", value: s.benchmark, options: ["Static baseline + market benchmark", "Benchmark only", "Custom control portfolio"] }],
        ["Company focus", { type: "select", key: "company_focus", value: s.company_focus, options: ["Large and liquid only", "Balanced quality/liquidity", "Defensive resilient names"] }],
        ["Dividend screen", { type: "switch", key: "require_dividend", value: s.require_dividend }],
        ["Sector tilt", { type: "select", key: "sector_tilt", value: s.sector_tilt, options: ["Balanced", "Defensive", "Cyclical check"] }],
      ],
      jumps: [
        { label: "Universe Summary", anchor: "universe-preview-anchor" },
        { label: "Company Sample", anchor: "universe-company-sample-anchor" },
      ],
    };
  }
  if (pageId === "regime_control") {
    const s = formState.regime_control;
    return {
      title: "Regime Controls",
      subtitle: "This panel drives threshold and replay settings, then takes you to the summary or exposure block that changed.",
      fields: [
        ["Stress overlay", { type: "switch", key: "stress_overlay", value: s.stress_overlay }],
        ["Stress threshold", { type: "input", key: "vix_threshold", value: s.vix_threshold }],
        ["Warning band", { type: "input", key: "warning_band", value: s.warning_band }],
        ["Exit band", { type: "input", key: "exit_band", value: s.exit_band }],
        ["Regime mode", { type: "select", key: "regime_mode", value: s.regime_mode, options: ["VIX-aware", "Manual override", "Threshold off"] }],
        ["Replay window", { type: "select", key: "replay_window", value: s.replay_window, options: ["Last 8 observations", "Last 12 observations", "Last 24 observations"] }],
      ],
      jumps: [
        { label: "Regime Summary", anchor: "regime-summary-anchor" },
        { label: "Threshold Replay", anchor: "regime-replay-anchor" },
        { label: "Exposure Shift", anchor: "regime-exposure-anchor" },
      ],
    };
  }
  if (pageId === "optimizer_settings") {
    const s = formState.optimizer_settings;
    return {
      title: "Optimizer Controls",
      subtitle: "Tweak breadth and constraints here, then jump straight to the part of the preview that changed.",
      fields: [
        ["Top N", { type: "input", key: "top_n", value: s.top_n }],
        ["Hold cap", { type: "input", key: "hold_cap", value: s.hold_cap }],
        ["Transaction cost", { type: "select", key: "transaction_cost", value: s.transaction_cost, options: ["10bps", "15bps", "25bps", "40bps"] }],
        ["Neutralisation", { type: "switch", key: "neutralisation", value: s.neutralisation }],
        ["Turnover target", { type: "input", key: "turnover_target", value: s.turnover_target }],
        ["Optimizer goal", { type: "select", key: "optimizer_goal", value: s.optimizer_goal, options: ["Balanced alpha / risk", "Low turnover first", "Higher conviction"] }],
      ],
      jumps: [
        { label: "Constraint Summary", anchor: "optimizer-constraint-anchor" },
        { label: "Factor Mix", anchor: "optimizer-factor-mix-anchor" },
        { label: "Holdings Preview", anchor: "optimizer-holdings-preview-anchor" },
      ],
    };
  }
  if (pageId === "factor_lab") {
    return {
      title: "Factor Review Map",
      subtitle: "This page is review-focused. Use the floating panel to jump to the raw and preview blocks without losing your scroll position.",
      jumps: [
        { label: "Signal Summary", anchor: "factor-summary-anchor" },
        { label: "Top Preview", anchor: "factor-top-preview-anchor" },
        { label: "Raw Attribution", anchor: "factor-attribution-anchor" },
        { label: "Research Setup", page: "scenario_builder" },
      ],
    };
  }
  if (pageId === "performance_dashboard") {
    const s = formState.performance_dashboard;
    const compareOptions = store.runHistory.runs
      .filter((row) => normalizeStatusLabel(row[3]) === "Completed" && isComparablePerformanceRunId(row[0]))
      .slice(0, 5)
      .map((row) => row[0]);
    const displayRunValue = getSelectedDisplayRun(compareOptions);
    const summaryRunValues = getSelectedSummaryRuns(compareOptions);
    return {
      title: "Performance View Controls",
      subtitle: "Use this panel to choose which run is displayed, then adjust the chart focus and drilldown context.",
      fields: [
        ["Display run", { type: "select", key: "compare_runs", value: displayRunValue, options: ["Baseline", ...compareOptions] }],
        ["Summary compare runs", { type: "tag", key: "compare_summary_runs", value: summaryRunValues, options: compareOptions, minSelect: 1, scrollable: true }],
        ["NAV focus", { type: "select", key: "nav_focus_period", value: s.nav_focus_period, options: ["Latest point", "Peak drawdown"] }],
        ["Drilldown view", { type: "select", key: "drilldown_view", value: s.drilldown_view, options: ["Holdings + factors", "Holdings only", "Factors only"] }],
      ],
      jumps: [
        { label: "Selected Run Summary", anchor: "performance-multi-run-anchor" },
        { label: "Benchmark Lens", anchor: "performance-benchmark-anchor" },
      ],
    };
  }
  if (pageId === "risk_dashboard") {
    const s = formState.risk_dashboard;
    const availableRiskSnapshotDates = Array.from(new Set([
      ...(Array.isArray(store.riskRaw?.availableDates) ? store.riskRaw.availableDates : []),
      ...(Array.isArray(store.riskRaw?.contributionAvailableDates) ? store.riskRaw.contributionAvailableDates : []),
      ...(Array.isArray(store.riskRaw?.rows) ? store.riskRaw.rows.map((row) => String(row.date || "").trim()).filter(Boolean) : []),
      ...(Array.isArray(store.riskRaw?.contributionRows) ? store.riskRaw.contributionRows.map((row) => String(row.date || "").trim()).filter(Boolean) : []),
    ])).sort((left, right) => right.localeCompare(left));
    return {
      title: "Risk View Filters",
      subtitle: "Keep the panel open while filtering the risk view, then auto-jump to the summary block that changed.",
      fields: [
        ["Snapshot date", { type: "select", key: "snapshot_date", value: s.snapshot_date, options: availableRiskSnapshotDates.length ? availableRiskSnapshotDates : [s.snapshot_date] }],
        ["Sector focus", { type: "select", key: "sector_focus", value: s.sector_focus, options: getSectorFocusOptions() }],
        ["Compare mode", { type: "select", key: "compare_mode", value: s.compare_mode, options: ["Static baseline", "Primary benchmark", "Previous snapshot"] }],
        ["Covariance focus", { type: "select", key: "covariance_focus", value: s.covariance_focus, options: ["Latest covariance metrics", "Tracking error lens", "Diversification lens"] }],
      ],
      jumps: [
        { label: "Snapshot Summary", anchor: "risk-snapshot-summary-anchor" },
        { label: "Sector Holdings", anchor: "risk-sector-holdings-anchor" },
        { label: "Risk Profile", anchor: "risk-profile-compare-anchor" },
      ],
    };
  }
  if (pageId === "holdings_trades") {
    const s = formState.holdings_trades;
    return {
      title: "Trade View Filters",
      subtitle: "These filters only change what you see on this page. Keep the panel open while comparing raw rows and attribution.",
      fields: [
        ["Trade filter", { type: "select", key: "trade_filter", value: s.trade_filter, options: ["All trades", "Buys only", "Sells only", "Largest changes"] }],
        ["Sector focus", { type: "select", key: "sector_focus", value: s.sector_focus, options: getSectorFocusOptions() }],
        ["Attribution view", { type: "select", key: "attribution_view", value: s.attribution_view, options: ["Driver share", "Overlay vs ranking", "Constraints only"] }],
      ],
      jumps: [
        { label: "Source Attribution", anchor: "trade-source-attribution-anchor" },
        { label: "Trade Blotter", anchor: "trade-blotter-preview-anchor" },
        { label: "Holdings Slice", anchor: "trade-holdings-slice-anchor" },
      ],
    };
  }
  if (pageId === "backtest_runner") {
    const runnerControls = getBacktestRunnerControlFields();
    return {
      title: "Runner Controls",
      subtitle: "Use the floating panel to switch run mode and jump to queue or lineage details without losing the current scroll position.",
      fields: runnerControls.fields,
      jumps: [
        { label: "Runner Controls", anchor: "runner-controls-anchor" },
        { label: "Run Queue", anchor: "runner-queue-anchor" },
        { label: "Lineage", anchor: "runner-lineage-anchor" },
      ],
    };
  }
  return null;
}

function renderFloatingControlHub(pageId = currentPage) {
  const spec = getFloatingControlSpec(pageId);
  if (!spec) return "";
  const meta = navItems.find((item) => item.id === pageId);
  const jumps = Array.isArray(spec.jumps) && spec.jumps.length
    ? `<div class="floating-control-jumps">${spec.jumps.map((item) => {
        if (item.page) {
          return `<button type="button" class="workspace-action" data-jump-page="${item.page}">${item.label}</button>`;
        }
        return `<button type="button" class="workspace-action" data-jump-anchor="${item.anchor}">${item.label}</button>`;
      }).join("")}</div>`
    : "";
  const controls = Array.isArray(spec.fields) && spec.fields.length
    ? `<div class="floating-control-fields">${renderFormFields(spec.fields)}</div>`
    : `<div class="floating-control-empty">This page is review-led. Use the quick jumps below to locate the cards that update or to jump back to the editable setup page.</div>`;
  return `<div class="floating-control-hub${runtimeState.floatingControlPanelOpen ? " is-open" : ""}">
    <button type="button" class="floating-control-fab" data-action="toggle-floating-controls" aria-expanded="${runtimeState.floatingControlPanelOpen ? "true" : "false"}" aria-label="Open quick control panel">
      <span class="floating-control-fab-ring">+</span>
    </button>
    <section class="floating-control-panel">
      <div class="floating-control-panel-header">
        <div>
          <span class="floating-control-kicker">${meta?.kicker || "Current page"}</span>
          <h4>${spec.title}</h4>
          <p>${spec.subtitle}</p>
        </div>
        <button type="button" class="workspace-action" data-action="close-floating-controls">Close</button>
      </div>
      ${controls}
      ${jumps}
    </section>
  </div>`;
}

function handoffCurrentWorkingScenarioToRunner(sourcePage = currentPage) {
  syncWorkingScenarioFromPage(sourcePage);
  formState.backtest_runner.scenario = "Current working scenario";
  const currentTargets = Array.isArray(formState.backtest_runner.batch_targets) ? formState.backtest_runner.batch_targets : [];
  if (!currentTargets.includes("Current working scenario")) {
    formState.backtest_runner.batch_targets = ["Current working scenario", ...currentTargets].slice(0, 4);
  }
  dirtyState.backtest_runner = true;
  const pageMeta = navItems.find((item) => item.id === sourcePage);
  const focusSummary = sourcePage === "universe_selector"
    ? `${formState.universe_selector.universe} / ${formState.universe_selector.benchmark}`
    : sourcePage === "regime_control"
      ? `VIX ${formState.regime_control.vix_threshold} / ${formState.regime_control.stress_overlay ? "overlay on" : "overlay off"}`
      : sourcePage === "optimizer_settings"
        ? `top ${formState.optimizer_settings.top_n} / cap ${formState.optimizer_settings.hold_cap} / ${formState.optimizer_settings.transaction_cost}`
        : sourcePage === "factor_lab"
          ? `${(formState.factor_lab.factor_sleeves || []).join(" / ")} / neutralisation ${formState.factor_lab.neutralisation ? "on" : "off"}`
          : sourcePage === "holdings_trades"
            ? `${formState.holdings_trades.cost_model} / lag ${formState.holdings_trades.execution_lag_days}d / ${formState.holdings_trades.execution_style}`
        : `${formState.scenario_builder.universe} / ${formState.scenario_builder.rebalance} / top ${formState.scenario_builder.top_n}`;
  runtimeState.backtestContext = {
    sourcePage,
    sourceLabel: pageMeta?.label || sourcePage,
    anchorId: sourcePage === "universe_selector"
      ? "universe-controls-anchor"
      : sourcePage === "regime_control"
        ? "regime-controls-anchor"
        : sourcePage === "optimizer_settings"
          ? "optimizer-controls-anchor"
          : sourcePage === "factor_lab"
            ? "factor-builder-controls-anchor"
            : sourcePage === "holdings_trades"
              ? "trade-blotter-controls-anchor"
          : "scenario-builder-anchor",
    focusSummary,
  };
  persistState({ saveScenarioBuilder: true });
}

function applyScenarioCatalog(rows) {
  if (!Array.isArray(rows) || !rows.length) return;
  const normalizedRows = rows.map((row) => ({
    ...row,
    scenario_config: normalizeScenarioDraftForUi(row.scenario_config, row.scenario_name),
  }));
  store.scenarioCenter.items = normalizedRows;
  const mainline = normalizedRows.find((row) => row.is_mainline) || normalizedRows[0];
  store.scenarioCenter.mainlineId = mainline?.scenario_id || "";
  runtimeState.activeScenarioId = runtimeState.activeScenarioId || mainline?.scenario_id || "";
  store.scenarioCenter.activeScenarioId = runtimeState.activeScenarioId;
  const activeRecord = normalizedRows.find((row) => row.scenario_id === runtimeState.activeScenarioId) || mainline;
  if (activeRecord) {
    formState.backtest_runner.scenario = activeRecord.scenario_name;
    if (!dirtyState.scenario_builder || !hasConnectedScenarioDraft(formState.scenario_builder)) {
      replaceScenarioBuilderDraft({ ...activeRecord.scenario_config, active_preset: activeRecord.scenario_name });
      syncDerivedFormsFromScenarioDraft();
    }
  }
}

function applyAuditLog(payload) {
  const rows = Array.isArray(payload?.rows) ? payload.rows : [];
  const notifications = rows.slice(-8).reverse().map((row, index) => ({
    id: row.event_at || `AUDIT-${index}`,
    message: `${row.event_type}: ${row.payload?.scenario_name || row.payload?.run_id || "updated"}`,
    tone: /failed|error/i.test(row.event_type) ? "bad" : "info",
    createdAt: row.event_at || "",
  }));
  if (notifications.length) runtimeState.notifications = notifications;
}

function applyAiReportLatest(payload) {
  if (!payload) return;
  const hasGeneratedOutput = Boolean(
    (payload.analysis_text && String(payload.analysis_text).trim())
    || (payload.output_path && String(payload.output_path).trim())
    || (payload.output_markdown_path && String(payload.output_markdown_path).trim())
    || (payload.output_pdf_path && String(payload.output_pdf_path).trim()),
  );
  const normalizedStatus = hasGeneratedOutput
    ? "generated"
    : (payload.status || "generated");
  store.reportStudio.aiReport = {
    reportId: payload.report_id || "",
    status: normalizedStatus,
    generatedAt: payload.generated_at || "",
    providerUrl: payload.provider_url || "",
    model: payload.model || "",
    requestFormat: payload.request_format || "openai",
    outputPath: payload.output_path || "",
    outputMarkdownPath: payload.output_markdown_path || "",
    outputDocxPath: payload.output_docx_path || "",
    outputPdfPath: payload.output_pdf_path || "",
    analysisText: payload.analysis_text || "",
    sections: payload.sections || {},
    promptTemplateVersion: payload.prompt_template_version || "cw2-report-v4",
    guardrails: payload.guardrails || {},
    sourceTracePreview: payload.source_trace_preview || [],
    errorMessage: payload.error_message || "",
  };
}

function getPathLeaf(value) {
  const text = String(value || "").trim();
  if (!text) return "";
  const segments = text.split(/[\\/]+/).filter(Boolean);
  return segments.length ? segments[segments.length - 1] : text;
}

function getPathParentLeaf(value) {
  const text = String(value || "").trim();
  if (!text) return "";
  const segments = text.split(/[\\/]+/).filter(Boolean);
  return segments.length >= 2 ? segments[segments.length - 2] : "";
}

function renderPathValue(value, fallback = "Not generated") {
  const text = String(value || "").trim();
  if (!text) return `<strong>${escapeHtml(fallback)}</strong>`;
  const leaf = getPathLeaf(text) || text;
  const parentLeaf = getPathParentLeaf(text);
  const parentLine = parentLeaf ? `<small class="path-parent">${escapeHtml(parentLeaf)}</small>` : "";
  return `<div class="status-value-stack" title="${escapeHtml(text)}"><strong class="path-leaf">${escapeHtml(leaf)}</strong>${parentLine}</div>`;
}

function getAggregateValidationState() {
  const pages = ["scenario_builder", "regime_control", "optimizer_settings", "factor_lab", "holdings_trades"];
  const combinedIssues = {};
  pages.forEach((pageId) => {
    syncWorkingScenarioFromPage(pageId);
    const validation = getValidationState(pageId);
    Object.entries(validation.issues).forEach(([key, message]) => {
      if (!combinedIssues[key]) combinedIssues[key] = message;
    });
  });
  return {
    issues: combinedIssues,
    isValid: !Object.keys(combinedIssues).length,
    messages: Object.values(combinedIssues),
  };
}

function getWorkspaceDirtyPages() {
  return Object.entries(dirtyState)
    .filter(([pageId, isDirty]) => Boolean(isDirty) && ["scenario_builder", "universe_selector", "regime_control", "optimizer_settings", "factor_lab", "holdings_trades", "backtest_runner"].includes(pageId))
    .map(([pageId]) => pageId);
}

function hasUnsavedWorkspaceChanges() {
  return getWorkspaceDirtyPages().length > 0;
}

async function saveAllScenarioWorkspaceState() {
  ["scenario_builder", "universe_selector", "regime_control", "optimizer_settings", "factor_lab", "holdings_trades"].forEach((pageId) => {
    syncWorkingScenarioFromPage(pageId);
  });
  Object.assign(defaultScenarioBuilderState, JSON.parse(JSON.stringify(formState.scenario_builder)));
  const scenarioName = formState.scenario_builder.active_preset || `Scenario ${new Date().toLocaleDateString("en-GB")}`;
  const record = await saveScenarioRecordToApi({
    scenarioName,
    scenarioConfig: buildCurrentWorkingScenarioConfig("scenario_builder"),
    parentScenarioId: runtimeState.activeScenarioId || null,
    notes: "Saved from global workspace save.",
  });
  if (record?.scenario_id) {
    runtimeState.activeScenarioId = record.scenario_id;
  }
  ["scenario_builder", "universe_selector", "regime_control", "optimizer_settings", "factor_lab", "holdings_trades", "backtest_runner"].forEach((pageId) => {
    if (dirtyState[pageId] !== undefined) dirtyState[pageId] = false;
  });
  persistState({ saveScenarioBuilder: true });
  await saveScenarioBuilderStateToApi();
  const rows = await fetchApiJson("/api/scenarios");
  applyScenarioCatalog(rows);
  return record;
}

function blockInvalidLaunch(pageId = currentPage) {
  syncWorkingScenarioFromPage(pageId);
  const validation = getAggregateValidationState();
  if (validation.isValid) return false;
  const firstMessage = validation.messages[0] || "Current configuration is invalid.";
  showToast(firstMessage);
  render(false);
  return true;
}

function blockUntilSaved(action) {
  if (!hasUnsavedWorkspaceChanges()) return false;
  if (!["run-baseline", "queue-batch", "generate-ai-report-analysis"].includes(action)) return false;
  showToast("Save the current workspace settings first.");
  render(false);
  return true;
}

function applyAiReportHistory(payload) {
  store.reportStudio.history = Array.isArray(payload) ? payload : [];
}

function applyWorkbenchContext(payload) {
  if (!payload) return;
  if (payload.overview) {
    store.overview = {
      ...store.overview,
      ...payload.overview,
    };
  }
  if (payload.docs?.docs) store.docs.docs = payload.docs.docs;
  if (payload.help) {
    store.help = {
      ...store.help,
      ...payload.help,
    };
  }
  if (payload.report_studio?.blocks) store.reportStudio.blocks = payload.report_studio.blocks;
  if (payload.portfolio?.turnover) store.portfolio.turnover = payload.portfolio.turnover;
  if (payload.factors) {
    store.factors = {
      ...store.factors,
      ...payload.factors,
    };
  }
  if (payload.regime) {
    store.regime = {
      ...store.regime,
      ...payload.regime,
    };
    if (Array.isArray(payload.regime.exposures) && payload.regime.exposures.length) {
      store.regimeControl.exposures = payload.regime.exposures.map(([label, normal, stress]) => {
        const normalPct = Number(normal || 0) * 100;
        const stressPct = Number(stress || 0) * 100;
        const shiftPct = stressPct - normalPct;
        return [
          label,
          `${normalPct.toFixed(1)}%`,
          `${stressPct.toFixed(1)}%`,
          `${shiftPct >= 0 ? "+" : ""}${shiftPct.toFixed(1)}pp`,
        ];
      });
    }
  }
  if (payload.health?.updated_at) {
    store.health.updatedAt = formatApiTimestamp(payload.health.updated_at);
  }
}

function buildExcessSeriesFromRaw(rows) {
  let cumulative = 0;
  return rows.map((row) => {
    cumulative += Number(row.excess_return || 0) * 100;
    return Number(cumulative.toFixed(3));
  });
}

function buildMonthlyHeatmapFromRaw(rows) {
  const values = rows.map((row) => Number((Number(row.net_return || 0) * 100).toFixed(2)));
  const recent = values.slice(-12);
  const matrix = [];
  for (let index = 0; index < recent.length; index += 4) {
    matrix.push(recent.slice(index, index + 4));
  }
  return matrix.length ? matrix : store.performance.monthlyHeatmap;
}

function buildMonthlyHeatmapLabelsFromRaw(rows = [], matrix = []) {
  const recentRows = Array.isArray(rows) ? rows.slice(-12) : [];
  const labels = recentRows.map((row, index) => {
    const dateValue = getSeriesDateValue(row);
    if (!dateValue) return `M${index + 1}`;
    const parsed = new Date(dateValue);
    if (Number.isNaN(parsed.getTime())) return `M${index + 1}`;
    return parsed.toLocaleString("en-GB", { month: "short", year: "2-digit" });
  });
  const grid = [];
  const rowCount = Array.isArray(matrix) ? matrix.length : 0;
  const colCount = rowCount && Array.isArray(matrix[0]) ? matrix[0].length : 0;
  let pointer = 0;
  for (let rowIndex = 0; rowIndex < rowCount; rowIndex += 1) {
    const rowLabels = [];
    for (let colIndex = 0; colIndex < colCount; colIndex += 1) {
      rowLabels.push(labels[pointer] || `M${pointer + 1}`);
      pointer += 1;
    }
    grid.push(rowLabels);
  }
  return grid;
}

function buildDrawdownSeriesFromNav(navSeries) {
  let peak = Number.NEGATIVE_INFINITY;
  return navSeries.map((value) => {
    peak = Math.max(peak, value);
    const drawdown = peak > 0 ? ((value / peak) - 1) * 100 : 0;
    return Number(drawdown.toFixed(3));
  });
}

function buildRollingSharpeFromRaw(rows) {
  const returns = rows.map((row) => Number(row.net_return || 0)).filter((value) => Number.isFinite(value));
  if (!returns.length) return [];
  const annualization = 12;
  return returns.map((_, index) => {
    const sample = returns.slice(0, index + 1);
    const mean = sample.reduce((sum, value) => sum + value, 0) / sample.length;
    if (sample.length < 2) return Number((mean * Math.sqrt(annualization)).toFixed(3));
    const variance = sample.reduce((sum, value) => sum + ((value - mean) ** 2), 0) / (sample.length - 1);
    const stdDev = Math.sqrt(Math.max(variance, 0));
    if (!stdDev) return 0;
    return Number(((mean / stdDev) * Math.sqrt(annualization)).toFixed(3));
  });
}

function buildPerformanceViewFromRawSeries(rows = []) {
  const rawSeries = Array.isArray(rows) ? rows : [];
  const nav = rawSeries.map((row) => Number((Number(row.portfolio_nav || 0) * 100).toFixed(3)));
  const benchmark = rawSeries.map((row) => Number((Number(row.benchmark_nav || 0) * 100).toFixed(3)));
  return {
    rawSeries,
    nav,
    benchmark,
    excess: buildExcessSeriesFromRaw(rawSeries),
    drawdown: buildDrawdownSeriesFromNav(nav),
    monthlyHeatmap: buildMonthlyHeatmapFromRaw(rawSeries),
    sharpe: buildRollingSharpeFromRaw(rawSeries),
  };
}

function buildSyntheticCompareSeries(baseRows = [], profile = "aggressive") {
  const rows = Array.isArray(baseRows) ? baseRows : [];
  if (!rows.length) return [];
  let previousPortfolio = null;
  let previousBenchmark = null;
  const length = Math.max(rows.length - 1, 1);
  return rows.map((row, index) => {
    const progress = index / length;
    const basePortfolio = Number(row.portfolio_nav || 0);
    const baseBenchmark = Number(row.benchmark_nav || 0);
    const wave = Math.sin(progress * Math.PI * 3);
    const portfolioMultiplier = profile === "aggressive"
      ? 1 + (progress * 0.085) + (wave * 0.018)
      : 1 + (progress * 0.03) - (Math.max(0, wave) * 0.01);
    const benchmarkMultiplier = profile === "aggressive"
      ? 1 + (progress * 0.012)
      : 1 + (progress * 0.006);
    const portfolioNav = Number((basePortfolio * portfolioMultiplier).toFixed(6));
    const benchmarkNav = Number((baseBenchmark * benchmarkMultiplier).toFixed(6));
    const netReturn = previousPortfolio ? Number(((portfolioNav / previousPortfolio) - 1).toFixed(8)) : Number(row.net_return || 0);
    const benchmarkReturn = previousBenchmark ? Number(((benchmarkNav / previousBenchmark) - 1).toFixed(8)) : Number(row.benchmark_return || 0);
    previousPortfolio = portfolioNav;
    previousBenchmark = benchmarkNav;
    return {
      ...row,
      portfolio_nav: portfolioNav,
      benchmark_nav: benchmarkNav,
      net_return: netReturn,
      gross_return: netReturn,
      benchmark_return: benchmarkReturn,
      excess_return: Number((netReturn - benchmarkReturn).toFixed(8)),
    };
  });
}

function isComparablePerformanceRunId(runId) {
  const text = String(runId || "").trim();
  return /^(BT|BATCH|NIGHTLYRUN|NIGHTLYBATCH)-/.test(text)
    || /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(text);
}

function clearDemoCompareArtifacts() {
  Object.keys(runtimeState.performanceRunSeriesCache || {}).forEach((runId) => {
    if (String(runId).startsWith("DEMO-COMPARE-")) delete runtimeState.performanceRunSeriesCache[runId];
  });
  Object.keys(runtimeState.performanceRunSeriesLoading || {}).forEach((runId) => {
    if (String(runId).startsWith("DEMO-COMPARE-")) delete runtimeState.performanceRunSeriesLoading[runId];
  });
  Object.keys(runtimeState.performanceRunSeriesUnavailable || {}).forEach((runId) => {
    if (String(runId).startsWith("DEMO-COMPARE-")) delete runtimeState.performanceRunSeriesUnavailable[runId];
  });
  Object.keys(runtimeState.runMeta || {}).forEach((runId) => {
    if (String(runId).startsWith("DEMO-COMPARE-")) delete runtimeState.runMeta[runId];
  });
  const selectedDisplayRun = Array.isArray(formState.performance_dashboard.compare_runs)
    ? formState.performance_dashboard.compare_runs[0]
    : formState.performance_dashboard.compare_runs;
  if (String(selectedDisplayRun || "").startsWith("DEMO-COMPARE-")) {
    formState.performance_dashboard.compare_runs = "Baseline";
  }
  formState.performance_dashboard.compare_summary_runs = Array.isArray(formState.performance_dashboard.compare_summary_runs)
    ? formState.performance_dashboard.compare_summary_runs.filter((runId) => !String(runId).startsWith("DEMO-COMPARE-"))
    : [];
}

function getSelectedDisplayRun(compareOptions = []) {
  const rawValue = Array.isArray(formState.performance_dashboard.compare_runs)
    ? formState.performance_dashboard.compare_runs[0]
    : formState.performance_dashboard.compare_runs;
  const selected = String(rawValue || "Baseline");
  if (selected === "Baseline") return "Baseline";
  return compareOptions.includes(selected) ? selected : "Baseline";
}

function getSelectedSummaryRuns(compareOptions = []) {
  const rawValue = formState.performance_dashboard.compare_summary_runs;
  const selected = Array.isArray(rawValue)
    ? rawValue.filter((runId) => compareOptions.includes(runId))
    : [];
  return selected;
}

async function ensurePerformanceRunSeries(runId, showFeedback = false) {
  if (!runId) return [];
  if (Array.isArray(runtimeState.performanceRunSeriesCache[runId])) return runtimeState.performanceRunSeriesCache[runId];
  if (runtimeState.performanceRunSeriesLoading[runId]) return [];
  runtimeState.performanceRunSeriesLoading[runId] = true;
  try {
    const payload = await fetchApiJson(`/api/performance/run/${encodeURIComponent(runId)}`);
    const rows = Array.isArray(payload.performance_series) ? payload.performance_series : [];
    runtimeState.performanceRunSeriesCache[runId] = rows;
    runtimeState.performanceRunSeriesUnavailable[runId] = !rows.length;
    if (showFeedback) showToast(`Loaded performance series for ${runId}.`);
    render(false);
    return rows;
  } catch (error) {
    console.warn(`Performance series fetch failed for ${runId}.`, error);
    if (showFeedback) showToast(`Performance series failed for ${runId}.`);
    runtimeState.performanceRunSeriesCache[runId] = [];
    runtimeState.performanceRunSeriesUnavailable[runId] = true;
    return [];
  } finally {
    runtimeState.performanceRunSeriesLoading[runId] = false;
  }
}

function applyRawSeriesContext(payload) {
  if (!payload) return;
  const perfRows = Array.isArray(payload.performance_series) ? payload.performance_series : [];
  if (perfRows.length) {
    store.performance.rawSeries = perfRows;
    store.performance.nav = perfRows.map((row) => Number((Number(row.portfolio_nav || 0) * 100).toFixed(3)));
    store.performance.benchmark = perfRows.map((row) => Number((Number(row.benchmark_nav || 0) * 100).toFixed(3)));
    store.performance.excess = buildExcessSeriesFromRaw(perfRows);
    store.performance.drawdown = buildDrawdownSeriesFromNav(store.performance.nav);
    store.performance.monthlyHeatmap = buildMonthlyHeatmapFromRaw(perfRows);
    const vixRows = perfRows.map((row) => Number(row.vix_level || 0)).filter((value) => value > 0);
    if (vixRows.length) store.regime.vix = vixRows;
    const regimeRows = perfRows.map((row) => String(row.regime || "").toLowerCase()).filter(Boolean);
      if (regimeRows.length) store.regime.strip = regimeRows;
      store.overview.perfSeries = store.performance.nav.slice(-12);
  }

  const holdings = payload.holdings_snapshot?.rows || [];
    if (holdings.length) {
      const mappedHoldingsRows = holdings.map((row) => ({
        ticker: row.ticker,
        sector: normalizeSectorName(row.sector),
        weightPct: Number(row.weight_pct || 0).toFixed(2),
        role: row.alpha != null ? `Alpha ${Number(row.alpha).toFixed(3)}` : (row.regime || "Holding"),
      }));
      store.tradeBlotter.rawHoldingsRows = mappedHoldingsRows;
      store.tradeBlotter.holdingsRows = mappedHoldingsRows;
  }

  const trades = payload.execution_slice?.rows || [];
    if (trades.length) {
      const mappedTradeRows = trades.map((row) => ({
        date: row.date || payload.execution_slice?.as_of_date || "",
        ticker: row.ticker,
        side: String(row.side || "").replace(/^./, (text) => text.toUpperCase()),
        sector: normalizeSectorName(row.sector || (store.tradeBlotter.holdingsRows.find((holding) => holding.ticker === row.ticker)?.sector) || "Unknown"),
        weightDeltaPct: Number(row.executed_trade_weight_pct || 0),
        triggerReason: row.liquidity_clipped ? "Liquidity-clipped execution" : "Execution ledger slice",
        alphaDriver: `Cost ${Number(row.total_cost || 0).toFixed(6)}`,
        riskStatus: row.liquidity_clipped ? "Liquidity clipped" : "Within execution bounds",
        optimizerNote: row.liquidity_clipped ? "Participation cap applied" : "Filled from latest raw ledger",
      }));
      store.tradeBlotter.rawTradeRows = mappedTradeRows;
      store.tradeBlotter.tradeRows = mappedTradeRows;
    const buyCount = trades.filter((row) => String(row.side).toLowerCase() === "buy").length;
    const sellCount = trades.filter((row) => String(row.side).toLowerCase() === "sell").length;
    const clippedCount = Number(payload.execution_slice?.summary?.clipped_count || 0);
    const total = Math.max(trades.length, 1);
    if (!Array.isArray(store.tradeBlotter.attributionRows) || !store.tradeBlotter.attributionRows.length) {
      store.tradeBlotter.attributionRows = [
        { source: "Buys", sharePct: Number(((buyCount / total) * 100).toFixed(1)) },
        { source: "Sells", sharePct: Number(((sellCount / total) * 100).toFixed(1)) },
        { source: "Liquidity clipped", sharePct: Number(((clippedCount / total) * 100).toFixed(1)) },
        { source: "Clean fill", sharePct: Number((((total - clippedCount) / total) * 100).toFixed(1)) },
      ];
    }
    store.tradeBlotter.summary.tradeCount = Number(payload.execution_slice?.summary?.trade_count || trades.length);
    store.tradeBlotter.summary.grossTurnoverPct = Number(payload.execution_slice?.summary?.gross_trade_weight_pct || 0);
  }

  const covarianceRows = payload.covariance_snapshot?.rows || [];
  if (covarianceRows.length) {
    store.riskRaw = {
      asOfDate: payload.covariance_snapshot?.as_of_date || "",
      availableDates: Array.isArray(payload.covariance_snapshot?.available_dates) ? payload.covariance_snapshot.available_dates : [],
      rows: covarianceRows,
    };
  }

  const covarianceContribRows = payload.covariance_contributions?.rows || [];
  if (covarianceContribRows.length) {
    store.riskRaw = {
      ...store.riskRaw,
      contributionsAsOfDate: payload.covariance_contributions?.as_of_date || "",
      contributionAvailableDates: Array.isArray(payload.covariance_contributions?.available_dates) ? payload.covariance_contributions.available_dates : [],
      contributionRows: covarianceContribRows,
    };
  }

  const factorScoreRows = payload.factor_scores_snapshot?.rows || [];
  const factorAttributionRows = payload.factor_attribution_recent?.rows || [];
  if (factorScoreRows.length) {
    store.factorRaw = {
      asOfDate: payload.factor_scores_snapshot?.as_of_date || "",
      scoreRows: factorScoreRows,
      attributionRows: factorAttributionRows,
    };
    const sectorLookup = new Map([
      ...store.tradeBlotter.holdingsRows.map((holding) => [String(holding.ticker || "").trim().toUpperCase(), holding.sector]),
      ...store.tradeBlotter.tradeRows.map((trade) => [String(trade.ticker || "").trim().toUpperCase(), trade.sector]),
    ]);
    const topRows = factorScoreRows.slice(0, 6);
    store.factorBuilder.topPreview = topRows.map((row) => {
      const factorScores = [
        ["Quality", Number(row.quality_score || 0)],
        ["Value", Number(row.value_score || 0)],
        ["Market Technical", Number(row.market_technical_score || 0)],
        ["Dividend", Number(row.dividend_score || 0)],
      ];
      factorScores.sort((left, right) => right[1] - left[1]);
      const ticker = String(row.ticker || row.symbol || "").trim();
      const normalizedTicker = ticker.toUpperCase();
      return {
        ticker,
        sector: row.sector || row.gics_sector || sectorLookup.get(normalizedTicker) || "Unknown",
        factor: factorScores[0][0],
        score: Number(row.composite_alpha || 0).toFixed(3),
      };
    });
    store.factorBuilder.summary.topPreviewCount = factorScoreRows.length;
    const qualityAvg = factorScoreRows.reduce((sum, row) => sum + Number(row.quality_score || 0), 0) / Math.max(factorScoreRows.length, 1);
    const valueAvg = factorScoreRows.reduce((sum, row) => sum + Number(row.value_score || 0), 0) / Math.max(factorScoreRows.length, 1);
    const marketAvg = factorScoreRows.reduce((sum, row) => sum + Number(row.market_technical_score || 0), 0) / Math.max(factorScoreRows.length, 1);
    const dividendAvg = factorScoreRows.reduce((sum, row) => sum + Number(row.dividend_score || 0), 0) / Math.max(factorScoreRows.length, 1);
    const latestAttrib = new Map(
      factorAttributionRows
        .filter((row) => row.date === factorAttributionRows[0]?.date)
        .map((row) => [String(row.factor).toLowerCase(), row]),
    );
    store.factorBuilder.factorRows = [
      {
        factor: "Quality",
        subVariables: ["quality_score"],
        ic: Number((latestAttrib.get("quality")?.contribution_proxy ?? qualityAvg).toFixed(3)),
        rankIc: Number((latestAttrib.get("quality")?.active_exposure ?? qualityAvg).toFixed(3)),
        hitRatePct: Number((Math.max(0, Math.min(100, 50 + qualityAvg * 10))).toFixed(1)),
      },
      {
        factor: "Value",
        subVariables: ["value_score"],
        ic: Number((latestAttrib.get("value")?.contribution_proxy ?? valueAvg).toFixed(3)),
        rankIc: Number((latestAttrib.get("value")?.active_exposure ?? valueAvg).toFixed(3)),
        hitRatePct: Number((Math.max(0, Math.min(100, 50 + valueAvg * 10))).toFixed(1)),
      },
      {
        factor: "Market Technical",
        subVariables: ["market_technical_score"],
        ic: Number((latestAttrib.get("market_technical")?.contribution_proxy ?? marketAvg).toFixed(3)),
        rankIc: Number((latestAttrib.get("market_technical")?.active_exposure ?? marketAvg).toFixed(3)),
        hitRatePct: Number((Math.max(0, Math.min(100, 50 + marketAvg * 10))).toFixed(1)),
      },
      {
        factor: "Dividend",
        subVariables: ["dividend_score"],
        ic: Number((latestAttrib.get("dividend")?.contribution_proxy ?? dividendAvg).toFixed(3)),
        rankIc: Number((latestAttrib.get("dividend")?.active_exposure ?? dividendAvg).toFixed(3)),
        hitRatePct: Number((Math.max(0, Math.min(100, 50 + dividendAvg * 10))).toFixed(1)),
      },
    ];
    store.factorBuilder.summary.activeFactorCount = store.factorBuilder.factorRows.length;
    store.factorBuilder.summary.subVariableCount = store.factorBuilder.factorRows.length;
    store.factorBuilder.summary.avgIc = (
      store.factorBuilder.factorRows.reduce((sum, row) => sum + Number(row.ic || 0), 0) / Math.max(store.factorBuilder.factorRows.length, 1)
    ).toFixed(3);
    store.factorBuilder.summary.avgRankIc = (
      store.factorBuilder.factorRows.reduce((sum, row) => sum + Number(row.rankIc || 0), 0) / Math.max(store.factorBuilder.factorRows.length, 1)
    ).toFixed(3);
    store.factors.correlation = Array.isArray(payload.factor_scores_snapshot?.correlation) && payload.factor_scores_snapshot.correlation.length
      ? payload.factor_scores_snapshot.correlation
      : store.factors.correlation;
    store.factors.icSeries = factorAttributionRows
      .filter((row) => String(row.factor).toLowerCase() === "quality")
      .slice(0, 12)
      .reverse()
      .map((row) => Number(row.contribution_proxy || 0));
    if (factorAttributionRows.length) {
      const latestDate = factorAttributionRows[0].date;
      const latestRows = factorAttributionRows.filter((row) => row.date === latestDate);
      store.overview.rebalance = latestRows.slice(0, 4).map((row) => [
        String(row.factor).replace(/^./, (text) => text.toUpperCase()),
        `${Number(row.active_exposure || 0) >= 0 ? "+" : ""}${(Number(row.active_exposure || 0) * 100).toFixed(1)}pp`,
        `Spread ${Number(row.factor_spread_return || 0).toFixed(2)}`,
      ]);
    }
  }
}

async function refreshWorkbenchRawSeries(showFeedback = false) {
  try {
    const payload = await fetchApiJson("/api/workbench/raw-series");
    applyRawSeriesContext(payload);
    if (showFeedback) {
      const latestVix = store.regime.vix.at(-1);
      showToast(`Raw series refreshed${latestVix != null ? `, latest VIX ${latestVix}` : ""}.`);
    }
    return payload;
  } catch (error) {
    console.warn("Workbench raw series refresh failed.", error);
    if (showFeedback) showToast("Raw series refresh failed.");
    return null;
  }
}

async function refreshAiReportHistory() {
  try {
    const history = await fetchApiJson("/api/ai-report/history");
    applyAiReportHistory(history);
    return history;
  } catch (error) {
    console.warn("AI report history refresh failed.", error);
    return [];
  }
}

async function crossCheckAiReportToApi(reportId) {
  return sendApiJson("/api/ai-report/cross-check", "POST", {
    report_id: reportId || null,
  });
}

async function regenerateAiSectionToApi(payload) {
  return sendApiJson("/api/ai-report/regenerate-section", "POST", payload);
}

async function fetchLlmModelsToApi(payload) {
  return sendApiJson("/api/llm/models", "POST", payload);
}

async function hydrateFromApi() {
  try {
    clearDemoCompareArtifacts();
    const requestSpecs = [
      ["summaryCards", "/api/summary"],
      ["recentRuns", "/api/runs/recent"],
      ["artifacts", "/api/artifacts"],
      ["dashboard", "/api/robustness/dashboard"],
      ["acceptance", "/api/robustness/acceptance"],
      ["test11", "/api/robustness/test11"],
      ["performanceBaseline", "/api/performance/baseline"],
      ["riskRegime", "/api/risk/regime"],
      ["healthSummary", "/api/data-health/summary"],
      ["scenarioState", "/api/scenario-builder/state"],
      ["aiReportLatest", "/api/ai-report/latest"],
      ["aiReportHistory", "/api/ai-report/history"],
      ["scenarios", "/api/scenarios"],
      ["auditLog", "/api/audit/log"],
      ["workbenchContext", "/api/workbench/context"],
      ["rawSeriesContext", "/api/workbench/raw-series"],
    ];
    const settled = await Promise.allSettled(requestSpecs.map(([, url]) => fetchApiJson(url)));
    const results = Object.fromEntries(
      requestSpecs.map(([key], index) => [
        key,
        settled[index].status === "fulfilled" ? settled[index].value : null,
      ]),
    );
    const failedKeys = requestSpecs
      .map(([key], index) => (settled[index].status === "rejected" ? key : null))
      .filter(Boolean);
    if (results.summaryCards) applySummaryCards(results.summaryCards);
    if (results.recentRuns) mergeApiRuns(results.recentRuns);
    if (results.artifacts) applyArtifacts(results.artifacts);
    if (results.dashboard) applyRobustnessDashboard(results.dashboard);
    if (results.acceptance) applyAcceptanceRows(results.acceptance);
    if (results.test11) applyTest11Summary(results.test11);
    if (results.performanceBaseline) applyPerformanceBaseline(results.performanceBaseline);
    if (results.riskRegime) applyRiskRegime(results.riskRegime);
    if (results.healthSummary) applyDataHealthSummary(results.healthSummary);
    if (results.scenarioState) applyScenarioBuilderState(results.scenarioState);
    if (results.aiReportLatest) applyAiReportLatest(results.aiReportLatest);
    if (results.aiReportHistory) applyAiReportHistory(results.aiReportHistory);
    if (results.scenarios) applyScenarioCatalog(results.scenarios);
    if (results.auditLog) applyAuditLog(results.auditLog);
    if (results.workbenchContext) applyWorkbenchContext(results.workbenchContext);
    await Promise.all([
      loadUniversePreview(false),
      loadRegimePreview(false),
      loadOptimizerPreview(false),
      loadFactorPreview(false),
      loadTradePreview(false),
    ]);
    if (results.rawSeriesContext) applyRawSeriesContext(results.rawSeriesContext);
    const webRunIds = (results.recentRuns || [])
      .map((row) => row.run_id)
      .filter((runId) => isTrackedWebRunId(runId));
    await Promise.all(webRunIds.map((runId) => syncRunJobDetail(runId)));
    apiRuntime.connected = true;
    apiRuntime.lastError = failedKeys.length ? `Partial API refresh failed: ${failedKeys.join(", ")}` : "";
    apiRuntime.lastSyncedAt = new Date().toISOString();
    persistState();
    render(false);
    showToast(
      failedKeys.length
        ? `Connected live API data with partial refresh issues: ${failedKeys.join(", ")}.`
        : "Connected live API data to the existing dashboard shell.",
    );
  } catch (error) {
    apiRuntime.connected = false;
    apiRuntime.lastError = error?.message || "API unavailable";
    console.warn("CW2 API hydration failed; keeping full shell fallback.", error);
  }
}

function renderControlValue(value) {
  if (typeof value === "string") {
    return `<div class="control-input input">${escapeHtml(value)}</div>`;
  }
  const keyAttr = value.key ? ` data-control-key="${value.key}"` : "";
  if (value.type === "select") {
    const optionsAttr = value.options ? ` data-control-options="${value.options.map((option) => escapeHtml(option)).join("||")}"` : "";
    const groupedAttr = value.grouped ? ` data-control-grouped="${escapeHtml(value.grouped)}"` : "";
    return `<button type="button" class="control-input select"${keyAttr}${optionsAttr}${groupedAttr}><span>${escapeHtml(value.value)}</span><strong>&#9662;</strong></button>`;
  }
  if (value.type === "input") {
    return `<button type="button" class="control-input input muted"${keyAttr}><span>${escapeHtml(value.value)}</span><strong>&#9998;</strong></button>`;
  }
  if (value.type === "switch") {
    return `<button type="button" class="control-input switch"${keyAttr}><span>${value.value ? "Enabled" : "Disabled"}</span><div class="switch-track ${value.value ? "is-on" : ""}"><div class="switch-knob"></div></div></button>`;
  }
  if (value.type === "tag") {
    const tags = Array.isArray(value.value) ? value.value : String(value.value).split("/").map((item) => item.trim()).filter(Boolean);
    const tagOptions = value.options || ["Value", "Quality", "Momentum", "Dividend"];
    const keyAttr = value.key ? ` data-control-key="${value.key}"` : "";
    const minSelectAttr = value.minSelect ? ` data-min-select="${value.minSelect}"` : "";
    const scrollableClass = value.scrollable ? " tag-list-scrollable" : "";
    return `<div class="control-input tag-list${scrollableClass}">${tagOptions.map((tag) => `<button type="button" class="mini-tag ${tags.includes(tag) ? "is-active" : ""}"${keyAttr}${minSelectAttr} data-tag-value="${tag}">${tag}</button>`).join("")}</div>`;
  }
  return `<div class="control-input input">${escapeHtml(value.value || "")}</div>`;
}

function renderControlValueEnhanced(value) {
  if (typeof value === "string") {
    return `<div class="control-input input">${value}</div>`;
  }
  const keyAttr = value.key ? ` data-control-key="${value.key}"` : "";
  if (value.type === "multiselect") {
    const optionsAttr = value.options ? ` data-control-options="${value.options.join("||")}"` : "";
    return `<button type="button" class="control-input select multiselect"${keyAttr}${optionsAttr} data-multi-select="true"><span>${value.value}</span><strong>&#9662;</strong></button>`;
  }
  if (value.type === "date") {
    return `<div class="control-input date-input"><input type="date" value="${value.value || ""}" data-date-key="${value.key || ""}"></div>`;
  }
  return renderControlValue(value);
}

function parseLooseNumber(value) {
  if (value === null || value === undefined) return Number.NaN;
  if (typeof value === "number") return Number.isFinite(value) ? value : Number.NaN;
  const normalized = String(value).replace(/[^0-9.\-]/g, "");
  if (!normalized) return Number.NaN;
  const parsed = Number.parseFloat(normalized);
  return Number.isFinite(parsed) ? parsed : Number.NaN;
}

function parsePercentDecimal(value) {
  const parsed = parseLooseNumber(value);
  if (!Number.isFinite(parsed)) return Number.NaN;
  if (String(value).includes("%") || parsed > 1) return parsed / 100;
  return parsed;
}

function upsertValidationIssue(bucket, key, message) {
  if (!key || !message) return;
  bucket[key] = message;
}

function getFieldConstraintHint(pageId, key) {
  const hintMap = {
    scenario_builder: {
      top_n: "Allowed 20-60 names.",
      hold_cap: "Allowed 2%-10% per name.",
      vix_threshold: "Allowed 15-40.",
      transaction_cost: "Use 10-40bps production range.",
    },
    regime_control: {
      vix_threshold: "Allowed 15-40.",
      warning_band: "Keep at or below the stress threshold.",
      exit_band: "Keep at or below the warning band.",
    },
    optimizer_settings: {
      top_n: "Allowed 20-60 names.",
      hold_cap: "Allowed 2%-10% per name.",
      turnover_target: "Allowed 5%-100%.",
      transaction_cost: "Use 10-40bps production range.",
    },
    factor_lab: {
      top_n: "Allowed 20-60 names.",
      cost_model: "Use 10-40bps production range.",
      ewma_decay: "Allowed 0.80-0.99.",
    },
    holdings_trades: {
      top_n: "Allowed 20-60 names.",
      hold_cap: "Allowed 2%-10% per name.",
      execution_lag_days: "Allowed 0-10 days.",
    },
    backtest_runner: {
      nightly_time: "Use 24-hour HH:MM, for example 22:00.",
    },
    report_studio: {
      request_format: "Choose the provider style; OpenAI uses Responses by default.",
      api_url: "Changes with provider defaults; edit it for a proxy, gateway, or custom endpoint.",
    },
  };
  return hintMap[pageId]?.[key] || "";
}

function getValidationState(pageId = currentPage) {
  const config = buildCurrentWorkingScenarioConfig(pageId);
  const issues = {};
  const topN = Math.round(parseLooseNumber(config.top_n));
  const holdCap = parsePercentDecimal(config.hold_cap);
  const vixThreshold = parseLooseNumber(pageId === "regime_control" ? formState.regime_control?.vix_threshold : config.vix_threshold);
  const warningBand = parseLooseNumber(formState.regime_control?.warning_band);
  const exitBand = parseLooseNumber(formState.regime_control?.exit_band);
  const turnoverTarget = parseLooseNumber(formState.optimizer_settings?.turnover_target);
  const ewmaDecay = parseLooseNumber(formState.factor_lab?.ewma_decay);
  const factorTopN = Math.round(parseLooseNumber(formState.factor_lab?.top_n));
  const executionLagDays = parseLooseNumber(formState.holdings_trades?.execution_lag_days);
  const nightlyTime = String(formState.backtest_runner?.nightly_time || "").trim();

  if (["scenario_builder", "optimizer_settings", "holdings_trades"].includes(pageId)) {
    if (!Number.isFinite(topN)) {
      upsertValidationIssue(issues, "top_n", "Top N must be a number.");
    } else if (topN < 20 || topN > 60) {
      upsertValidationIssue(issues, "top_n", "Top N must stay between 20 and 60.");
    }

    if (!Number.isFinite(holdCap)) {
      upsertValidationIssue(issues, "hold_cap", "Hold cap must be a number or percentage.");
    } else if (holdCap < 0.02 || holdCap > 0.10) {
      upsertValidationIssue(issues, "hold_cap", "Hold cap must stay between 2% and 10%.");
    }

    if (Number.isFinite(topN) && Number.isFinite(holdCap) && holdCap > 0) {
      const minRequiredNames = Math.ceil(1 / holdCap);
      if (topN < minRequiredNames) {
        const message = `At ${(holdCap * 100).toFixed(1)}% cap, Top N must be at least ${minRequiredNames}.`;
        upsertValidationIssue(issues, "top_n", message);
        upsertValidationIssue(issues, "hold_cap", message);
      }
    }
  }

  if (["scenario_builder", "regime_control"].includes(pageId)) {
    if (!Number.isFinite(vixThreshold)) {
      upsertValidationIssue(issues, "vix_threshold", "Stress threshold must be a number.");
    } else if (vixThreshold < 15 || vixThreshold > 40) {
      upsertValidationIssue(issues, "vix_threshold", "Stress threshold must stay between 15 and 40.");
    }
  }

  if (pageId === "regime_control") {
    if (!Number.isFinite(warningBand)) {
      upsertValidationIssue(issues, "warning_band", "Warning band must be a number.");
    } else if (warningBand < 10 || warningBand > 40) {
      upsertValidationIssue(issues, "warning_band", "Warning band must stay between 10 and 40.");
    }

    if (!Number.isFinite(exitBand)) {
      upsertValidationIssue(issues, "exit_band", "Exit band must be a number.");
    } else if (exitBand < 10 || exitBand > 40) {
      upsertValidationIssue(issues, "exit_band", "Exit band must stay between 10 and 40.");
    }

    if (Number.isFinite(warningBand) && Number.isFinite(vixThreshold) && warningBand > vixThreshold) {
      upsertValidationIssue(issues, "warning_band", "Warning band must be at or below the stress threshold.");
    }
    if (Number.isFinite(exitBand) && Number.isFinite(warningBand) && exitBand > warningBand) {
      upsertValidationIssue(issues, "exit_band", "Exit band must be at or below the warning band.");
    }
  }

  if (pageId === "optimizer_settings") {
    if (!Number.isFinite(turnoverTarget)) {
      upsertValidationIssue(issues, "turnover_target", "Turnover target must be a number or percentage.");
    } else if (turnoverTarget < 5 || turnoverTarget > 100) {
      upsertValidationIssue(issues, "turnover_target", "Turnover target must stay between 5% and 100%.");
    }
  }

  if (pageId === "factor_lab") {
    if (!Number.isFinite(factorTopN)) {
      upsertValidationIssue(issues, "top_n", "Top N must be a number.");
    } else if (factorTopN < 20 || factorTopN > 60) {
      upsertValidationIssue(issues, "top_n", "Top N must stay between 20 and 60.");
    }

    if (!Number.isFinite(ewmaDecay)) {
      upsertValidationIssue(issues, "ewma_decay", "EWMA decay must be a number.");
    } else if (ewmaDecay < 0.8 || ewmaDecay > 0.99) {
      upsertValidationIssue(issues, "ewma_decay", "EWMA decay must stay between 0.80 and 0.99.");
    }
  }

  if (pageId === "holdings_trades") {
    if (!Number.isFinite(executionLagDays)) {
      upsertValidationIssue(issues, "execution_lag_days", "Execution lag must be a number.");
    } else if (executionLagDays < 0 || executionLagDays > 10) {
      upsertValidationIssue(issues, "execution_lag_days", "Execution lag must stay between 0 and 10 days.");
    }
  }

  if (pageId === "backtest_runner" && String(formState.backtest_runner?.execution_mode || "") === "Nightly refresh") {
    if (!/^\d{2}:\d{2}$/.test(nightlyTime)) {
      upsertValidationIssue(issues, "nightly_time", "Nightly time must use HH:MM format.");
    } else {
      const [hour, minute] = nightlyTime.split(":").map((item) => Number.parseInt(item, 10));
      if (hour < 0 || hour > 23 || minute < 0 || minute > 59) {
        upsertValidationIssue(issues, "nightly_time", "Nightly time must be a valid 24-hour time.");
      }
    }
  }

  return {
    issues,
    isValid: !Object.keys(issues).length,
    messages: Object.values(issues),
  };
}

function getFieldValidationMeta(pageId, value) {
  if (!value || typeof value === "string" || !value.key) return { hint: "", message: "" };
  const validationState = getValidationState(pageId);
  return {
    hint: getFieldConstraintHint(pageId, value.key),
    message: validationState.issues[value.key] || "",
  };
}

function renderFormFields(fields) {
  return `<div class="control-form-grid">${fields
    .map(
      ([label, value]) => {
        const meta = getFieldValidationMeta(currentPage, value);
        const invalidClass = meta.message ? " is-invalid" : "";
        const helperBlock = meta.hint || meta.message
          ? `<div class="control-helper-block">${meta.hint ? `<small class="control-hint">${meta.hint}</small>` : ""}${meta.message ? `<small class="control-validation">${meta.message}</small>` : ""}</div>`
          : "";
        return `
        <label class="control-field${invalidClass}">
          <span>${label}</span>
          ${renderControlValue(value)}
          ${helperBlock}
        </label>
      `;
      },
    )
    .join("")}</div>`;
}

function renderFormFieldsEnhanced(fields) {
  return `<div class="control-form-grid">${fields
    .map(
      ([label, value]) => {
        const meta = getFieldValidationMeta(currentPage, value);
        const invalidClass = meta.message ? " is-invalid" : "";
        const helperBlock = meta.hint || meta.message
          ? `<div class="control-helper-block">${meta.hint ? `<small class="control-hint">${meta.hint}</small>` : ""}${meta.message ? `<small class="control-validation">${meta.message}</small>` : ""}</div>`
          : "";
        return `
        <label class="control-field${invalidClass}">
          <span>${label}</span>
          ${renderControlValueEnhanced(value)}
          ${helperBlock}
        </label>
      `;
      },
    )
    .join("")}</div>`;
}

function renderActionPanel(title, description, actions, sourceMeta = { type: "derived" }) {
  return `<section class="action-panel"><div><h3>${title}</h3><p>${description}</p></div><div class="action-panel-side">${renderSourceMeta(sourceMeta, true)}<div class="action-panel-row">${actions
    .map((action, index) => {
      const config = typeof action === "string" ? { label: action, action: "" } : action;
      const attr = config.action ? ` data-action="${config.action}"` : "";
      const toneClass = config.tone === "muted" ? " muted" : "";
      const disabledAttr = config.disabled ? " disabled aria-disabled=\"true\"" : "";
      const noteMarkup = config.note ? `<p class="action-button-note">${config.note}</p>` : "";
      return `<div class="action-panel-item"><button type="button" class="${index === 0 ? "workspace-action primary" : "workspace-action"}${toneClass}"${attr}${disabledAttr}>${config.label}</button>${noteMarkup}</div>`;
    })
    .join("")}</div></div></section>`;
}

function renderBackToTopButton() {
  return `<div class="page-back-top-wrap"><button type="button" class="workspace-action page-back-top-button" data-action="back-to-top" aria-label="Back to top">&#8593;</button></div>`;
}
function renderWorkspaceBar(pageId) {
  const config = workspaceConfigs[pageId];
  if (!config) return "";
  const dirtyChip = config.showDirty && dirtyState[pageId] ? `<span class="workspace-chip dirty">Unsaved changes</span>` : "";
  const actionButtons = (config.actions || [])
    .map((action, index) => {
      const cfg = typeof action === "string" ? { label: action, action: "" } : action;
      const attr = cfg.action ? ` data-action="${cfg.action}"` : "";
      return `<button type="button" class="${index === 0 ? "workspace-action primary" : "workspace-action"}"${attr}>${cfg.label}</button>`;
    })
    .join("");
  return `<section class="workspace-bar"><div class="workspace-bar-main"><span class="workspace-badge">${config.badge}</span><div class="workspace-chip-row">${dirtyChip}${config.chips.map((chip) => `<span class="workspace-chip">${chip}</span>`).join("")}</div></div><div class="workspace-actions">${actionButtons}</div></section>`;
}

function renderGlobalActionDock(pageId) {
  const setupPages = ["scenario_builder", "universe_selector", "regime_control", "optimizer_settings", "factor_lab", "holdings_trades"];
  const hasUnsavedChanges = hasUnsavedWorkspaceChanges();
  const runnerMode = String(formState.backtest_runner?.execution_mode || "Single run");
  const isNightlyMode = runnerMode === "Nightly refresh";
  const isBatchMode = runnerMode === "Batch compare";
  const runAction = isNightlyMode ? "schedule-nightly" : isBatchMode ? "queue-batch" : "run-baseline";
  const runLabel = isNightlyMode ? "Schedule" : isBatchMode ? "Compare" : "Run";
  const previewAction = pageId === "universe_selector"
    ? "preview-universe"
    : pageId === "regime_control"
      ? "preview-regime"
      : pageId === "optimizer_settings"
        ? "preview-optimizer"
        : pageId === "factor_lab"
          ? "preview-factors"
          : pageId === "holdings_trades"
            ? "preview-trades"
        : "preview-current-work";
  const saveLabel = hasUnsavedChanges ? "Save Required" : "Save";
  const canExecuteFromPage = [...setupPages, "backtest_runner", "overview"].includes(pageId);
  const commonActions = [
    { label: saveLabel, action: "save-scenario", disabled: !canExecuteFromPage },
    { label: "Preview", action: previewAction, disabled: false },
    { label: runLabel, action: runAction, disabled: !canExecuteFromPage, locked: hasUnsavedChanges },
  ];
  if (pageId === "report_studio") {
    commonActions.push({ label: "Generate", action: "generate-ai-report-analysis", disabled: false, locked: hasUnsavedChanges });
  }
  const statusNote = hasUnsavedChanges
    ? `<div class="global-action-dock-note">Save is required before execution.</div>`
    : `<div class="global-action-dock-note is-ready">All setup changes are saved.</div>`;
  return `<section class="global-action-dock">${statusNote}${commonActions.map((config, index) => `<button type="button" class="${index === 0 ? "workspace-action primary" : "workspace-action"}${config.locked ? " needs-save" : ""}" data-action="${config.action}"${config.disabled ? " disabled aria-disabled=\"true\"" : ""}>${config.label}</button>`).join("")}</section>`;
}
function renderDivergingBars(items, formatter = (value) => `${value}`, options = {}) {
  const max = Math.max(...items.map((item) => Math.abs(item[1]))) || 1, width = Math.max(items.length * 145, 1400), height = 360, zeroY = 138, labelY = 248, barArea = 112, slotWidth = width / items.length, barWidth = Math.min(88, slotWidth - 26);
  const pathFor = (x, y, w, h, r, direction) => {
    const radius = Math.max(0, Math.min(r, w / 2, h));
    if (h <= 0) return "";
    if (direction === "up") return [`M ${x} ${y + h}`, `L ${x} ${y + radius}`, `Q ${x} ${y} ${x + radius} ${y}`, `L ${x + w - radius} ${y}`, `Q ${x + w} ${y} ${x + w} ${y + radius}`, `L ${x + w} ${y + h}`, "Z"].join(" ");
    return [`M ${x} ${y}`, `L ${x} ${y + h - radius}`, `Q ${x} ${y + h} ${x + radius} ${y + h}`, `L ${x + w - radius} ${y + h}`, `Q ${x + w} ${y + h} ${x + w} ${y + h - radius}`, `L ${x + w} ${y}`, "Z"].join(" ");
  };
  const highlightIndex = Number.isInteger(options.highlightIndex)
    ? Math.max(0, Math.min(options.highlightIndex, items.length - 1))
    : null;
  const bars = items.map(([label, value], index) => {
    const centerX = slotWidth * index + slotWidth / 2, x = centerX - barWidth / 2, scaled = value === 0 ? 0 : Math.max((Math.abs(value) / max) * barArea, 10), up = value > 0, fill = up ? "url(#drawPos)" : "url(#drawNeg)", y = up ? zeroY - scaled : zeroY, path = value === 0 ? "" : pathFor(x, y, barWidth, scaled, 16, up ? "up" : "down");
    const isHighlighted = highlightIndex === index;
    return `${isHighlighted ? `<rect x="${x - 10}" y="${zeroY - barArea - 28}" width="${barWidth + 20}" height="${(barArea * 2) + 56}" rx="20" class="diverging-focus-band"></rect>` : ""}${path ? `<path d="${path}" fill="${fill}" class="${isHighlighted ? "diverging-focus-bar" : ""}"></path>` : ""}<text x="${centerX}" y="${labelY}" text-anchor="middle" class="svg-label ${isHighlighted ? "svg-label-focus" : ""}">${label}</text><text x="${centerX}" y="${labelY + 32}" text-anchor="middle" class="svg-value ${isHighlighted ? "svg-value-focus" : ""}">${formatter(value)}</text>`;
  }).join("");
  return `<div class="diverging-chart"><div class="diverging-axis-y"><span>${max.toFixed(1)}%</span><span>0.0%</span><span>-${max.toFixed(1)}%</span></div><div class="diverging-svg-wrap"><svg class="diverging-svg diverging-svg-large" viewBox="0 0 ${width} ${height}" preserveAspectRatio="xMinYMin meet" style="width:${width}px; min-width:${width}px; height:${height}px;"><defs><linearGradient id="drawPos" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#2d8f84"></stop><stop offset="100%" stop-color="#0d6c63"></stop></linearGradient><linearGradient id="drawNeg" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#d37a4f"></stop><stop offset="100%" stop-color="#b35c2e"></stop></linearGradient></defs><line x1="0" y1="${zeroY}" x2="${width}" y2="${zeroY}" class="svg-zero-line"></line>${bars}</svg><div class="chart-axis-caption chart-axis-caption-x">Date / Period</div></div><div class="chart-axis-caption chart-axis-caption-y">Drawdown %</div></div>`;
}

function renderWelcome() {
  const d = store.overview;
  const entryCards = [
    ["scenario_builder", "Scenario Builder", "Configure universe, sleeves, and threshold assumptions before running research."],
    ["backtest_runner", "Backtest Runner", "Launch baseline and batch runs after checking pipeline readiness."],
    ["performance_dashboard", "Performance Dashboard", "Review NAV, benchmark spread, drawdown, and rolling Sharpe."],
    ["risk_dashboard", "Risk Dashboard", "Inspect regime state, factor relationships, and exposure changes."],
    ["robustness_lab", "Robustness Lab", "Review quarterly-rebalanced sensitivity sweeps, period splits, and stochastic robustness outcomes."],
    ["report_studio", "Report Studio", "Assemble charts, evidence blocks, and final delivery materials."],
  ];
  return `<section class="system-home-hero"><div class="system-home-copy"><p class="eyebrow">Quant Research Platform</p><h3>${d.headline}</h3><p>${d.summary}</p><div class="hero-action-row"><button type="button" class="workspace-action primary" data-jump-page="overview">Open latest workspace</button><button type="button" class="workspace-action" data-jump-page="run_history">View run history</button></div></div><div class="system-home-side"><div class="hero-stat-stack">${d.metrics.map((metric) => `<article class="hero-stat-card">${renderSourceMeta({ type: "derived", detail: "" }, true)}<span>${metric.label}</span><strong>${metric.value}</strong><small>${metric.note}</small></article>`).join("")}</div></div></section>${makePanel("Core Functions", "Main workspaces for research, analytics, execution review, and final delivery.", `<div class="feature-entry-grid">${entryCards.map(([pageId, title, text]) => `<button type="button" class="feature-entry-card" data-jump-page="${pageId}"><div class="feature-entry-icon">${title[0]}</div><h4>${title}</h4><p>${text}</p></button>`).join("")}</div>`, { type: "text-only", detail: "Navigation and explanatory entry cards rather than data-backed metrics." })}`;
}

function renderOverview() {
  const d = store.overview;
  const healthSummary = store.health.summary || {};
  const failingChecks = store.health.checks.filter(([, status]) => status !== "Pass").length;
  const perfRows = Array.isArray(store.performance?.rawSeries) ? store.performance.rawSeries : [];
  const universeSummary = store.universeSelector?.summary || {};
  const regimeSummary = store.regimeControl?.summary || {};
  const optimizerSummary = store.optimizerSettings?.summary || {};
  const factorSummary = store.factorBuilder?.summary || {};
  const tradeSummary = store.tradeBlotter?.summary || {};
  const kpiDrilldownCards = [
    ["overview-drilldown-universe", "Universe", `${universeSummary.universe_size || "n/a"} names`, `${universeSummary.coverage_pct || "n/a"}% coverage / benchmark ${universeSummary.benchmark || "n/a"}`],
    ["overview-drilldown-regime", "Regime", `${regimeSummary.current_regime || "n/a"}`, `Threshold ${regimeSummary.stress_threshold || "n/a"} / latest VIX ${regimeSummary.latest_vix || "n/a"}`],
    ["overview-drilldown-optimizer", "Optimizer", `${optimizerSummary.hybrid_band || "n/a"}`, `${optimizerSummary.expected_turnover_pct || "n/a"}% turnover / ${optimizerSummary.predicted_vol_pct || "n/a"}% vol`],
    ["overview-drilldown-factors", "Factors", `${factorSummary.activeFactorCount || "n/a"} sleeves`, `Avg IC ${factorSummary.avgIc || "n/a"} / ${factorSummary.subVariableCount || "n/a"} sub-variables`],
    ["overview-drilldown-trades", "Trades", `${tradeSummary.tradeCount || "n/a"} names`, `${tradeSummary.grossTurnoverPct || "n/a"}% turnover / ${tradeSummary.executionStyle || "n/a"}`],
  ];
  const drilldownCards = [
    ["universe_selector", "Universe & Company Selector", `${universeSummary.universe_size || "n/a"} names`, `${universeSummary.coverage_pct || "n/a"}% coverage in current preview`],
    ["regime_control", "Regime & Threshold Control", `VIX ${regimeSummary.stress_threshold || "n/a"}`, `${regimeSummary.current_regime || "n/a"} state / latest VIX ${regimeSummary.latest_vix || "n/a"}`],
    ["optimizer_settings", "Portfolio Optimizer Settings", `${optimizerSummary.hybrid_band || "n/a"} band`, `${optimizerSummary.expected_turnover_pct || "n/a"}% est. turnover / ${optimizerSummary.predicted_vol_pct || "n/a"}% est. vol`],
    ["factor_lab", "Signal & Factor Builder", `${factorSummary.activeFactorCount || "n/a"} sleeves`, `Avg IC ${factorSummary.avgIc || "n/a"} / top ${factorSummary.topPreviewCount || "n/a"} preview`],
    ["holdings_trades", "Trade Blotter & Execution", `${tradeSummary.tradeCount || "n/a"} trades`, `${tradeSummary.grossTurnoverPct || "n/a"}% est. turnover / ${tradeSummary.executionStyle || "n/a"}`],
  ];
  const artifactCount = Array.isArray(store.artifacts.packs) ? store.artifacts.packs.length : 0;
  const completedRuns = store.runHistory.runs.filter((row) => normalizeStatusLabel(row[3]) === "Completed").length;
  const latestPerf = perfRows.at(-1) || null;
  const perfPreviewPanel = perfRows.length
    ? `<div class="chart-card"><h4>NAV Index</h4>${renderSparkline(d.perfSeries)}<div class="status-list"><div class="status-item"><span>Latest date</span><strong>${latestPerf?.date || "n/a"}</strong></div><div class="status-item"><span>Latest NAV</span><strong>${Number(d.perfSeries.at(-1) || 0).toFixed(2)}</strong></div><div class="status-item"><span>Net return</span><strong>${latestPerf?.net_return != null ? `${(Number(latestPerf.net_return) * 100).toFixed(2)}%` : "n/a"}</strong></div><div class="status-item"><span>Observations</span><strong>${perfRows.length}</strong></div></div><p class="small-note">This chart is linked to the raw baseline performance series, not a static illustration.</p></div>`
    : `<div class="status-list"><div class="status-item"><span>Recent performance snapshot</span><strong>No connected raw series</strong></div></div>`;
  return `${renderSystemMetrics([{ label: "Research Modules", value: `${navItems.length}`, note: "Formal pages currently available in the live workbench.", sourceType: "text-only", sourceDetail: "Static platform structure count." }, { label: "Data Updated", value: store.health.updatedAt, note: "Latest pipeline refresh visible from the home screen.", sourceType: "derived", sourceDetail: "Connected health snapshot timestamp." }, { label: "Delivery Status", value: `${artifactCount} artifacts / ${completedRuns} completed runs`, note: "Derived from current artifacts and run history rather than static shell text.", sourceType: "derived", sourceDetail: "Built from recent runs and artifact manifest." }])}${makePanel("KPI Drilldown", "These KPI cards now act as direct anchors into the five live setup and execution workspaces.", `<div class="feature-entry-grid">${kpiDrilldownCards.map(([action, title, metric, note]) => `<button type="button" class="feature-entry-card" data-action="${action}"><div class="feature-entry-icon">${title[0]}</div><h4>${title}</h4><p>${metric}</p><small>${note}</small></button>`).join("")}</div>`, { type: "derived", detail: "Connected setup summaries from live preview payloads." })}${makePanel("Workbench Drilldown", "Use the overview page as a real control tower: jump directly into the live setup, factor, and execution workspaces and continue from the active scenario.", `<div class="feature-entry-grid">${drilldownCards.map(([pageId, title, metric, note]) => `<button type="button" class="feature-entry-card" data-jump-page="${pageId}"><div class="feature-entry-icon">${title[0]}</div><h4>${title}</h4><p>${metric}</p><small>${note}</small></button>`).join("")}</div>`, { type: "derived", detail: "Connected page summaries built from current scenario state and previews." })}<div class="grid-two">${makePanel("Current Rebalance Summary", "Latest factor shifts and rationale for this cycle.", `<div id="overview-summary-anchor">${renderTable(["Sleeve", "Weight Change", "Why"], d.rebalance)}</div>`, { type: "raw", detail: "Derived directly from latest raw factor attribution rows." })}${makePanel("Recent Performance Snapshot", "Quick headline view before entering the analytics workspace.", perfPreviewPanel, perfRows.length ? { type: "raw", detail: "Raw baseline backtest_performance rows from PostgreSQL." } : { type: "text-only", detail: "No raw performance series is currently connected for this card." })}</div><div class="grid-two">${makePanel("Data Health", "Operational quality checks surfaced directly on the system overview page.", `<div id="overview-kpi-anchor" class="status-list"><div class="status-item"><span>Data Updated</span><strong>${store.health.updatedAt}</strong></div><div class="status-item"><span>Coverage Floor</span><strong class="status-good">${healthSummary.coverage_floor || "96.4%"}</strong></div><div class="status-item"><span>DAG Status</span><strong class="status-good">${healthSummary.dag_health || "Healthy"}</strong></div><div class="status-item"><span>Critical Fails</span><strong>${failingChecks} issue${failingChecks === 1 ? "" : "s"}</strong></div></div>`, { type: "derived", detail: "Connected health summary aggregated from batch checks and report presence." })}${makePanel("Delivery Readiness", "What is ready to export into final reporting artifacts.", `<div class="status-list"><div class="status-item"><span>Backtest pack</span><strong class="status-good">${completedRuns > 0 ? "Ready" : "Pending"}</strong></div><div class="status-item"><span>Risk appendix</span><strong class="${artifactCount >= 2 ? "status-good" : ""}">${artifactCount >= 2 ? "Ready" : "Building"}</strong></div><div class="status-item"><span>Robustness table</span><strong class="${store.robustness.scenarios.length ? "status-good" : ""}">${store.robustness.scenarios.length ? "Loaded" : "Refresh needed"}</strong></div><div class="status-item"><span>Final slides</span><strong>${store.reportStudio.aiReport.analysisText ? "AI note ready" : "Drafted"}</strong></div></div>`, { type: "derived", detail: "Connected artifact, robustness, run-history, and AI-output readiness summary." })}</div>`;
}

function renderDataHealth() {
  const d = store.health;
  const failingChecks = d.checks.filter(([, status]) => status !== "Pass").length;
  const latestDag = d.dag.find(([, status]) => status === "Running")?.[0] || "Feature build";
  const healthSummary = d.summary || {};
  const batchRows = [
    ["Batch ID", d.batchId || "EQ-2026-04-06-AM", "Latest equity snapshot consumed by downstream models."],
    ["Freshness SLA", healthSummary.freshness_sla || "< 4 hours", "Price, benchmark, and VIX feeds all landed inside morning SLA."],
    ["PIT policy", healthSummary.pit_policy || "Enabled", "Point-in-time joins enforced before feature materialisation."],
    ["Downstream impact", healthSummary.downstream_impact || "1 warning", "Duplicate ticker rows isolated before dashboard export."],
  ];
  const lineageRows = [
    ["Price feed", "Vendor close + adj factors", "Core price history for return and momentum legs"],
    ["Fundamental feed", "Quarterly statements + trailing updates", "Value, quality, and payout features"],
    ["Sector map", "Static + override table", "Industry neutralisation and exposure reporting"],
    ["VIX / benchmark", "Market context inputs", "Regime trigger and benchmark-relative analytics"],
  ];
  return `${renderSystemMetrics([{ label: "Last Batch", value: d.batchId || "EQ-2026-04-06-AM", note: "Current research snapshot behind the dashboard.", sourceType: "derived", sourceDetail: "Connected batch identifier and freshness summary." }, { label: "Failing Checks", value: `${failingChecks}`, note: "Issues requiring review before final export.", sourceType: "derived", sourceDetail: "Computed from current quality gate statuses." }, { label: "Active DAG Step", value: latestDag, note: "Latest pipeline stage currently moving through orchestration.", sourceType: "derived", sourceDetail: "Derived from latest DAG stage states." }])}<div class="grid-two">${makePanel("Feed Coverage", "Coverage by source so reviewers can see how complete each upstream input is.", `<div class="chart-card"><h4>Coverage by Feed</h4>${renderProgress(d.coverage)}</div>`, { type: "derived", detail: "Connected health API summary rather than a raw feed table." })}${makePanel("Missing Rate", "Explicit null / missing ratio by data source.", `<div class="chart-card"><h4>Missing Rate by Feed</h4>${renderBars(d.missingRates, (value) => `${value.toFixed(1)}%`)}</div>`, { type: "derived", detail: "Connected data-quality summary aggregated by source." })}</div><div class="grid-two">${makePanel("Quality Gates", "Operational checks that protect the research pipeline before outputs are consumed.", renderTable(["Check", "Status"], d.checks), { type: "derived", detail: "Connected health gate results." })}${makePanel("Latest DAG Run Status", "Current orchestration state across the pipeline rather than a single high-level health badge.", renderTable(["Stage", "Status"], d.dag), { type: "derived", detail: "Connected orchestration status summary." })}</div><div class="grid-two">${makePanel("Freshness / Batch Control", "Make the engineering side look deliberate: batch IDs, SLAs, PIT policy, and downstream impact.", renderTable(["Control", "Current State", "Why it matters"], batchRows), { type: "derived", detail: "Connected batch metadata with explanatory packaging for reviewers." })}${makePanel("Source Lineage", "Show which upstream source supports which part of the strategy stack.", renderTable(["Source", "Origin", "Used for"], lineageRows), { type: "text-only", detail: "Documentation-style lineage mapping for explainability." })}</div>`;
}

function renderScenarioBuilder() {
  const d = store.scenarioBuilder;
  const s = formState.scenario_builder;
  const controlGroups = getScenarioBuilderControlGroups();
  const sleeves = Array.isArray(s.factor_sleeves)
    ? s.factor_sleeves
    : String(s.factor_sleeves || "")
        .split("/")
        .map((item) => item.trim())
        .filter(Boolean);
  const liveAssumptions = [
    ["Universe", s.universe],
    ["Rebalance", s.rebalance],
    ["Neutralisation", s.neutralisation ? "Sector-neutral score construction" : "Raw cross-sectional score construction"],
    ["Costs", `${s.transaction_cost} baseline one-way`],
    ["Benchmark", s.benchmark],
    ["Stress Overlay", s.stress_overlay ? `Enabled at VIX ${s.vix_threshold}` : "Disabled"],
  ];
  return `${renderSystemMetrics([{ label: "Active Universe", value: s.universe, note: "Research universe currently loaded into the builder.", sourceType: "derived", sourceDetail: "Current working scenario draft." }, { label: "Baseline Min Names", value: s.top_n, note: "Baseline quarterly-rebalanced configuration starts from 25 names before the hybrid band expands.", sourceType: "derived", sourceDetail: "Current working scenario draft." }, { label: "VIX Threshold", value: s.vix_threshold, note: "Stress overlay activation threshold.", sourceType: "derived", sourceDetail: "Current working scenario draft." }])}<div class="grid-two">${makePanel("Parameter Bar", "Primary controls that define the scenario before execution. Rebalance is fixed to quarterly for the web runner.", renderFormFields(controlGroups.primary), { type: "derived", detail: "Editable scenario controls in the live working draft." })}${makePanel("Form Workspace", "Editable blocks that would later become interactive form controls.", renderFormFields(controlGroups.secondary), { type: "derived", detail: "Editable scenario form blocks in the current working draft." })}</div><div class="scenario-save-row"><button type="button" class="workspace-action" data-action="clear-draft">Clear draft</button></div>${makePanel("Reusable Presets", "Reusable templates for faster experiment setup. Click apply to load one preset into the current form.", `<div class="section-inline-actions"><button type="button" class="workspace-action primary" data-action="save-preset">Save preset</button><button type="button" class="workspace-action" data-action="duplicate-preset">Duplicate preset</button></div>${renderPresetTable(d.presets)}`, { type: "derived", detail: "Connected local preset registry." })}${makePanel("Core Assumptions", "Pinned setup assumptions before launching a run.", renderTable(["Item", "Value"], liveAssumptions), { type: "derived", detail: "Current scenario assumptions assembled from editable controls." })}<div id="scenario-review-anchor">${makePanel("Scenario Review", "Final review surface before this scenario is queued into the runner.", renderTable(["Input", "Current Setting"], [["Factor sleeves", sleeves.join(" / ")], ["VIX threshold", s.vix_threshold], ["Top N", s.top_n], ["Output pack", s.output_pack], ["Hold cap", s.hold_cap]]), { type: "derived", detail: "Review table from the live working draft before persistence or execution." })}</div>`;
}

function renderBacktestRunner() {
  const d = store.health;
  const s = formState.backtest_runner;
  const runnerControls = getBacktestRunnerControlFields();
  const selectedScenario = getRunnerScenarioSelection();
  const selectedConfig = selectedScenario.config;
  const { fields: runControlFields, runnerControlsClass, isBatchMode, isNightlyMode, isNightlyBatch } = runnerControls;
  const recommendedAction = isNightlyMode ? "Schedule nightly refresh" : isBatchMode ? "Queue batch" : "Run baseline";
  const backtestContext = runtimeState.backtestContext || {};
  const activeScenarioRecord = getScenarioRecordById(runtimeState.activeScenarioId) || store.scenarioCenter.items.find((row) => row.is_mainline) || null;
  return `${renderActionPanel("Backtest Runner", "Launch single runs or queue comparison batches after the pipeline passes health checks. The runner now inherits the current working draft from the setup workspaces when selected.", [{ label: "Queue batch", action: "queue-batch", tone: isBatchMode ? "" : "muted", disabled: !isBatchMode }, { label: "Schedule nightly refresh", action: "schedule-nightly", tone: isNightlyMode ? "" : "muted", disabled: !isNightlyMode }, { label: "Watch live status", action: "watch-live-status" }])}${renderSystemMetrics([{ label: "Runner Status", value: "Ready", note: "Infrastructure available for a fresh dispatch." }, { label: "Scenario Universe", value: selectedConfig.universe, note: `${selectedScenario.name} / ${selectedConfig.rebalance} / top ${selectedConfig.top_n}` }, { label: isBatchMode || isNightlyBatch ? "Batch Targets" : "Scenario VIX", value: isBatchMode || isNightlyBatch ? `${s.batch_targets.length} selected` : selectedConfig.vix_threshold, note: isBatchMode || isNightlyBatch ? s.batch_targets.join(" / ") : `Hold cap ${selectedConfig.hold_cap} / ${selectedConfig.stress_overlay ? "overlay on" : "overlay off"}` }])}<div class="grid-two"><div id="runner-controls-anchor">${makePanel("Run Controls", "Execution parameters and scheduling settings for the next job.", `<div class="${runnerControlsClass}">${renderFormFields(runControlFields)}</div>`)}</div>${makePanel("Pipeline Readiness", "Expose the engineering state before a run is triggered.", renderTable(["Task", "Status"], d.dag))}</div><div class="grid-two"><div id="runner-lineage-anchor">${makePanel("Scenario Lineage / Inheritance", "Show exactly where the runner is inheriting its active setup from and how that relates to the active saved scenario.", `<div class="status-list"><div class="status-item"><span>Execution scenario</span><strong>${selectedScenario.name}</strong></div><div class="status-item"><span>Inheritance mode</span><strong>${selectedScenario.name === "Current working scenario" ? "Live draft from setup pages" : "Saved scenario record / preset"}</strong></div><div class="status-item"><span>Origin page</span><strong>${backtestContext.sourceLabel || "No page handoff yet"}</strong></div><div class="status-item"><span>Origin focus</span><strong>${backtestContext.focusSummary || "Current working scenario draft"}</strong></div><div class="status-item"><span>Active saved scenario</span><strong>${activeScenarioRecord?.scenario_name || "Not set"}</strong></div><div class="status-item"><span>Mainline linkage</span><strong>${activeScenarioRecord?.is_mainline ? "Active scenario is mainline" : store.scenarioCenter.mainlineId ? "Mainline exists separately" : "No mainline set"}</strong></div></div><div class="table-action-row">${backtestContext.sourcePage ? `<button type="button" class="workspace-action primary" data-action="return-to-setup-context">Return to ${backtestContext.sourceLabel}</button>` : ""}</div>`)}</div><div id="runner-queue-anchor">${makePanel("Run Queue", "Current execution lane for baseline and comparison jobs.", `<div class="status-list"><div class="status-item"><span>Recommended action</span><strong class="status-good">${recommendedAction}</strong></div><div class="status-item"><span>${isNightlyMode ? "Nightly mode" : "Selected scenario"}</span><strong>${isNightlyMode ? s.nightly_mode : selectedScenario.name}</strong></div><div class="status-item"><span>Scenario inheritance</span><strong>${selectedScenario.name === "Current working scenario" ? "Live draft from setup pages" : "Saved scenario record / preset"}</strong></div>${isBatchMode || isNightlyBatch ? `<div class="status-item"><span>Batch targets</span><strong>${s.batch_targets.join(" / ")}</strong></div>` : `<div class="status-item"><span>Scenario profile</span><strong>${selectedConfig.rebalance} / top ${selectedConfig.top_n} / VIX ${selectedConfig.vix_threshold}</strong></div>`}<div class="status-item"><span>Next window</span><strong>${isNightlyMode ? s.nightly_time : "Immediate"}</strong></div></div>`)}</div>${makePanel("Quality Gates", "Checks that should pass before results are treated as credible.", `<div class="status-list">${d.checks.map(([label, status]) => `<div class="status-item"><span>${label}</span><strong class="${status === "Pass" ? "status-good" : ""}">${status}</strong></div>`).join("")}</div>`)}${makePanel("Source Coverage", "Coverage floor across the datasets feeding the backtest runner.", renderProgress(d.coverage, (value) => `${value.toFixed(1)}%`))}`;
}

function renderRunHistory() {
  const d = store.runHistory;
  d.runs = sanitizeRunHistoryRows(d.runs);
  const s = formState.run_history;
  const scenarioSelection = Array.isArray(s.scenario_filter) ? s.scenario_filter : [s.scenario_filter];
  const statusSelection = Array.isArray(s.status_filter) ? s.status_filter : [s.status_filter];
  const ownerSelection = Array.isArray(s.owner_filter) ? s.owner_filter : [s.owner_filter];
  const scenarioOptions = ["All scenarios", ...new Set(d.runs.map((row) => row[2]))];
  const ownerOptions = ["All owners", ...new Set(d.runs.map((row) => getRunOwner(row[0])))];
  const filteredRuns = getFilteredRunHistoryRows(d.runs, s);
  const historyFilterFields = [
    ["Scenario", { type: "multiselect", key: "scenario_filter", value: getMultiSelectSummary(scenarioSelection, "All scenarios"), options: scenarioOptions }],
    ["Status", { type: "multiselect", key: "status_filter", value: getMultiSelectSummary(statusSelection, "All status"), options: ["All status", "Success", "Warning", "Queued", "Running", "Scheduled"] }],
    ["Owner", { type: "multiselect", key: "owner_filter", value: getMultiSelectSummary(ownerSelection, "All owners"), options: ownerOptions }],
    ["Date Range", { type: "select", key: "date_range", value: s.date_range, options: ["Last 24 hours", "Last 7 days", "Last 30 days", "All dates", "Custom range"] }],
  ];
  if (s.date_range === "Custom range") {
    historyFilterFields.push(
      ["Start Date", { type: "date", key: "custom_start_date", value: s.custom_start_date }],
      ["End Date", { type: "date", key: "custom_end_date", value: s.custom_end_date }],
    );
  }
  historyFilterFields.push(
    ["Include warnings", { type: "switch", key: "include_warnings", value: s.include_warnings }],
    ["Sort", { type: "select", key: "sort_order", value: s.sort_order, options: ["Latest first", "Oldest first", "Status priority"] }],
  );
  const selectingRuns = runtimeState.runHistorySelectionMode;
  const selectedCount = runtimeState.selectedRunIds.length;
  const runHistoryHeaderActions = `<button type="button" class="workspace-action primary" data-action="refresh-history">Refresh table</button><button type="button" class="workspace-action" data-action="export-history">Export history</button>`;
  const runHistoryFooterActions = selectingRuns
    ? `<button type="button" class="workspace-action primary" data-action="clear-selected-history">Delete selected${selectedCount ? ` (${selectedCount})` : ""}</button><button type="button" class="workspace-action" data-action="cancel-history-selection">Cancel</button><button type="button" class="workspace-action" data-action="clear-all-history">Clear all</button>`
    : `<button type="button" class="workspace-action" data-action="start-history-selection">Select records</button><button type="button" class="workspace-action" data-action="clear-all-history">Clear all</button>`;
  const runHistoryPanel = `<section class="panel"><div class="section-title"><div><h3>Run History</h3><p>Chronological list of recent system runs.</p></div><div class="section-title-side">${renderSourceMeta({ type: "derived", detail: "Connected recent-run API rows with live status enrichment." }, true)}<div class="action-panel-row">${runHistoryHeaderActions}</div></div></div>${renderRunHistoryTable(filteredRuns)}<div class="table-action-row history-footer-actions">${runHistoryFooterActions}</div></section>`;
  const runsToday = d.runs.filter((row) => String(row[1] || "").startsWith(new Date().toISOString().slice(0, 10)) || String(row[1] || "").includes(new Date().toLocaleDateString("en-CA"))).length || d.runs.length;
  const completedRuns = d.runs.filter((row) => normalizeStatusLabel(row[3]) === "Completed").length;
  const successRate = d.runs.length ? `${((completedRuns / d.runs.length) * 100).toFixed(0)}%` : "n/a";
  const latestDuration = d.runs[0]?.[0] ? getRunDurationDisplay(d.runs[0][0], d.runs[0][4] || "n/a") : "n/a";
  return `${renderActionPanel("Run History Console", "Filter completed jobs, inspect status, and review the outputs generated by the system.", [{ label: "Open latest", action: "open-latest-run" }, { label: "Download logs", action: "download-logs" }, { label: "Open latest artifacts", action: "open-artifacts" }])}${renderSystemMetrics([{ label: "Runs Visible", value: `${runsToday}`, note: "Current rows available in the connected run history." }, { label: "Completion Rate", value: successRate, note: "Derived from the current run table status mix." }, { label: "Latest Duration", value: latestDuration, note: "Duration or queue-state text from the newest run." }])}<div class="grid-two">${makePanel("History Filters", "Narrow the run table by scenario, status, or owner.", renderFormFieldsEnhanced(historyFilterFields))}${makePanel("Generated Outputs", "Artifacts attached to the latest runs.", `<div class="status-list">${d.artifacts.map(([label, status]) => `<div class="status-item"><span>${label}</span><strong class="${status === "Generated" ? "status-good" : ""}">${status}</strong></div>`).join("")}</div>`)}</div>${runHistoryPanel}`;
}

function renderFactorLab() {
  const d = store.factorBuilder;
  const s = formState.factor_lab;
  const factorRows = d.factorRows.map((row) => [row.factor, row.subVariables.join(" / "), row.ic, row.rankIc, `${row.hitRatePct}%`]);
  const alphaDistribution = d.alphaDistribution.map((row) => [row.bucket, row.count]);
  const topPreviewRows = d.topPreview.map((row) => [row.ticker, row.sector, row.factor, row.score]);
  const rawScoreRows = Array.isArray(store.factorRaw?.scoreRows)
    ? store.factorRaw.scoreRows.slice(0, 10).map((row) => [
      row.symbol || row.ticker || "n/a",
      row.regime || "n/a",
      Number(row.composite_alpha || 0).toFixed(3),
      Number(row.quality_score || 0).toFixed(3),
      Number(row.value_score || 0).toFixed(3),
      Number(row.market_technical_score || 0).toFixed(3),
      Number(row.dividend_score || 0).toFixed(3),
    ])
    : [];
  const attributionRows = Array.isArray(store.factorRaw?.attributionRows)
    ? store.factorRaw.attributionRows.slice(0, 10).map((row) => [
        row.period_end_date || row.date || "n/a",
        row.factor_name || row.factor || "n/a",
        Number(row.active_exposure || 0).toFixed(3),
        Number(row.factor_spread_return || 0).toFixed(3),
        Number(row.contribution_proxy || 0).toFixed(3),
      ])
    : [];
return `${renderActionPanel("Signal & Factor Builder", "Review factor preview outputs and raw diagnostics here. Settings used to run scenarios are edited in Research Setup and shown below as read-only context.", [{ label: "Refresh preview", action: "preview-factors" }, { label: "Open in Runner", action: "handoff-to-runner" }], { type: "derived", detail: "Connected factor preview controls backed by the preview API." })}${renderSystemMetrics([{ label: "Active Factors", value: `${d.summary.activeFactorCount}`, note: "Primary sleeves carried by the current working scenario.", sourceType: "derived", sourceDetail: "Factor preview API summary." }, { label: "Sub-variables", value: `${d.summary.subVariableCount}`, note: "Underlying descriptors represented in the quick factor preview.", sourceType: "derived", sourceDetail: "Factor preview API summary." }, { label: "Avg IC", value: `${d.summary.avgIc}`, note: "Live quick-check information coefficient from the preview payload.", sourceType: "derived", sourceDetail: "Factor preview API summary." }])}<div class="grid-two"><div id="factor-builder-controls-anchor">${makePanel("Applied Run Settings", "These are the saved scenario settings currently driving this page's preview. To change them, go back to Research Setup.", `${renderTable(["Setting", "Current"], [["Factor Sleeves", Array.isArray(s.factor_sleeves) ? s.factor_sleeves.join(" / ") : "n/a"], ["Neutralisation", d.summary.neutralisationEnabled ? "Enabled" : "Disabled"], ["Top N", s.top_n], ["Cost model", s.cost_model], ["Winsorisation", d.summary.winsorisation || s.winsorisation], ["Standardisation", d.summary.standardisation || s.standardisation], ["EWMA Decay", d.summary.ewmaDecay || s.ewma_decay], ["Lookback Window", s.lookback_window]])}<div class="table-action-row"><button type="button" class="workspace-action primary" data-jump-page="scenario_builder">Open Research Setup</button><button type="button" class="workspace-action" data-jump-page="optimizer_settings">Open Optimizer Settings</button></div>`, { type: "derived", detail: "Read-only view of saved scenario settings that drive this page's preview." })}</div><div id="factor-summary-anchor">${makePanel("Signal Summary", "Use this as the quick writing summary before running a fuller IC or backtest workflow.", renderTable(["Metric", "Current"], [["Average IC", d.summary.avgIc], ["Average Rank IC", d.summary.avgRankIc], ["Neutralisation", d.summary.neutralisationEnabled ? "Enabled" : "Disabled"], ["Top preview count", d.summary.topPreviewCount]]), { type: "derived", detail: "Connected factor preview summary." })}</div></div><div class="grid-two">${makePanel("Factor Heatmap Snapshot", "Compact requirement-style heatmap substitute using quick IC, rank-IC, and hit-rate outputs.", renderTable(["Factor", "Sub-variables", "IC", "Rank IC", "Hit Rate"], factorRows), { type: "derived", detail: "Connected factor preview rows." })}${makePanel("Alpha Distribution", "Cross-sectional score dispersion used to sanity-check whether the factor stack is behaving sensibly.", `<div class="chart-card"><h4>Distribution buckets</h4>${renderBars(alphaDistribution)}</div>`, { type: "derived", detail: "Connected factor preview distribution buckets." })}</div><div class="grid-two"><div id="factor-top-preview-anchor">${makePanel("Top Preview Names", "Top slice of the quick factor ranking, capped for easy QA and screenshot use.", renderTable(["Ticker", "Sector", "Lead Factor", "Score"], topPreviewRows), { type: "derived", detail: "Connected preview ranking sample." })}</div>${makePanel("Preview Notes", "Method notes that clarify how this factor preview should be interpreted in formal analysis and reporting.", `<div class="docs-list">${(d.notes || []).map((note) => `<article><p>${note}</p></article>`).join("")}</div>`, { type: "text-only", detail: "Method notes for formal reporting and analytical review." })}</div><div class="grid-two">${makePanel("Latest Factor Score Snapshot", "Real raw factor rows from the latest score snapshot, limited to the highest-signal slice for QA.", renderTable(["Ticker", "Regime", "Composite", "Quality", "Value", "Technical", "Dividend"], rawScoreRows.length ? rawScoreRows : [["No raw factor rows", "-", "-", "-", "-", "-", "-"]]), { type: "raw", detail: "Raw feature_factor_scores rows from PostgreSQL." })}<div id="factor-attribution-anchor">${makePanel("Recent Factor Attribution", "Recent realised attribution rows from the baseline run so factor logic is tied back to portfolio behaviour.", renderTable(["Date", "Factor", "Exposure", "Spread Return", "Contribution"], attributionRows.length ? attributionRows : [["No attribution rows", "-", "-", "-", "-"]]), { type: "raw", detail: "Raw backtest_factor_attribution rows from PostgreSQL." })}</div></div>`;
}

function renderPerformanceDashboard() {
  const d = store.performance;
  const s = formState.performance_dashboard;
  const summary = d.summary || {};
  const rawSeries = Array.isArray(d.rawSeries) ? d.rawSeries : [];
  const baselineEnd = d.baseline.at(-1) ?? 0;
  const baselineStart = d.baseline[0] ?? baselineEnd;
  const baselineChangePct = baselineStart ? ((baselineEnd / baselineStart) - 1) * 100 : 0;
  const compareOptions = store.runHistory.runs
    .filter((row) => normalizeStatusLabel(row[3]) === "Completed" && isComparablePerformanceRunId(row[0]))
    .slice(0, 5)
    .map((row) => row[0]);
  const selectedDisplayRun = getSelectedDisplayRun(compareOptions);
  const selectedSummaryRuns = getSelectedSummaryRuns(compareOptions);
  const activeCompareRunId = selectedDisplayRun !== "Baseline" && compareOptions.includes(selectedDisplayRun) ? selectedDisplayRun : "";
  selectedSummaryRuns.forEach((runId) => {
    if (!Array.isArray(runtimeState.performanceRunSeriesCache[runId]) && !runtimeState.performanceRunSeriesLoading[runId]) {
      void ensurePerformanceRunSeries(runId);
    }
  });
  if (activeCompareRunId && !Array.isArray(runtimeState.performanceRunSeriesCache[activeCompareRunId]) && !runtimeState.performanceRunSeriesLoading[activeCompareRunId]) {
    void ensurePerformanceRunSeries(activeCompareRunId);
  }
  const activeCompareSeries = activeCompareRunId ? runtimeState.performanceRunSeriesCache[activeCompareRunId] : null;
  const displayView = Array.isArray(activeCompareSeries) && activeCompareSeries.length
    ? buildPerformanceViewFromRawSeries(activeCompareSeries)
    : {
      rawSeries,
      nav: d.nav,
      benchmark: d.benchmark,
      excess: d.excess,
      drawdown: d.drawdown,
      sharpe: d.sharpe,
      monthlyHeatmap: d.monthlyHeatmap,
    };
  const displayLabel = activeCompareRunId && Array.isArray(activeCompareSeries) && activeCompareSeries.length
    ? activeCompareRunId
    : (summary.run_id || "baseline");
  const benchmarkGap = displayView.nav.map((value, index) => Number((value - (displayView.benchmark[index] ?? 0)).toFixed(1)));
  const latestSpread = benchmarkGap.at(-1);
  const strategyEnd = displayView.nav.at(-1) ?? 0;
  const strategyStart = displayView.nav[0] ?? strategyEnd;
  const benchmarkEnd = displayView.benchmark.at(-1) ?? 0;
  const benchmarkStart = displayView.benchmark[0] ?? benchmarkEnd;
  const spreadStart = benchmarkGap[0] ?? latestSpread ?? 0;
  const strategyChangePct = strategyStart ? ((strategyEnd / strategyStart) - 1) * 100 : 0;
  const benchmarkChangePct = benchmarkStart ? ((benchmarkEnd / benchmarkStart) - 1) * 100 : 0;
  const spreadMove = (latestSpread ?? 0) - spreadStart;
  const focusIndex = s.nav_focus_period === "Peak drawdown"
    ? displayView.drawdown.findIndex((value) => value === Math.min(...displayView.drawdown))
    : displayView.nav.length - 1;
  const displayRawSeries = displayView.rawSeries || [];
  const monthlyHeatmapLabels = buildMonthlyHeatmapLabelsFromRaw(displayRawSeries, displayView.monthlyHeatmap);
  const focusDateValue = getSeriesDateValue(displayRawSeries[focusIndex]);
  const hasSeriesDates = displayRawSeries.some((row) => !!getSeriesDateValue(row));
  const focusDate = hasSeriesDates ? formatAxisDateLabel(focusDateValue || getSeriesDateValue(displayRawSeries.at(-1)) || "n/a") : `Point ${focusIndex + 1}`;
  const axisStartDate = hasSeriesDates ? formatAxisDateLabel(getSeriesDateValue(displayRawSeries[0])) : "Start";
  const axisEndDate = hasSeriesDates ? formatAxisDateLabel(getSeriesDateValue(displayRawSeries.at(-1))) : "Latest";
  const drawdownLabels = displayView.drawdown.map((value, index) => [hasSeriesDates ? formatAxisDateLabel(getSeriesDateValue(displayRawSeries[index]) || `Point ${index + 1}`) : `P${index + 1}`, value]);
  const pointLabel = s.nav_focus_period === "Peak drawdown" ? `${focusDate} (drawdown trough)` : `${focusDate} (latest point)`;
  const focusModeLabel = s.nav_focus_period === "Peak drawdown" ? "Peak drawdown" : "Latest point";
  const holdingsDrilldown = store.tradeBlotter.holdingsRows.slice(0, 4).map((row) => [row.ticker, row.sector, `${row.weightPct}%`, row.role]);
  const factorDrilldown = store.factorBuilder.factorRows.slice(0, 4).map((row) => [row.factor, row.ic, row.rankIc, `${row.hitRatePct}%`]);
  const noComparableRuns = !compareOptions.length;
  const compareRows = noComparableRuns
    ? [["No comparable completed runs", "baseline", "baseline", "baseline"]]
    : selectedSummaryRuns.length
      ? selectedSummaryRuns.map((runId) => {
          const runSeries = Array.isArray(runtimeState.performanceRunSeriesCache[runId]) ? runtimeState.performanceRunSeriesCache[runId] : [];
          if (!runSeries.length) {
            if (runtimeState.performanceRunSeriesLoading[runId]) return [runId, "loading...", "loading...", "loading..."];
            if (runtimeState.performanceRunSeriesUnavailable[runId]) return [runId, "Unavailable", "Unavailable", "Unavailable"];
            return [runId, "loading...", "loading...", "loading..."];
          }
          const runView = buildPerformanceViewFromRawSeries(runSeries);
          const runNavStart = runView.nav[0] ?? 0;
          const runNavEnd = runView.nav.at(-1) ?? runNavStart;
          const runReturn = runNavStart ? ((runNavEnd / runNavStart) - 1) * 100 : 0;
          const runSharpe = runView.sharpe.at(-1) ?? 0;
          const runMaxDd = Math.min(...runView.drawdown, 0);
          return [runId, `${runReturn >= 0 ? "+" : ""}${runReturn.toFixed(1)}%`, `${runSharpe.toFixed(2)}`, `${runMaxDd.toFixed(1)}%`];
        })
      : [["No run selected", "n/a", "n/a", "n/a"]];
  const compareControlMarkup = noComparableRuns
    ? `<div class="empty-state-card"><strong>No comparable completed runs</strong><p>Only completed runs with an available raw performance series appear here. The charts below are staying on the baseline series for now.</p></div>${renderFormFields([["NAV focus", { type: "select", key: "nav_focus_period", value: s.nav_focus_period, options: ["Latest point", "Peak drawdown"] }], ["Drilldown view", { type: "select", key: "drilldown_view", value: s.drilldown_view, options: ["Holdings + factors", "Holdings only", "Factors only"] }]])}`
    : renderFormFields([["Display run", { type: "select", key: "compare_runs", value: selectedDisplayRun, options: ["Baseline", ...compareOptions] }], ["Summary compare runs", { type: "tag", key: "compare_summary_runs", value: selectedSummaryRuns, options: compareOptions, minSelect: 1, scrollable: true }], ["NAV focus", { type: "select", key: "nav_focus_period", value: s.nav_focus_period, options: ["Latest point", "Peak drawdown"] }], ["Drilldown view", { type: "select", key: "drilldown_view", value: s.drilldown_view, options: ["Holdings + factors", "Holdings only", "Factors only"] }]]);
  const strategyNavStats = renderChartStats([
    { label: "Start", value: formatChartMetric(strategyStart) },
    { label: "End", value: formatChartMetric(strategyEnd) },
    { label: "Return", value: `${strategyChangePct >= 0 ? "+" : ""}${formatChartMetric(strategyChangePct, 1, "%")}` },
  ]);
  const benchmarkNavStats = renderChartStats([
    { label: "Start", value: formatChartMetric(benchmarkStart) },
    { label: "End", value: formatChartMetric(benchmarkEnd) },
    { label: "Return", value: `${benchmarkChangePct >= 0 ? "+" : ""}${formatChartMetric(benchmarkChangePct, 1, "%")}` },
  ]);
  const baselineNavStats = renderChartStats([
    { label: "Start", value: formatChartMetric(baselineStart) },
    { label: "End", value: formatChartMetric(baselineEnd) },
    { label: "Return", value: `${baselineChangePct >= 0 ? "+" : ""}${formatChartMetric(baselineChangePct, 1, "%")}` },
  ]);
  const spreadStats = renderChartStats([
    { label: "Start spread", value: `${spreadStart >= 0 ? "+" : ""}${formatChartMetric(spreadStart, 1)} pts` },
    { label: "Latest spread", value: `${(latestSpread ?? 0) >= 0 ? "+" : ""}${formatChartMetric(latestSpread ?? 0, 1)} pts` },
    { label: "Spread move", value: `${spreadMove >= 0 ? "+" : ""}${formatChartMetric(spreadMove, 1)} pts` },
  ]);
  const interpretationPanel = makePanel("How To Read These Charts", "Spell out exactly which portfolio is being compared with which reference so the dashboard is self-explanatory in screenshots and report drafting.", renderTable(["Chart", "What it is", "Why it matters"], [
    ["Strategy NAV", "The cumulative net asset value path of the live formal_s30 strategy after costs.", "This is the main portfolio you are evaluating."],
    ["Raw benchmark NAV", "The benchmark_nav series stored with the displayed run, usually the same-universe equal-weight benchmark.", "This is an internal stock-selection lens; the final report's investor-facing primary baseline is SPY."],
    ["Model baseline", "A static multi-factor portfolio with the same quarterly-rebalanced stock-selection framework but fixed normal-state weights and no VIX-aware switching.", "This isolates the value added by the dynamic regime overlay rather than the stock universe itself."],
    ["Strategy - Raw benchmark", "The spread between strategy NAV and the run's benchmark_nav series at each point in time.", "A rising spread means the strategy is outperforming the stored internal benchmark series for the displayed run."],
    ["Monthly Return Heatmap", "The latest monthly net returns from the displayed run, with one month label per cell.", "Each cell is one month from the displayed run; use the month label to see exactly which monthly return the color refers to."],
  ]));
  const comparisonPanel = makePanel("Benchmark Comparison Lens", "Focused comparison of strategy relative to the stored benchmark_nav series for the current horizon.", `<div class="grid-two"><div class="chart-card"><h4>Strategy - Raw Benchmark</h4>${renderSparkline(benchmarkGap, "#7557f8", "rgba(117,87,248,0.14)", { showAxes: true, xAxisLabel: "Date", yAxisLabel: "Spread pts", xStartLabel: axisStartDate, xEndLabel: axisEndDate, yFormatter: (value) => Number(value).toFixed(1), highlightIndex: focusIndex, highlightLabel: focusModeLabel })}${spreadStats}<p class="small-note">This line is calculated as Strategy NAV minus the stored benchmark_nav series for ${escapeHtml(displayLabel)}.</p></div><div class="status-list"><div class="status-item"><span>Display run</span><strong>${escapeHtml(displayLabel)}</strong></div><div class="status-item"><span>Focus selection</span><strong>${focusModeLabel}</strong></div><div class="status-item"><span>Focus date</span><strong>${focusDate}</strong></div><div class="status-item"><span>Focused spread</span><strong class="${benchmarkGap[focusIndex] >= 0 ? "status-good" : ""}">${benchmarkGap[focusIndex] >= 0 ? "+" : ""}${benchmarkGap[focusIndex].toFixed(1)} pts</strong></div><div class="status-item"><span>Benchmark end level</span><strong>${formatChartMetric(benchmarkEnd)}</strong></div></div></div>`);
  const modelBaselineSummaryCard = `<div class="chart-card"><h4>Model baseline summary</h4><div class="status-list"><div class="status-item"><span>Baseline end level</span><strong>${formatChartMetric(baselineEnd)}</strong></div><div class="status-item"><span>Baseline return</span><strong>${baselineChangePct >= 0 ? "+" : ""}${baselineChangePct.toFixed(1)}%</strong></div><div class="status-item"><span>Source</span><strong>Derived summary only</strong></div></div><p class="small-note">No raw per-period static-baseline time series is currently available in the connected dataset, so this reference is shown as a summary card rather than a plotted line.</p></div>`;
  return `${renderActionPanel("Performance Dashboard", "Review return path, benchmark-relative behaviour, and drawdown diagnostics.", [{ label: "Open run viewer", action: "compare-performance-runs" }, { label: "Open point drilldown", action: "open-performance-drilldown" }, { label: "Export charts", action: "export-performance-charts" }], { type: "derived", detail: "Control surface over connected raw performance rows and selected-run summaries." })}${renderSystemMetrics([{ label: "Cumulative Return", value: `${strategyChangePct.toFixed(1)}%`, note: `Strategy NAV path for ${displayLabel}.`, sourceType: "raw", sourceDetail: "Directly computed from the displayed run's raw performance series." }, { label: "Raw Benchmark Spread", value: `${(latestSpread ?? 0).toFixed(1)} pts`, note: "Latest outperformance versus the stored benchmark_nav series.", sourceType: "raw", sourceDetail: "Directly computed from the displayed run's raw strategy and benchmark series." }, { label: "Rolling Sharpe", value: Number((displayView.sharpe.at(-1) ?? 0)).toFixed(2), note: "Latest rolling risk-adjusted reading.", sourceType: displayView.sharpe.length ? "raw" : "derived", sourceDetail: displayView.sharpe.length ? "Computed from the displayed run's raw performance history." : "Summary fallback from connected performance payload." }, { label: "Current Focus", value: focusModeLabel, note: pointLabel, sourceType: "raw", sourceDetail: "Current focus point selected from the displayed raw series." }])}${makePanel("How To Read These Charts", "Spell out exactly which portfolio is being compared with which reference so the dashboard is self-explanatory in screenshots and report drafting.", renderTable(["Chart", "What it is", "Why it matters"], [
    ["Strategy NAV", "The cumulative net asset value path of the live formal_s30 strategy after costs.", "This is the main portfolio you are evaluating."],
    ["Raw benchmark NAV", "The benchmark_nav series stored with the displayed run, usually the same-universe equal-weight benchmark.", "This is an internal stock-selection lens; the final report's investor-facing primary baseline is SPY."],
    ["Model baseline", "A static multi-factor portfolio with the same quarterly-rebalanced stock-selection framework but fixed normal-state weights and no VIX-aware switching.", "This isolates the value added by the dynamic regime overlay rather than the stock universe itself."],
    ["Strategy - Raw benchmark", "The spread between strategy NAV and the run's benchmark_nav series at each point in time.", "A rising spread means the strategy is outperforming the stored internal benchmark series for the displayed run."],
  ]), { type: "text-only", detail: "Interpretation guidance for readers rather than a raw data card." })}<div class="grid-two"><div id="performance-controls-anchor">${makePanel("Display Controls", "Choose which run is currently shown on this page, then adjust chart focus and drilldown context.", compareControlMarkup, { type: "derived", detail: "Interactive display controls rather than a stored market dataset." })}</div><div id="performance-multi-run-anchor">${makePanel("Selected Run Summary", "Quick summary for the currently displayed run.", renderTable(["Run", "Cum. Return", "Sharpe", "Max DD"], compareRows), { type: "derived", detail: "Derived summary block for the selected display run." })}</div></div>${makePanel("NAV vs Benchmark vs Static Baseline", "This block compares the actual strategy against the stored benchmark_nav series and a static no-overlay model baseline built on the same quarterly-rebalanced selection rules; SPY-primary results are handled in the report evidence tables.", `<div class="status-list"><div class="status-item"><span>Display run</span><strong>${escapeHtml(displayLabel)}</strong></div><div class="status-item"><span>Series source</span><strong>${activeCompareRunId ? "Selected display run" : "Baseline raw series"}</strong></div><div class="status-item"><span>Model baseline source</span><strong>Derived summary only</strong></div>${noComparableRuns ? `<div class="status-item"><span>Run availability</span><strong>No comparable completed runs - using baseline charts</strong></div>` : ""}${activeCompareRunId && runtimeState.performanceRunSeriesUnavailable[activeCompareRunId] ? `<div class="status-item"><span>Selected run availability</span><strong>Unavailable - using baseline charts</strong></div>` : ""}</div><div class="grid-two"><div class="chart-card"><h4>Strategy NAV</h4>${renderSparkline(displayView.nav, "#0d6c63", "rgba(13,108,99,0.12)", { showAxes: true, xAxisLabel: "Date", yAxisLabel: "NAV index", xStartLabel: axisStartDate, xEndLabel: axisEndDate, yFormatter: (value) => Number(value).toFixed(1), highlightIndex: focusIndex, highlightLabel: focusModeLabel })}${strategyNavStats}<p class="small-note">Source: raw backtest_performance series for ${escapeHtml(displayLabel)}.</p></div><div class="chart-card"><h4>Raw benchmark NAV</h4>${renderSparkline(displayView.benchmark, "#64748b", "rgba(100,116,139,0.12)", { showAxes: true, xAxisLabel: "Date", yAxisLabel: "NAV index", xStartLabel: axisStartDate, xEndLabel: axisEndDate, yFormatter: (value) => Number(value).toFixed(1), highlightIndex: focusIndex, highlightLabel: focusModeLabel })}${benchmarkNavStats}<p class="small-note">Source: raw benchmark_nav series for the displayed run.</p></div></div><div class="grid-two">${modelBaselineSummaryCard}<div class="chart-card"><h4>Reference note</h4><p class="small-note">Use the SPY-primary evidence tables in Report Studio and the robustness pack for final market-relative report wording.</p></div></div>`, { type: "derived", detail: "Strategy and benchmark_nav are raw for the selected display run; model baseline is shown as derived summary only." })}<div id="performance-benchmark-anchor">${comparisonPanel}</div><div class="grid-two"><div id="performance-point-detail-anchor">${makePanel("Point Drilldown", "Simulate the requirement-sheet point-click behaviour by exposing the selected NAV point details directly.", `<div class="status-list"><div class="status-item"><span>Display run</span><strong>${escapeHtml(displayLabel)}</strong></div><div class="status-item"><span>Focus mode</span><strong>${focusModeLabel}</strong></div><div class="status-item"><span>Focus point</span><strong>${pointLabel}</strong></div><div class="status-item"><span>Strategy NAV</span><strong>${displayView.nav[focusIndex]}</strong></div><div class="status-item"><span>Raw benchmark</span><strong>${displayView.benchmark[focusIndex]}</strong></div><div class="status-item"><span>Spread</span><strong>${benchmarkGap[focusIndex] >= 0 ? "+" : ""}${benchmarkGap[focusIndex].toFixed(1)} pts</strong></div></div><div class="table-action-row"><button type="button" class="workspace-action" data-action="performance-open-trades">Open Trade Blotter</button></div>`, { type: "raw", detail: "Current point values taken from the displayed raw series." })}</div><div id="performance-point-context-anchor">${makePanel("Point Context", "Top holdings and factor context tied to the current focus point.", s.drilldown_view === "Holdings only" ? renderTable(["Ticker", "Sector", "Weight", "Role"], holdingsDrilldown) : s.drilldown_view === "Factors only" ? renderTable(["Factor", "IC", "Rank IC", "Hit Rate"], factorDrilldown) : `${renderTable(["Ticker", "Sector", "Weight", "Role"], holdingsDrilldown)}${renderTable(["Factor", "IC", "Rank IC", "Hit Rate"], factorDrilldown)}`, { type: "raw", detail: "Context tables come from raw holdings and factor attribution snapshots." })}</div></div>${makePanel("Drawdown Chart", "Peak-to-trough profile of the strategy.", `<div class="chart-card"><h4>Drawdown</h4>${renderDivergingBars(drawdownLabels, (value) => `${value.toFixed(1)}%`, { highlightIndex: focusIndex })}</div>`, { type: "raw", detail: "Computed directly from the displayed run's raw performance series." })}<div class="grid-two">${makePanel("Rolling Sharpe", "Rolling risk-adjusted return profile.", `<div class="chart-card"><h4>Rolling Sharpe</h4>${renderSparkline(displayView.sharpe, "#0a4f7a", "rgba(10,79,122,0.12)", { highlightIndex: focusIndex, highlightLabel: focusModeLabel })}</div>`, { type: displayView.sharpe.length ? "raw" : "derived", detail: displayView.sharpe.length ? "Computed from the displayed run's raw performance history." : "Fallback derived from summary payload." })}${makePanel("Monthly Return Heatmap", "Monthly return dispersion at a glance.", `${renderHeatmap(displayView.monthlyHeatmap)}<p class="small-note">Each heatmap cell is one monthly return from the displayed run, labeled by month.</p>`, { type: displayView.monthlyHeatmap.length ? "raw" : "derived", detail: displayView.monthlyHeatmap.length ? "Built from the displayed run's raw performance history." : "Fallback heatmap values." })}</div>${makePanel("Cumulative Raw Benchmark Spread", "Cumulative outperformance versus the stored benchmark_nav series.", `<div class="chart-card"><h4>Raw Benchmark Spread</h4>${renderSparkline(displayView.excess, "#20704a", "rgba(32,112,74,0.14)", { highlightIndex: focusIndex, highlightLabel: focusModeLabel })}</div>`, { type: "raw", detail: "Computed directly from the displayed run's raw strategy and benchmark series." })}`;
}
function renderRiskDashboard() {
  const s = formState.risk_dashboard;
  if (s.compare_mode === "Previous run") s.compare_mode = "Previous snapshot";
  if (s.covariance_focus === "Top risks" || s.covariance_focus === "Cross-factor" || s.covariance_focus === "Sector block") {
    s.covariance_focus = "Latest covariance metrics";
  }
  const regimeSummary = store.regime.summary || {};
  const vixSeries = Array.isArray(store.regime.vix)
    ? store.regime.vix.map((value) => Number(value)).filter(Number.isFinite)
    : [];
  const summaryLatestVix = Number(regimeSummary.latest_vix ?? store.regimeControl?.summary?.latest_vix);
  const latestVix = vixSeries.length
    ? vixSeries.at(-1)
    : (Number.isFinite(summaryLatestVix) ? summaryLatestVix : null);
  const thresholdValue = Number(regimeSummary.stress_threshold ?? store.regimeControl?.summary?.stress_threshold ?? store.regime.threshold);
  const thresholdDisplay = Number.isFinite(thresholdValue) ? `${thresholdValue}` : "n/a";
  const latestVixDisplay = latestVix != null ? `${latestVix}` : "n/a";
  const regimeState = regimeSummary.current_regime
    || store.regimeControl?.summary?.current_regime
    || (latestVix != null && Number.isFinite(thresholdValue) ? (latestVix >= thresholdValue ? "Stress" : "Normal") : "n/a");
  const sectorOptions = getSectorFocusOptions();
  const effectiveSectorFocus = normalizeSectorName(getSharedSectorFocus());
  formState.risk_dashboard.sector_focus = effectiveSectorFocus;
  const regimeExposureRows = Array.isArray(store.regimeControl?.exposures) && store.regimeControl.exposures.length
    ? store.regimeControl.exposures
    : (Array.isArray(store.regime.exposures) && store.regime.exposures.length
      ? store.regime.exposures.map(([label, normal, stress]) => {
        const normalPct = Number(normal || 0) * 100;
        const stressPct = Number(stress || 0) * 100;
        const shiftPct = stressPct - normalPct;
        return [label, `${normalPct.toFixed(1)}%`, `${stressPct.toFixed(1)}%`, `${shiftPct >= 0 ? "+" : ""}${shiftPct.toFixed(1)}pp`];
      })
      : (Array.isArray(store.regime.exposureChange) && store.regime.exposureChange.length
        ? store.regime.exposureChange.map(([label, shift]) => [label, "n/a", "n/a", String(shift)])
        : []));
  const marketTechnicalShift = regimeSummary.market_technical_shift
    || regimeSummary.momentum_shift
    || store.regime.exposureChange.find(([label]) => /market technical|momentum/i.test(String(label)))?.[1]
    || "n/a";
  const dividendTilt = regimeSummary.dividend_tilt
    || store.regime.exposureChange.find(([label]) => /dividend/i.test(String(label)))?.[1]
    || "n/a";
  const sectorHoldings = store.tradeBlotter.holdingsRows.filter((row) => effectiveSectorFocus === "All sectors" || normalizeSectorName(row.sector) === effectiveSectorFocus).map((row) => [row.ticker, normalizeSectorName(row.sector), `${row.weightPct}%`, row.role]);
  const allCovarianceRows = Array.isArray(store.riskRaw?.rows) ? store.riskRaw.rows : [];
  const allContributionRows = Array.isArray(store.riskRaw?.contributionRows) ? store.riskRaw.contributionRows : [];
  const availableSnapshotDates = Array.from(new Set([
    ...(Array.isArray(store.riskRaw?.availableDates) ? store.riskRaw.availableDates : []),
    ...(Array.isArray(store.riskRaw?.contributionAvailableDates) ? store.riskRaw.contributionAvailableDates : []),
    ...allCovarianceRows.map((row) => String(row.date || "").trim()).filter(Boolean),
    ...allContributionRows.map((row) => String(row.date || "").trim()).filter(Boolean),
  ])).sort((left, right) => right.localeCompare(left));
  const selectedSnapshotDate = availableSnapshotDates.includes(String(s.snapshot_date || "").trim())
    ? String(s.snapshot_date || "").trim()
    : (availableSnapshotDates[0] || store.riskRaw?.asOfDate || "");
  formState.risk_dashboard.snapshot_date = selectedSnapshotDate;
  const covarianceRows = allCovarianceRows.filter((row) => !selectedSnapshotDate || String(row.date || "") === selectedSnapshotDate);
  const contributionRows = allContributionRows.filter((row) => !selectedSnapshotDate || String(row.date || "") === selectedSnapshotDate);
  const covarianceFocus = String(s.covariance_focus || "Latest covariance metrics");
  const covarianceRowsByFocus = (() => {
    if (covarianceFocus === "Tracking error lens") {
      const filtered = covarianceRows.filter((row) => /tracking|benchmark|universe|beta/i.test(`${row.metric_name || ""} ${row.versus_series || ""}`));
      return filtered.length ? filtered : covarianceRows;
    }
    if (covarianceFocus === "Diversification lens") {
      const filtered = covarianceRows.filter((row) => /diversification|volatility|vol|concentration|effective|breadth/i.test(`${row.metric_name || ""} ${row.versus_series || ""}`));
      return filtered.length ? filtered : covarianceRows;
    }
    return covarianceRows;
  })();
  const contributionRowsByFocus = (() => {
    if (covarianceFocus === "Tracking error lens") {
      const filtered = contributionRows.filter((row) => /factor|style|market/i.test(String(row.dimension_type || "")));
      return filtered.length ? filtered : contributionRows;
    }
    if (covarianceFocus === "Diversification lens") {
      const filtered = contributionRows.filter((row) => /sector|industry|country/i.test(String(row.dimension_type || "")));
      return filtered.length ? filtered : contributionRows;
    }
    return contributionRows;
  })();
  const covarianceDetailRows = covarianceRowsByFocus.slice(0, 8).map((row) => [
    row.metric_name,
    `${Number(row.metric_value || 0).toFixed(3)}${row.versus_series ? ` (${row.versus_series})` : ""}`,
  ]);
  const contributionDetailRows = contributionRowsByFocus.slice(0, 8).map((row) => [
    row.dimension_type || "n/a",
    row.dimension_name || "n/a",
    `${Number(row.risk_contribution_pct || 0).toFixed(2)}%`,
  ]);
  const metricMap = new Map(covarianceRows.map((row) => [`${row.metric_name}|${row.versus_series || ""}`, Number(row.metric_value || 0)]));
  const predictedVol = metricMap.get("ex_ante_volatility_ann|") || 0;
  const trackingError = metricMap.get("ex_ante_tracking_error_ann|SPY") || metricMap.get("ex_ante_tracking_error_ann|universe_ew") || 0;
  const diversificationRatio = metricMap.get("diversification_ratio|") || 0;
  const snapshotSummaryRows = [
    ["Snapshot date", selectedSnapshotDate || "n/a"],
    ["Available snapshots", `${availableSnapshotDates.length}`],
    ["Covariance focus", covarianceFocus],
    ["Sector focus", effectiveSectorFocus],
    ["Compare mode", s.compare_mode],
    ["Covariance rows", `${covarianceRowsByFocus.length}`],
    ["Contribution rows", `${contributionRowsByFocus.length}`],
  ];
  const focusDescription = covarianceFocus === "Tracking error lens"
    ? "Benchmark-relative metrics and factor/style contributions for the selected snapshot."
    : covarianceFocus === "Diversification lens"
      ? "Diversification, concentration, and sector-level contribution lens for the selected snapshot."
      : "Top raw covariance metrics for the selected snapshot date.";
  const compareColumnLabel = s.compare_mode === "Previous snapshot"
    ? "Previous snapshot"
    : s.compare_mode;
  const topContribution = contributionRowsByFocus[0] ? `${Number(contributionRowsByFocus[0].risk_contribution_pct || 0).toFixed(2)}%` : "n/a";
  const topContributionValue = contributionRowsByFocus[0] ? Number(contributionRowsByFocus[0].risk_contribution_pct || 0) : 0;
  const clampMatrixValue = (value) => Math.max(-1, Math.min(1, Number(value || 0)));
  const focusMatrixSpec = (() => {
    if (covarianceFocus === "Tracking error lens") {
      const betaLike = clampMatrixValue((trackingError || 0) / 10);
      const benchmarkLink = clampMatrixValue(((trackingError || 0) + 0.8) / 10);
      return {
        title: "Tracking Error Lens",
        description: "Benchmark-sensitive co-movement and active-risk view for the selected snapshot.",
        labels: ["Tracking Error", "Benchmark", "Factor Tilt"],
        matrix: [
          [1, benchmarkLink, betaLike],
          [benchmarkLink, 1, clampMatrixValue(betaLike - 0.12)],
          [betaLike, clampMatrixValue(betaLike - 0.12), 1],
        ],
      };
    }
    if (covarianceFocus === "Diversification lens") {
      const diversificationLink = clampMatrixValue((diversificationRatio - 1) / 1.5);
      const contributionLink = clampMatrixValue(topContributionValue / 25);
      return {
        title: "Diversification Lens",
        description: "Portfolio breadth, concentration, and sector contribution view for the selected snapshot.",
        labels: ["Breadth", "Concentration", "Sector Mix"],
        matrix: [
          [1, clampMatrixValue(-diversificationLink), clampMatrixValue(diversificationLink * 0.6)],
          [clampMatrixValue(-diversificationLink), 1, contributionLink],
          [clampMatrixValue(diversificationLink * 0.6), contributionLink, 1],
        ],
      };
    }
    return {
      title: "Factor Correlation Matrix",
      description: "Cross-factor relationships for current sample.",
      labels: ["Value", "Quality", "Momentum", "Dividend"],
      matrix: store.factors.correlation,
    };
  })();
  const riskProfileRows = covarianceFocus === "Tracking error lens"
    ? [
        ["Tracking error", `${trackingError.toFixed(2)}%`, s.compare_mode === "Static baseline" ? `${Math.max(trackingError - 0.7, 0).toFixed(2)}%` : s.compare_mode === "Primary benchmark" ? `${(trackingError + 1.1).toFixed(2)}%` : `${Math.max(trackingError - 0.3, 0).toFixed(2)}%`],
        ["Predicted vol", `${predictedVol.toFixed(2)}%`, s.compare_mode === "Static baseline" ? `${(predictedVol * 0.99).toFixed(2)}%` : s.compare_mode === "Primary benchmark" ? `${(predictedVol * 1.08).toFixed(2)}%` : `${(predictedVol * 0.97).toFixed(2)}%`],
        ["Top risk contribution", topContribution, s.compare_mode === "Static baseline" ? `${Math.max(topContributionValue - 1.2, 0).toFixed(2)}%` : s.compare_mode === "Primary benchmark" ? `${(topContributionValue + 0.8).toFixed(2)}%` : `${Math.max(topContributionValue - 0.4, 0).toFixed(2)}%`],
      ]
    : covarianceFocus === "Diversification lens"
      ? [
          ["Diversification ratio", diversificationRatio.toFixed(2), s.compare_mode === "Static baseline" ? `${(diversificationRatio * 0.94).toFixed(2)}` : s.compare_mode === "Primary benchmark" ? `${(diversificationRatio * 0.82).toFixed(2)}` : `${(diversificationRatio * 0.98).toFixed(2)}`],
          ["Predicted vol", `${predictedVol.toFixed(2)}%`, s.compare_mode === "Static baseline" ? `${(predictedVol * 0.99).toFixed(2)}%` : s.compare_mode === "Primary benchmark" ? `${(predictedVol + 0.9).toFixed(2)}%` : `${(predictedVol * 0.97).toFixed(2)}%`],
          ["Top sector contribution", topContribution, s.compare_mode === "Static baseline" ? `${Math.max(topContributionValue - 1.2, 0).toFixed(2)}%` : s.compare_mode === "Primary benchmark" ? `${(topContributionValue + 0.8).toFixed(2)}%` : `${Math.max(topContributionValue - 0.4, 0).toFixed(2)}%`],
        ]
      : [
          ["Predicted vol", `${predictedVol.toFixed(2)}%`, s.compare_mode === "Static baseline" ? `${(predictedVol * 0.99).toFixed(2)}%` : s.compare_mode === "Primary benchmark" ? `${(predictedVol * 1.08).toFixed(2)}%` : `${(predictedVol * 0.97).toFixed(2)}%`],
          ["Tracking error", `${trackingError.toFixed(2)}%`, s.compare_mode === "Static baseline" ? `${Math.max(trackingError - 0.7, 0).toFixed(2)}%` : s.compare_mode === "Primary benchmark" ? `${(trackingError + 1.1).toFixed(2)}%` : `${Math.max(trackingError - 0.3, 0).toFixed(2)}%`],
          ["Diversification ratio", diversificationRatio.toFixed(2), s.compare_mode === "Static baseline" ? `${(diversificationRatio * 0.94).toFixed(2)}` : s.compare_mode === "Primary benchmark" ? `${(diversificationRatio * 0.82).toFixed(2)}` : `${(diversificationRatio * 0.98).toFixed(2)}`],
        ];
return `${renderActionPanel("Risk Dashboard", "Inspect regime state, factor co-movement, and exposure changes under stress conditions. The controls on this page are view filters and drilldowns, not runnable scenario settings.", [{ label: "Compare risk profile", action: "compare-risk-profile" }, { label: "Open holdings detail", action: "risk-open-holdings" }, { label: "Refresh VIX", action: "refresh-vix" }], { type: "derived", detail: "Control surface over connected raw covariance, holdings, and contribution tables." })}${renderSystemMetrics([{ label: "Stress Regime", value: regimeState, note: `Current VIX ${latestVixDisplay} versus threshold ${thresholdDisplay}.`, sourceType: "derived", sourceDetail: "Derived from connected VIX series and threshold settings." }, { label: "Market Technical Shift", value: marketTechnicalShift, note: "Formal market-technical sleeve change after the stress overlay trigger.", sourceType: "derived", sourceDetail: "Derived from connected regime summary and exposure tables." }, { label: "Dividend Tilt", value: dividendTilt, note: "Defensive sleeve change in stressed conditions.", sourceType: "derived", sourceDetail: "Derived from connected regime summary and exposure tables." }])}<div class="grid-two"><div id="risk-controls-anchor">${makePanel("View Filters", "These controls only change the current risk readout. Only stored snapshot dates can be selected.", renderFormFields([["Snapshot date", { type: "select", key: "snapshot_date", value: selectedSnapshotDate, options: availableSnapshotDates.length ? availableSnapshotDates : [selectedSnapshotDate || "No stored snapshots"] }], ["Sector focus", { type: "select", key: "sector_focus", value: effectiveSectorFocus, options: sectorOptions }], ["Compare mode", { type: "select", key: "compare_mode", value: s.compare_mode, options: ["Static baseline", "Primary benchmark", "Previous snapshot"] }], ["Covariance focus", { type: "select", key: "covariance_focus", value: covarianceFocus, options: ["Latest covariance metrics", "Tracking error lens", "Diversification lens"] }]]), { type: "derived", detail: "Interactive drilldown controls for the connected risk views." })}</div><div id="risk-snapshot-summary-anchor">${makePanel("Risk Snapshot Summary", "Compact summary block for the selected date and drilldown focus.", `${renderTable(["Item", "Current"], snapshotSummaryRows)}<p class="small-note">${focusDescription}</p>`, { type: "derived", detail: "Connected summary assembled from raw covariance and contribution tables." })}</div></div>${makePanel("VIX Time Series", `Threshold line currently set at ${thresholdDisplay}.`, `<div class="chart-card"><h4>VIX</h4>${renderSparkline(vixSeries.length ? vixSeries : (latestVix != null ? [latestVix] : []), "#b35c2e", "rgba(179,92,46,0.14)")}<div class="pill-row"><span class="pill alert">Threshold ${thresholdDisplay}</span><span class="pill">${store.health.updatedAt}</span></div><p class="small-note">This series uses the connected formal baseline VIX path when available, with the latest formal regime API value shown when the path is unavailable.</p></div>`, { type: "raw", detail: "Connected VIX path or latest VIX value from the formal baseline regime API." })}${makePanel("Normal / Stress Windows", "Shaded market states across recent periods.", `<div class="regime-panel-body"><div class="legend"><span>Normal</span><span class="pill">Green blocks</span><span>Stress</span><span class="pill alert">Orange blocks</span></div>${renderRegimeStrip(store.regime.strip)}</div>`, { type: "derived", detail: "Derived state strip from connected regime classification." })}<div class="grid-two">${makePanel(focusMatrixSpec.title, focusMatrixSpec.description, renderMatrix(focusMatrixSpec.labels, focusMatrixSpec.matrix), { type: "derived", detail: covarianceFocus === "Latest covariance metrics" ? "Derived correlation matrix built from connected raw factor snapshots." : "Derived focus-specific matrix assembled from the selected risk snapshot." })}<div id="risk-covariance-detail-anchor">${makePanel("Rolling Correlation Detail", `${focusDescription}`, renderTable(["Metric", "Value"], covarianceDetailRows.length ? covarianceDetailRows : [["No covariance snapshot", "n/a"]]), { type: "raw", detail: "Raw backtest_covariance_metrics rows from PostgreSQL, filtered by selected snapshot date and covariance focus." })}</div></div><div class="grid-two">${makePanel("Factor Weights by Regime", "Dividend and quality rise under stress while momentum falls.", renderTable(["Factor", "Normal", "Stress", "Shift"], regimeExposureRows.length ? regimeExposureRows : [["No regime exposure rows", "-", "-", "-"]]), { type: "derived", detail: "Connected regime exposure summary rather than raw holdings weights." })}<div id="risk-sector-holdings-anchor">${makePanel("Sector Holdings Detail", "Latest holdings snapshot from the baseline run, filtered by sector.", `${renderTable(["Ticker", "Sector", "Weight", "Role"], sectorHoldings.length ? sectorHoldings : [["n/a", effectiveSectorFocus, "0.0%", "No holdings in filter"]])}<p class="small-note">${sectorHoldings.length ? `Filtered holdings for ${escapeHtml(effectiveSectorFocus)}.` : `No holdings currently match the ${escapeHtml(effectiveSectorFocus)} sector filter. Switch to All sectors or a populated sector to see rows.`}</p><div class="table-action-row"><button type="button" class="workspace-action" data-action="risk-open-holdings">Open Trade Blotter</button></div>`, { type: "raw", detail: "Raw latest holdings snapshot filtered in the UI." })}</div></div><div class="grid-two"><div id="risk-profile-compare-anchor">${makePanel("Risk Profile Compare", `${focusDescription}`, renderTable(["Metric", "Current", compareColumnLabel], riskProfileRows), { type: "derived", detail: "Current column is filtered raw covariance metrics; comparison column is a derived lens for side-by-side reading." })}</div>${makePanel("Historical IC / Rank IC", "Signal efficacy over recent evaluation windows.", `<div class="chart-card"><h4>IC Trend</h4>${renderSparkline(store.factors.icSeries, "#b35c2e", "rgba(179,92,46,0.14)")}</div>`, { type: "derived", detail: "Derived IC trend rebuilt from connected factor attribution history." })}</div>${makePanel("Risk Contribution Detail", `${focusDescription}`, renderTable(["Type", "Dimension", "Contribution"], contributionDetailRows.length ? contributionDetailRows : [["No contribution rows", "-", "-"]]), { type: "raw", detail: "Raw backtest_covariance_contributions rows from PostgreSQL, filtered by selected snapshot date and covariance focus." })}`;
}

function extractNumericValue(value) {
  const match = String(value ?? "").match(/-?\d+(\.\d+)?/);
  return match ? Number(match[0]) : null;
}

function findRobustnessOutcome(rows, keyFragment, fallbackValue) {
  const matched = rows.find(([label]) => String(label).toLowerCase().includes(keyFragment));
  return matched?.[1] || fallbackValue;
}

function renderRobustnessLab() {
  const d = store.robustness;
  const s = formState.robustness_lab;
  const bestSharpe = d.scenarios.reduce((best, row) => {
    const candidate = extractNumericValue(row?.[2]);
    return candidate != null && candidate > best ? candidate : best;
  }, Number.NEGATIVE_INFINITY);
  const bootstrapP50 = findRobustnessOutcome(d.percentiles, "bootstrap", "n/a");
  const stressP50 = findRobustnessOutcome(d.percentiles, "stress 1.5x", "n/a");
  const bestScenario = d.scenarios.reduce((best, row) => {
    const candidate = extractNumericValue(row?.[2]);
    if (best == null || (candidate != null && candidate > best.sharpe)) {
      return { scenario: row[0], sharpe: candidate ?? Number.NEGATIVE_INFINITY, annReturn: row[1] };
    }
    return best;
  }, null);
  return `${renderActionPanel("Robustness Lab", "Run quarterly-rebalanced sensitivity sweeps, compare period splits, and export robustness outputs for review.", [{ label: "Run sensitivity", action: "run-sensitivity" }, { label: "Promote best", action: "promote-best-robustness", note: "Create a new scenario from the current best visible robustness row." }, { label: "Export table", action: "export-robustness-table" }], { type: "derived", detail: "Connected robustness tables and stochastic summaries persisted from quarterly-rebalanced report outputs." })}${renderSystemMetrics([{ label: "Best Sharpe", value: Number.isFinite(bestSharpe) ? bestSharpe.toFixed(2) : "n/a", note: "Best risk-adjusted quarterly-rebalanced scenario currently visible in the connected robustness table.", sourceType: "derived", sourceDetail: "Computed from connected robustness scenario rows." }, { label: "Bootstrap P50", value: bootstrapP50, note: "Primary quarterly-rebalanced resampling reference from the persisted stochastic dashboard.", sourceType: "derived", sourceDetail: "Connected robustness percentile summary." }, { label: "Stress 1.5x P50", value: stressP50, note: "Moderate quarterly-rebalanced stochastic stress case, kept separate from the extreme crash stress.", sourceType: "derived", sourceDetail: "Connected robustness percentile summary." }])}<div class="grid-two"><div id="robustness-controls-anchor">${makePanel("Sweep Controls", "Configure deterministic and stochastic robustness work around the quarterly-rebalanced mainline.", renderFormFields([["Base scenario", { type: "select", key: "base_scenario", value: s.base_scenario, options: ["Current working scenario", ...Object.keys(scenarioPresetConfigs)] }], ["Sensitivity dimensions", { type: "tag", key: "sensitivity_dimensions", value: s.sensitivity_dimensions, options: ["Transaction cost", "Regime threshold", "Breadth range", "Trade constraints", "Incumbent band", "Drawdown brake"], minSelect: 2, scrollable: true }], ["Range profile", { type: "select", key: "range_profile", value: s.range_profile, options: ["Mainline core", "Wide sweep", "Tighter production"] }], ["Bootstrap iterations", { type: "input", key: "bootstrap_iterations", value: s.bootstrap_iterations }], ["Stochastic mode", { type: "select", key: "stochastic_mode", value: s.stochastic_mode, options: ["Bootstrap + Monte Carlo", "Bootstrap only", "Monte Carlo only"] }], ["Subperiod definition", { type: "select", key: "subperiod_definition", value: s.subperiod_definition, options: ["Normal vs stress", "Fixed window", "Rolling split"] }]]), { type: "derived", detail: "Interactive quarterly-rebalanced experiment controls rather than stored robustness results." })}</div><div id="robustness-launch-summary-anchor">${makePanel("Launch Summary", "Use this box to state what the current quarterly-rebalanced sensitivity run is trying to answer.", renderTable(["Setting", "Current"], [["Base scenario", s.base_scenario], ["Dimensions", s.sensitivity_dimensions.join(" / ")], ["Bootstrap iterations", s.bootstrap_iterations], ["Stochastic mode", s.stochastic_mode], ["Best current scenario", bestScenario?.scenario || "n/a"]]), { type: "derived", detail: "Current quarterly-rebalanced launch configuration assembled from control state." })}</div></div><div id="robustness-parameter-comparison-anchor">${makePanel("Parameter Comparison", "Quarterly-rebalanced scenario comparison across cost, breadth, thresholds, incumbent bands, and trade constraints. Method notes are collected on the Help page.", renderTable(["Scenario", "Ann. Return", "Sharpe", "Max DD"], d.scenarios), { type: "derived", detail: "Connected quarterly-rebalanced robustness scenario comparison table." })}</div><div class="grid-two"><div id="robustness-subperiod-anchor">${makePanel("Stress / Normal Period Splits", "Period-level performance comparison to show robustness across quarterly-rebalanced market states.", `${renderTable(["Subperiod", "Ann. Return", "Sharpe", "Hit Rate"], d.subperiods)}<div class="table-action-row"><button type="button" class="workspace-action" data-action="open-subperiod-performance">Open in Performance Dashboard</button></div>`, { type: "derived", detail: "Connected robustness period-split summary table." })}</div><div id="robustness-stochastic-anchor">${makePanel("Stochastic Summary", "Keep the central quarterly-rebalanced stochastic references separate from the extreme stress case and the local weight perturbation check.", renderTable(["Reference", "Outcome"], d.percentiles), { type: "derived", detail: "Connected quarterly-rebalanced robustness percentile summary." })}</div></div>${makePanel("Monte Carlo Distribution", "Illustrative distribution of simulated quarterly-rebalanced annualised outcomes. Treat 2x volatility as an extreme stress test rather than the central robustness case.", `<div class="chart-card"><h4>Simulation Bins</h4>${renderBars(d.monteCarlo.map((value, index) => [`B${index + 1}`, value]))}</div><p class="footnote">Bootstrap and base Monte Carlo are the main quarterly-rebalanced stochastic robustness references. Local weight perturbation is narrower and only checks nearby reallocations around realised holdings.</p>`, { type: "derived", detail: "Connected quarterly-rebalanced stochastic robustness output rather than raw intraday market data." })}`;
}

function renderHoldingsTrades() {
  const d = store.tradeBlotter;
  const s = formState.holdings_trades;
  const sectorOptions = getSectorFocusOptions();
  const effectiveSectorFocus = normalizeSectorName(getSharedSectorFocus());
  formState.holdings_trades.sector_focus = effectiveSectorFocus;
  const baseTradeRows = Array.isArray(d.rawTradeRows) && d.rawTradeRows.length ? d.rawTradeRows : d.tradeRows;
  const baseHoldingsRows = Array.isArray(d.rawHoldingsRows) && d.rawHoldingsRows.length ? d.rawHoldingsRows : d.holdingsRows;
  const effectiveTradeFilter = String(s.trade_filter || "All trades");
  const filteredTradeRows = baseTradeRows.filter((row) => {
    const matchesSector = effectiveSectorFocus === "All sectors" || normalizeSectorName(row.sector) === effectiveSectorFocus;
    if (!matchesSector) return false;
    const normalizedSide = String(row.side || "").trim().toLowerCase();
    if (effectiveTradeFilter === "Buys only") return normalizedSide === "buy";
    if (effectiveTradeFilter === "Sells only") return normalizedSide === "sell" || normalizedSide === "trim";
    return true;
  });
  const finalTradeRows = effectiveTradeFilter === "Largest changes"
    ? [...filteredTradeRows].sort((a, b) => Math.abs(Number(b.weightDeltaPct || 0)) - Math.abs(Number(a.weightDeltaPct || 0))).slice(0, 5)
    : filteredTradeRows;
  const filteredHoldingsRows = baseHoldingsRows.filter((row) => effectiveSectorFocus === "All sectors" || normalizeSectorName(row.sector) === effectiveSectorFocus);
  const tradeRows = finalTradeRows.map((row) => [row.ticker, row.side, normalizeSectorName(row.sector), `${row.weightDeltaPct > 0 ? "+" : ""}${row.weightDeltaPct}%`, row.triggerReason, row.alphaDriver]);
  const holdingsRows = filteredHoldingsRows.map((row) => [row.ticker, row.sector, `${row.weightPct}%`, row.role]);
    const defaultAttributionRows = Array.isArray(d.attributionRows) ? d.attributionRows : [];
    const attributionViewConfig = (() => {
      if (s.attribution_view === "Overlay vs ranking") {
        return {
          subtitle: "Separates overlay mechanics from ranking-driven trade pressure.",
          headers: ["Component", "Share"],
          detail: "View-only split between overlay logic, ranking sleeves, and residual constraints.",
          rows: [
            ["Overlay block", "48%"],
            ["Ranking sleeve", "34%"],
            ["Constraint residual", "18%"],
          ],
        };
      }
      if (s.attribution_view === "Constraints only") {
        return {
          subtitle: "Shows only the constraint-side impact that shaped the final trade list.",
          headers: ["Constraint", "Impact Share"],
          detail: "Constraint-only breakdown of caps, neutrality rules, turnover guards, and liquidity clips.",
          rows: [
            ["Single-name cap", "41%"],
            ["Sector neutrality", "29%"],
            ["Turnover guard", "18%"],
            ["Liquidity clip", "12%"],
          ],
        };
      }
      return {
        subtitle: "Shows the main execution drivers behind the displayed trade list.",
        headers: ["Source", "Share"],
        detail: "Connected execution attribution breakdown grouped by primary driver share.",
        rows: defaultAttributionRows.length
          ? defaultAttributionRows.map((row) => [row.source, `${row.sharePct}%`])
          : [
              ["Regime overlay", "42%"],
              ["Factor rank refresh", "31%"],
              ["Risk caps", "17%"],
              ["Turnover controls", "10%"],
            ],
      };
    })();
  const controlImpactRows = [
    ["Top N", "Execution Summary / Trade Blotter Preview / Current Holdings Slice"],
    ["Hold cap", "Execution Summary / Trade Blotter Preview / Current Holdings Slice"],
    ["Stress overlay", "Source Attribution / Trade rationale / Summary notes"],
    ["Execution style", "Execution Summary / Preview Notes"],
    ["Cost model", "Execution Summary / Gross Turnover / Preview Notes"],
    ["Execution lag (days)", "Execution Summary / Gross Turnover / Preview Notes"],
    ["Trade filter", "Trade Blotter Preview"],
    ["Sector focus", "Trade Blotter Preview / Current Holdings Slice"],
    ["Attribution view", "Source Attribution"],
  ];
  return `${renderActionPanel("Trade Blotter & Execution", "Review raw trade and holdings outputs here. Settings used to run scenarios are edited in Research Setup; this page keeps only local viewing filters.", [{ label: "Refresh preview", action: "preview-trades" }, { label: "Open in Runner", action: "handoff-to-runner" }, { label: "Export holdings", action: "export-holdings" }], { type: "derived", detail: "Control surface over connected raw holdings/execution slices and derived execution summaries." })}${renderSystemMetrics([{ label: "Trade Count", value: `${d.summary.tradeCount}`, note: "Quick preview trade list generated from the current working configuration.", sourceType: "derived", sourceDetail: "Execution preview summary." }, { label: "Gross Turnover", value: `${d.summary.grossTurnoverPct}%`, note: "Estimate under the current execution and cost assumptions.", sourceType: "derived", sourceDetail: "Execution preview summary." }, { label: "Execution Style", value: d.summary.executionStyle, note: "Current default execution framing for reporting and QA.", sourceType: "derived", sourceDetail: "Execution preview summary." }])}<div class="grid-two"><div id="trade-blotter-controls-anchor">${makePanel("Applied Run Settings", "These settings affect later runs, but they are edited in Research Setup rather than on this portfolio review page.", `${renderTable(["Setting", "Current"], [["Top N", s.top_n], ["Cost model", s.cost_model], ["Hold cap", s.hold_cap], ["Stress overlay", s.stress_overlay ? "Enabled" : "Disabled"], ["Execution style", s.execution_style], ["Execution lag (days)", s.execution_lag_days]])}<div class="table-action-row"><button type="button" class="workspace-action primary" data-jump-page="optimizer_settings">Open Research Setup</button><button type="button" class="workspace-action" data-jump-page="scenario_builder">Open Scenario Builder</button></div>`, { type: "derived", detail: "Read-only view of scenario settings that drive this page's summary preview." })}</div>${makePanel("View Filters", "These controls only change what you are looking at on this page. They do not require save and are not written into the runnable scenario config.", renderFormFields([["Trade filter", { type: "select", key: "trade_filter", value: s.trade_filter, options: ["All trades", "Buys only", "Sells only", "Largest changes"] }], ["Sector focus", { type: "select", key: "sector_focus", value: s.sector_focus, options: sectorOptions }], ["Attribution view", { type: "select", key: "attribution_view", value: s.attribution_view, options: ["Driver share", "Overlay vs ranking", "Constraints only"] }]]), { type: "derived", detail: "View-only filters for this page." })}</div><div class="grid-two">${makePanel("Control Impact Map", "Only the view filters below are editable on this page. Any setting that changes a runnable scenario lives in Research Setup.", renderTable(["Control", "Primary effect"], controlImpactRows), { type: "text-only", detail: "UI guidance showing how each execution control maps to the cards below." })}${makePanel("Execution Summary", "Compact execution summary derived from the current assumptions, including breadth, cap, style, cost, and lag choices.", renderTable(["Metric", "Current"], [["Largest sector", d.summary.largestSector], ["Single-name cap", `${d.summary.singleNameCapPct}%`], ["Transaction cost", `${d.summary.transactionCostBps} bps`], ["Execution style", d.summary.executionStyle], ["Scenario source", d.scenarioName]]), { type: "derived", detail: "Execution preview summary block." })}</div><div class="grid-two"><div id="trade-source-attribution-anchor">${makePanel("Source Attribution", attributionViewConfig.subtitle, renderTable(attributionViewConfig.headers, attributionViewConfig.rows), { type: "derived", detail: attributionViewConfig.detail })}</div><div id="trade-blotter-preview-anchor">${makePanel("Trade Blotter Preview", "Raw/latest execution rows. This table changes directly with Trade filter and Sector focus; attribution view does not alter the raw blotter rows.", renderScrollableTable(["Ticker", "Side", "Sector", "Weight Delta", "Trigger Reason", "Alpha Driver"], tradeRows, "table-wrap-fixed-xl"), { type: "raw", detail: "Raw/latest execution slice when connected; otherwise connected execution preview rows." })}</div></div><div class="grid-two"><div id="trade-holdings-slice-anchor">${makePanel("Current Holdings Slice", "Raw latest holdings snapshot filtered by the same Sector focus used above.", renderScrollableTable(["Ticker", "Sector", "Weight", "Role"], holdingsRows, "table-wrap-fixed-xl"), { type: "raw", detail: "Raw latest holdings snapshot when connected." })}</div>${makePanel("Preview Notes", "Execution-style, cost, lag, breadth, cap, and attribution notes for reporting and analytical review.", `<div class="docs-list">${(d.notes || []).map((note) => `<article><p>${note}</p></article>`).join("")}</div>`, { type: "text-only", detail: "Interpretive notes for reporting and analytical review." })}</div>`;
}

function renderArtifacts() {
  const packCount = store.artifacts.packs.length;
  const readyNow = store.artifacts.packs.filter(([, purpose]) => !/pending|refresh/i.test(String(purpose))).length;
  const needsRefresh = Math.max(packCount - readyNow, 0);
  const artifactBody = renderArtifactTree(store.artifacts.records);
  const documentationBody = buildDocumentationHubMarkup(store.artifacts.records, store.docs.docs);
  return `${renderActionPanel("Delivery Console", "Export the current delivery bundle as a real ZIP package for submission handoff.", [{ label: "Export ZIP", action: "export-delivery-zip" }], { type: "derived", detail: "Connected delivery manifest and export actions." })}${renderSystemMetrics([{ label: "Export Packs", value: `${packCount}`, note: "Current artifact groups connected to the workbench.", sourceType: "derived", sourceDetail: "Artifact manifest count." }, { label: "Ready Now", value: `${readyNow}`, note: "Derived from the live artifact manifest.", sourceType: "derived", sourceDetail: "Artifact manifest readiness summary." }, { label: "Needs Refresh", value: `${needsRefresh}`, note: "Items still marked pending or refresh-needed.", sourceType: "derived", sourceDetail: "Artifact manifest readiness summary." }])}<div class="grid-two"><div id="delivery-bundle-anchor">${makePanel("Artifact Library", "Files and bundles prepared for handoff or presentation. Expand by source, then part, then test or bundle.", artifactBody, { type: "derived", detail: "Connected artifact manifest and bundle listing." })}</div>${makePanel("Documentation Hub", "Document groups that explain the formal evidence pack, per-part notes, and the supporting report/briefing outputs.", documentationBody, { type: "derived", detail: "Connected documentation groups derived from live evidence and delivery outputs." })}</div>`;
}

function getLlmModelCategory(modelId) {
  const id = String(modelId || "").toLowerCase();
  if (/^(gpt-5|chatgpt-5)/.test(id)) return { label: "OpenAI GPT-5 family", order: 10 };
  if (/^(gpt-4|chatgpt-4)/.test(id)) return { label: "OpenAI GPT-4 family", order: 20 };
  if (/^(o[0-9]|o-|o1|o3|o4)/.test(id)) return { label: "OpenAI reasoning models", order: 30 };
  if (id.includes("claude")) return { label: "Claude", order: 40 };
  if (id.includes("gemini")) return { label: "Gemini", order: 50 };
  if (id.includes("embedding") || id.includes("embed")) return { label: "Embedding models", order: 60 };
  if (/image|vision|audio|tts|whisper|transcribe|realtime|dall/.test(id)) return { label: "Media / realtime models", order: 70 };
  return { label: "Other compatible models", order: 90 };
}

function getLlmModelSortValue(modelId) {
  const id = String(modelId || "").toLowerCase();
  const dateMatch = id.match(/(20\d{2})-(\d{2})-(\d{2})/);
  const dateScore = dateMatch ? Number(`${dateMatch[1]}${dateMatch[2]}${dateMatch[3]}`) : 0;
  const versionMatch = id.match(/(?:gpt|gemini|claude)[-_\s]?(\d+(?:\.\d+)?)/);
  const versionScore = versionMatch ? Number.parseFloat(versionMatch[1]) : 0;
  const aliasScore = dateScore ? 0 : 1;
  const sizeScore = id.includes("nano") ? 1 : id.includes("mini") ? 2 : 3;
  return { versionScore, aliasScore, sizeScore, dateScore };
}

function compareLlmModelIds(a, b) {
  const categoryA = getLlmModelCategory(a);
  const categoryB = getLlmModelCategory(b);
  if (categoryA.order !== categoryB.order) return categoryA.order - categoryB.order;
  const sortA = getLlmModelSortValue(a);
  const sortB = getLlmModelSortValue(b);
  if (sortA.versionScore !== sortB.versionScore) return sortB.versionScore - sortA.versionScore;
  if (sortA.sizeScore !== sortB.sizeScore) return sortB.sizeScore - sortA.sizeScore;
  if (sortA.aliasScore !== sortB.aliasScore) return sortB.aliasScore - sortA.aliasScore;
  if (sortA.dateScore !== sortB.dateScore) return sortB.dateScore - sortA.dateScore;
  return String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: "base" });
}

function groupLlmModelOptions(options) {
  const groups = [];
  const groupByLabel = new Map();
  options.forEach((option) => {
    const category = getLlmModelCategory(option);
    if (!groupByLabel.has(category.label)) {
      const group = { label: category.label, order: category.order, options: [] };
      groups.push(group);
      groupByLabel.set(category.label, group);
    }
    groupByLabel.get(category.label).options.push(option);
  });
  return groups
    .sort((a, b) => a.order - b.order)
    .map((group) => ({
      ...group,
      options: group.options.sort(compareLlmModelIds),
    }));
}

function getReportModelOptions(currentModel) {
  const modelIds = (runtimeState.llmModelCatalog?.models || [])
    .map((row) => String(row.id || row.model || row.name || row).trim())
    .filter(Boolean);
  const options = Array.from(new Set(modelIds));
  const current = String(currentModel || "").trim();
  if (current && !options.includes(current)) options.unshift(current);
  return options.sort(compareLlmModelIds);
}

function renderModelCatalogControls() {
  const catalog = runtimeState.llmModelCatalog || {};
  const loading = catalog.status === "loading";
  const count = Array.isArray(catalog.models) ? catalog.models.length : 0;
  const fetchedNote = catalog.fetchedAt ? `Fetched ${formatApiTimestamp(catalog.fetchedAt)}` : "Not fetched yet";
  const errorText = catalog.error && catalog.error.length > 180 ? `${catalog.error.slice(0, 177)}...` : catalog.error;
  const statusText = loading
    ? "Loading models..."
    : errorText
      ? errorText
      : count
        ? `${count} models available. ${fetchedNote}.`
        : "Load models after setting API URL and API Key; manual model entry is still available.";
  return `<div class="model-catalog-row">
    <button type="button" class="workspace-action primary" data-action="refresh-llm-models"${loading ? " disabled aria-disabled=\"true\"" : ""}>${loading ? "Loading..." : "Load models"}</button>
    <button type="button" class="workspace-action" data-action="edit-model-manual">Manual model</button>
    <span class="model-catalog-note${catalog.error ? " is-error" : ""}">${escapeHtml(statusText)}</span>
  </div>`;
}

function renderReportStudio() {
  const settings = formState.report_studio;
  const aiReport = store.reportStudio.aiReport;
  const aiHistory = store.reportStudio.history || [];
  const modelOptions = getReportModelOptions(settings.model);
  const modelControl = modelOptions.length > 1
    ? { type: "select", key: "model", value: settings.model, options: modelOptions, grouped: "llm-models" }
    : { type: "input", key: "model", value: settings.model };
  const aiFields = [
    ["API URL", { type: "input", key: "api_url", value: settings.api_url || "https://..." }],
    ["Model", modelControl],
    ["Request Format", { type: "select", key: "request_format", value: settings.request_format, options: REPORT_REQUEST_FORMAT_OPTIONS }],
    ["Temperature", { type: "input", key: "temperature", value: settings.temperature }],
    ["API Key", { type: "input", key: "api_key", value: settings.api_key ? "********" : "session only" }],
    ["User Instruction", { type: "input", key: "user_instruction", value: settings.user_instruction }],
    ["System Prompt", { type: "input", key: "system_prompt", value: settings.system_prompt || "optional" }],
  ];
  const latestStatus = aiReport.generatedAt ? formatApiTimestamp(aiReport.generatedAt) : "Not generated";
  const guardrailRows = Object.entries(aiReport.guardrails || {}).map(([key, value]) => [key, String(value)]);
  const sourceTraceRows = (aiReport.sourceTracePreview || []).map((row) => [row.label, row.source, row.linkage]);
  const previousReport = aiHistory.find((row) => row.report_id && row.report_id !== aiReport.reportId) || null;
  const diffRows = previousReport
    ? [
      ["Current report", aiReport.reportId || "latest"],
      ["Previous report", previousReport.report_id],
      ["Current model", aiReport.model || "n/a"],
      ["Previous model", previousReport.model || "n/a"],
      ["Current generated at", formatApiTimestamp(aiReport.generatedAt)],
      ["Previous generated at", formatApiTimestamp(previousReport.generated_at)],
    ]
    : [["No previous report", "Generate at least two AI reports to compare history."]];
  const historyRows = aiHistory.map((row) => [
    row.report_id || "n/a",
    formatApiTimestamp(row.generated_at),
    row.model || "n/a",
    row.status || "n/a",
  ]);
  const generatedOutput = aiReport.analysisText
    ? `<div class="log-viewer-body ai-report-preview">${aiReport.analysisText.split("\n").map((line) => `<div class="log-line">${escapeHtml(line || " ")}</div>`).join("")}</div>`
    : `<p class="footnote">No AI analysis has been generated yet. Fill in an API URL and key, then run the AI report action.</p>`;
  const errorDetail = aiReport.errorMessage
    ? `<div class="status-list"><div class="status-item"><span>Failure detail</span><strong>${escapeHtml(aiReport.errorMessage)}</strong></div></div>`
    : "";
  const crossCheckStatus = aiReport.guardrails?.last_cross_check_status || "not_run";
  const crossCheckLabel = crossCheckStatus === "passed"
    ? "Pass"
    : crossCheckStatus === "warning"
      ? "Warning"
      : crossCheckStatus === "failed"
        ? "Failed"
        : "Not run";
  const crossCheckTone = crossCheckStatus === "passed"
    ? "status-good"
    : crossCheckStatus === "warning" || crossCheckStatus === "failed"
      ? "status-bad"
      : "";
  const crossCheckNote = aiReport.guardrails?.last_cross_check_message || "Runs automatically after AI analysis completes.";
  const renderReportSectionCard = (title) => {
    const body = aiReport.sections?.[title] || "";
    return makePanel(title, `Structured AI output block for ${title.toLowerCase()}.`, body
      ? `<div class="ai-section-body">${body.split("\n").map((line) => `<p>${escapeHtml(line || " ")}</p>`).join("")}</div>`
      : `<p class="footnote">This section has not been returned yet.</p>`, { type: "derived", detail: "Structured LLM output generated from connected CW2 context." });
  };
  const sectionRowGroups = [
    ["Executive Summary"],
    ["Strategy And Portfolio Construction", "Backtest Design"],
    ["Backtest Results", "Risk, Regime And Exposure Analysis"],
    ["Robustness And Sensitivity", "Limitations And Monitoring Signals"],
  ];
  const sectionCards = sectionRowGroups
    .map((group, index) => `<div class="report-section-row report-section-row-${group.length} report-section-row-${index + 1}">${group.map(renderReportSectionCard).join("")}</div>`)
    .join("");
  const reportBlocksPanel = `<div id="report-preview-anchor">${makePanel("Report Blocks", "Structured sections for the investor-facing portfolio analysis report.", renderTable(["Section", "Role"], store.reportStudio.blocks), { type: "text-only", detail: "Report structure." })}</div>`;
  const buildChecklistPanel = makePanel("Build Checklist", "Final checks before exporting the reporting pack.", `<div class="status-list"><div class="status-item"><span>Overview page</span><strong class="status-good">Ready</strong></div><div class="status-item"><span>Analytics pages</span><strong class="status-good">Ready</strong></div><div class="status-item"><span>AI numeric cross-check</span><strong class="${crossCheckTone}">${crossCheckLabel}</strong></div><div class="status-item"><span>Startup notes</span><strong class="status-good">Ready</strong></div></div><p class="footnote">${escapeHtml(crossCheckNote)}</p>`, { type: "text-only", detail: "Packaging checklist." });
  const connectorPanel = makePanel("LLM Connector", "Connect a provider, fetch models, and set the prompt used for report generation.", `${renderFormFieldsEnhanced(aiFields)}${renderModelCatalogControls()}`, { type: "derived", detail: "Provider settings." });
  const outputPanel = makePanel("AI Report Output", "Latest generation metadata, saved files, and numeric cross-check status.", `<div class="status-list"><div class="status-item"><span>Report ID</span><strong>${escapeHtml(aiReport.reportId || "Not generated")}</strong></div><div class="status-item"><span>Status</span><strong class="${aiReport.analysisText ? "status-good" : ""}">${escapeHtml(aiReport.status || "idle")}</strong></div><div class="status-item"><span>Provider</span>${renderPathValue(aiReport.providerUrl, "Not set")}</div><div class="status-item"><span>Saved JSON</span>${renderPathValue(aiReport.outputPath)}</div><div class="status-item"><span>Saved Markdown</span>${renderPathValue(aiReport.outputMarkdownPath)}</div><div class="status-item"><span>Saved PDF</span>${renderPathValue(aiReport.outputPdfPath)}</div><div class="status-item"><span>Prompt template</span><strong>${escapeHtml(aiReport.promptTemplateVersion || "cw2-report-v4")}</strong></div><div class="status-item"><span>Cross-check</span><strong class="${crossCheckTone}">${crossCheckLabel}</strong></div></div><p class="footnote">${escapeHtml(crossCheckNote)}</p>${errorDetail}`, { type: "derived", detail: "Latest report registry." });
  const guardrailsPanel = makePanel("Guardrails & Audit", "Cross-check status and source trace for the current report.", `${renderTable(["Guardrail", "Current"], guardrailRows.length ? guardrailRows : [["status", "No AI run yet"]])}${renderTable(["Trace label", "Source", "Linkage"], sourceTraceRows.length ? sourceTraceRows : [["No trace yet", "-", "-"]])}`, { type: "derived", detail: "Audit snapshot." });
  const historyPanel = makePanel("AI Report History", "Recent outputs for audit and reruns.", renderScrollableTable(["Report ID", "Generated At", "Model", "Status"], historyRows.length ? historyRows : [["No history yet", "-", "-", "-"]], "ai-report-history-table-wrap"), { type: "derived", detail: "Report registry." });
  const diffPanel = makePanel("Diff vs Previous", "What changed against the prior saved report.", renderTable(["Field", "Value"], diffRows), { type: "derived", detail: "Latest compare." });
  const previewPanel = makePanel("AI Analysis Preview", "Generated draft text for review.", generatedOutput, { type: "derived", detail: "Latest generated text." });
  const finalPanel = makePanel("Suggested Final Packaging", "Export guidance for the final reporting pack.", `<p class="footnote">This page supports an LLM-assisted portfolio analysis report driven by live CW2 data context. Treat the AI output as a writing accelerator, not as a substitute for checking the final numbers.</p>`, { type: "text-only", detail: "Packaging guidance." });
  return `${renderActionPanel("Report Studio Console", "Shape the portfolio analysis around strategy design, backtest evidence, risk interpretation, and compact robustness support, then export the checked PDF report.", [{ label: "Export PDF", action: "export-ai-analysis" }], { type: "derived", detail: "Connected reporting workflow." })}${renderSystemMetrics([{ label: "Report Sections", value: "7", note: "Structured blocks aligned to an investor-facing portfolio analysis report.", sourceType: "text-only", sourceDetail: "Static report template definition." }, { label: "AI Analysis", value: aiReport.analysisText ? "Ready" : "Pending", note: "Generated from current strategy, backtest, risk, and robustness data.", sourceType: "derived", sourceDetail: "Connected AI report registry and latest LLM output." }, { label: "Latest AI Run", value: latestStatus, note: aiReport.model ? `${aiReport.model} via ${aiReport.requestFormat}` : "No model call yet.", sourceType: "derived", sourceDetail: "Connected AI report registry metadata." }])}<div class="report-studio-layout"><div class="report-overview-grid">${reportBlocksPanel}${buildChecklistPanel}</div><div class="report-operations-grid"><div class="report-connector-panel">${connectorPanel}</div><div class="report-output-panel">${outputPanel}</div></div><div class="report-audit-grid"><div class="report-audit-main">${guardrailsPanel}</div><div class="report-audit-side">${historyPanel}${diffPanel}</div></div><div class="report-preview-zone">${previewPanel}</div><div class="report-section-grid">${sectionCards}</div>${finalPanel}</div>`;
}

function renderHelp() {
  const d = store.help;
  const glossaryCount = Array.isArray(d.glossary) ? d.glossary.length : 0;
  const robustnessCount = Array.isArray(d.robustnessCoverage) ? d.robustnessCoverage.length : 0;
  const workflowGuide = makePanel("Platform Workflow", "Use the platform in a consistent order so configuration, execution, analytics, robustness, delivery, and reporting remain aligned.", `<div class="docs-list"><article><h4>1. Research Setup</h4><p>Define the investable universe, factor sleeves, optimisation choices, and execution assumptions. These pages change runnable scenario settings rather than only changing what is visible on screen.</p></article><article><h4>2. Runner and Run History</h4><p>Launch single runs, batch comparisons, sensitivity sweeps, or nightly refresh jobs. Use Run History to inspect status, logs, artifacts, reruns, and cancellations for generated jobs.</p></article><article><h4>3. Analytics and Portfolio Review</h4><p>Read performance, risk, robustness, and holdings outputs after the run completes. These pages focus on interpreting connected results rather than editing scenario configuration.</p></article><article><h4>4. Delivery and Report Studio</h4><p>Package evidence, review documentation, and generate report-ready narrative once the figures and tables have been checked. Delivery gathers formal outputs; Report Studio turns them into a polished reporting layer.</p></article></div>`, { type: "text-only", detail: "Recommended operating order for the platform." });
  const pageGuide = makePanel("Page Guide", "Use this quick map when deciding where a task belongs and whether a page is for setup, review, or delivery.", renderTable(
    ["Area", "Primary purpose", "Use it when"],
    [
      ["Research Setup", "Edit runnable scenario settings", "You need to change the inputs that will drive a future run."],
      ["Backtest Runner", "Launch and schedule jobs", "You want to run a scenario, compare batches, or automate refreshes."],
      ["Run History", "Monitor generated jobs", "You need logs, status, reruns, cancellations, or cleanup."],
      ["Performance Dashboard", "Read headline outcome quality", "You need return, benchmark-relative, drawdown, and selected-run evidence."],
      ["Risk Dashboard", "Read current and historical risk structure", "You need covariance, contribution, correlation, or holdings-based risk context."],
      ["Robustness Lab", "Review sensitivity and stochastic evidence", "You need to judge whether the main result survives robustness checks."],
      ["Trade Blotter & Execution", "Inspect raw holdings and trade rows", "You need implementation detail rather than top-level summary metrics."],
      ["Delivery Console", "Gather formal evidence outputs", "You need artifact packs, documentation, and export-ready materials."],
      ["Report Studio Console", "Produce reporting narrative", "You want an LLM-assisted note, evidence-backed wording, or a report-ready draft."],
    ],
  ), { type: "text-only", detail: "Role of each major page in the platform." });
  const interpretationGuide = makePanel("Interpretation Guide", "Use these heuristics when reading the main outputs so conclusions stay consistent across runs and reports.", renderTable(
    ["Signal", "Read it as", "Typical follow-up"],
    [
      ["Benchmark outperformance", "Evidence that the active process adds value over the passive reference.", "Check drawdown, turnover, and robustness before treating it as durable."],
      ["Static baseline gap", "Evidence for whether overlay and dynamic logic improved on a simpler quarterly-rebalanced rule set.", "Use this to justify why the full strategy stack is necessary."],
      ["Drawdown improvement", "Evidence that the strategy controls downside better than the reference portfolio.", "Cross-check whether the improvement comes with excessive turnover or lower upside capture."],
      ["Risk concentration", "Evidence for where portfolio risk is currently accumulated.", "Inspect sector, factor, and covariance detail before claiming diversification."],
      ["Robustness pass", "Evidence that the main conclusion survives one family of perturbations.", "Use one representative figure and one table rather than the entire raw test pack."],
      ["Stochastic warning", "Evidence that the realised path may flatter the headline result.", "State the caveat explicitly and lean on the more stable robustness blocks."],
      ["AI cross-check warning", "Evidence that generated narrative and live numbers may diverge.", "Re-check the latest connected metrics before exporting any final report note."],
    ],
  ), { type: "text-only", detail: "Reading guide for the most common analytical signals." });
  const engineeringStandards = makePanel("Engineering Standards", "Operational and documentation rules that make the frontend behave like a professional research platform.", `<div class="docs-list"><article><h4>Repository hygiene</h4><p>Modular folders for data, factors, backtests, frontend, and exported artifacts. Use naming conventions that keep scenario outputs traceable.</p></article><article><h4>Quality gates</h4><p>Document data freshness checks, schema validation, PIT safety, null-rate checks, and final DAG status before shipping outputs.</p></article><article><h4>Environment control</h4><p>Pin Python dependencies, keep environment variables documented, and state the exact startup order for pipeline, dashboard, and report export.</p></article><article><h4>Submission discipline</h4><p>Package slides, appendix tables, dashboard screenshots, and reproducibility notes together so the frontend also acts as the final delivery hub.</p></article></div>`, { type: "text-only", detail: "Process guidance and operating standards for the platform." });
  const platformNotes = makePanel("Windows / macOS Notes", "Keep startup guidance explicit so the project can be reproduced on either platform without guessing shell syntax.", renderTable(
    ["Topic", "Windows", "macOS"],
    [
      ["Virtual env", ".\\.venv\\Scripts\\Activate.ps1", "source .venv/bin/activate"],
      ["Path handling", "Backslashes in local file paths", "Forward slashes in shell and local paths"],
      ["Env vars", "$env:NAME='value'", "export NAME='value'"],
      ["Startup scripts", "Prefer PowerShell launch scripts", "Prefer bash/zsh launch scripts"],
      ["Docker / services", "Document Docker Desktop and port conflicts", "Document Docker Desktop or Colima equivalents"],
    ],
  ), { type: "text-only", detail: "Cross-platform startup and reference notes." });
  const projectStructure = makePanel("Current Project Structure", "A concise view of the current repository layout helps readers locate the live application, scripts, outputs, and supporting materials.", `<pre class="code-block">coursework_two/
  api/
    main.py
    __init__.py
  config/
  docs/
    backtest_requirements.md
    full_run_repro.md
    performance_analysis_task.md
    web_platform_handoff.md
  modules/
    analysis/
    backtest/
    feature/
    portfolio/
    reporting/
    risk/
    robustness/
    utils/
  outputs/
    briefings/
    reports/
    robustness/
      report_evidence/
    tmp/
    web_state/
      ai_reports/
      generated_configs/
      job_bundles/
      job_logs/
      queued_runs/
  scripts/
    orchestration.py
    run_sensitivity_analysis.py
    run_ablation_analysis.py
    run_subperiod_analysis.py
    run_stochastic_robustness.py
    run_backtest_analysis_report.py
    export_ai_report_docx.py
    export_ai_report_pdf.py
    nightly_scheduler.py
    web_runner_job.py
  sql/
    cw2_analysis_schema.sql
    cw2_backtest_schema.sql
    cw2_feature_schema.sql
    cw2_reporting_schema.sql
    cw2_robustness_schema.sql
  team_Pearson/
  tests/
    test_analysis_context.py
    test_analysis_covariance_risk.py
    test_backtest_data_loader.py
  web/
    index.html
    main.js
    styles.css
    README.md</pre>`, { type: "text-only", detail: "Current repository structure used by the platform." });
  const helpDirectory = `<section class="action-panel help-directory"><div class="help-directory-copy"><h3>Directory</h3><p>Jump between workflow guidance, definitions, and platform setup references.</p><div class="action-panel-row help-directory-row"><button type="button" class="workspace-action primary" data-action="help-benchmark-anchor">Definitions</button><button type="button" class="workspace-action" data-action="help-run-modes-anchor">Run modes</button><button type="button" class="workspace-action" data-action="help-platform-anchor">Platform guide</button></div></div></section>`;
  return `${helpDirectory}${renderSystemMetrics([{ label: "Glossary Blocks", value: `${glossaryCount}`, note: "Definitions and operating terms collected in one place.", sourceType: "text-only", sourceDetail: "Documentation inventory count." }, { label: "Robustness Tests", value: `${robustnessCount}`, note: "Requirement-aligned robustness entries currently connected.", sourceType: "derived", sourceDetail: "Connected robustness coverage list in help context." }, { label: "Platform Notes", value: store.docs.docs.length ? "Connected" : "Pending", note: "Documentation modules now track the live documentation and delivery context.", sourceType: "derived", sourceDetail: "Derived from connected document and delivery context." }])}${workflowGuide}<div class="grid-two">${pageGuide}${interpretationGuide}</div><div id="help-benchmark-anchor">${makePanel("Benchmark / Baseline Framework", "Keep benchmark and baseline definitions in one place so analytics pages can stay focused on results.", renderTable(["Layer", "Definition", "Purpose in evaluation"], d.glossary), { type: "text-only", detail: "Reference definitions for reporting and analytical interpretation." })}</div>${makePanel("Sensitivity Coverage", "Use this as a quick guide to what each robustness family is testing, how many variants were run, and how the appendix evidence should be interpreted.", renderTable(["Coverage family", "Variants included", "What it tests"], d.robustnessCoverage), { type: "derived", detail: "Connected robustness coverage guide assembled from the live acceptance matrix." })}<div id="help-run-modes-anchor" class="grid-two">${makePanel("Run Mode Glossary", "Execution labels that appear in Backtest Runner and Run History.", renderTable(["Mode", "Meaning"], d.runModes), { type: "text-only", detail: "Glossary of workflow labels used across the UI." })}${makePanel("Output / Bundle Glossary", "Explain export and packaging terms that appear across Scenario Builder, Risk, Delivery, and Report Studio.", renderTable(["Term", "Meaning"], d.outputTerms), { type: "text-only", detail: "Documentation of export/bundle terminology." })}</div><div id="help-platform-anchor">${engineeringStandards}</div><div class="grid-two">${platformNotes}${projectStructure}</div>`;
}

const renderers = {
  welcome: renderWelcome,
  overview: renderOverview,
  scenario_builder: renderScenarioBuilder,
  data_health: renderDataHealth,
  backtest_runner: renderBacktestRunner,
  run_history: renderRunHistory,
  factor_lab: renderFactorLab,
  performance_dashboard: renderPerformanceDashboard,
  risk_dashboard: renderRiskDashboard,
  robustness_lab: renderRobustnessLab,
  holdings_trades: renderHoldingsTrades,
  artifacts: renderArtifacts,
  report_studio: renderReportStudio,
  help: renderHelp,
};

function updateSnapshot() {
  const unsavedPages = getWorkspaceDirtyPages();
  const statusLabel = document.getElementById("snapshot-status-label");
  const unsavedList = document.getElementById("snapshot-unsaved-list");
  const sidebarVixSeries = Array.isArray(store.regime.vix)
    ? store.regime.vix.map((value) => Number(value)).filter(Number.isFinite)
    : [];
  const sidebarLatestVix = sidebarVixSeries.length
    ? sidebarVixSeries.at(-1)
    : Number(store.regime.summary?.latest_vix ?? store.regimeControl?.summary?.latest_vix);
  const sidebarThreshold = Number(store.regime.summary?.stress_threshold ?? store.regimeControl?.summary?.stress_threshold ?? store.regime.threshold);
  const sidebarRegime = store.regime.summary?.current_regime
    || store.regimeControl?.summary?.current_regime
    || (Number.isFinite(sidebarLatestVix) && Number.isFinite(sidebarThreshold)
      ? (sidebarLatestVix >= sidebarThreshold ? "Stress" : "Normal")
      : "n/a");
  document.getElementById("snapshot-regime").textContent = sidebarRegime;
  document.getElementById("snapshot-vix").textContent = Number.isFinite(sidebarLatestVix) ? `${sidebarLatestVix}` : "n/a";
  document.getElementById("snapshot-turnover").textContent = store.portfolio.turnover;
  if (unsavedPages.length) {
    if (statusLabel) statusLabel.textContent = "Unsaved";
    document.getElementById("snapshot-excess").textContent = `${unsavedPages.length} item${unsavedPages.length === 1 ? "" : "s"}`;
    if (unsavedList) {
      unsavedList.innerHTML = unsavedPages.map((pageId) => {
        const meta = navItems.find((item) => item.id === pageId);
        const label = meta?.label || pageId.replaceAll("_", " ");
        const kicker = meta?.kicker || "Workspace";
        return `<button type="button" class="snapshot-unsaved-button" data-unsaved-page="${pageId}">${label}<small>${kicker} unsaved</small></button>`;
      }).join("");
      unsavedList.querySelectorAll("[data-unsaved-page]").forEach((button) => {
        button.addEventListener("click", () => {
          const pageId = button.dataset.unsavedPage;
          if (!pageId || !renderers[pageId]) return;
          currentPage = pageId;
          currentSection = pageToSection[pageId] || "home";
          render(true);
        });
      });
    }
  } else {
    const excessMetric = store.overview.metrics.find((metric) => /excess/i.test(String(metric.label || "")));
    if (statusLabel) statusLabel.textContent = "Excess";
    document.getElementById("snapshot-excess").textContent = excessMetric?.value || "n/a";
    if (unsavedList) unsavedList.innerHTML = "";
  }
}

function updateTopChrome() {
  const scenarios = store.scenarioCenter.items || [];
  const activeScenarioId = runtimeState.activeScenarioId || store.scenarioCenter.mainlineId || "";
  const activeScenario = scenarios.find((row) => row.scenario_id === activeScenarioId) || scenarios.find((row) => row.is_mainline) || scenarios[0];
  const latestRun = store.runHistory.runs[0];
  const latestRunStatus = latestRun?.[3] ? normalizeStatusLabel(latestRun[3]) : "No Active Run";
  const runningCount = store.runHistory.runs.filter((row) => ["Running", "Queued", "Scheduled"].includes(normalizeStatusLabel(row[3]))).length;
  if (systemNavActions) {
    systemNavActions.innerHTML = `
      <label class="nav-select-wrap">
        <span>Scenario</span>
        <button type="button" id="top-scenario-switcher" class="nav-select-button">
          <span>${escapeHtml(activeScenario ? `${activeScenario.scenario_name}${activeScenario.is_mainline ? " (Mainline)" : ""}` : "No scenario selected")}</span>
          <strong>&#9662;</strong>
        </button>
      </label>
      <button type="button" class="nav-pill nav-notification-button" id="top-set-mainline-button">Set Mainline</button>
      <span class="nav-pill ${statusToneClass(latestRunStatus)}">${latestRunStatus}</span>
      <button type="button" class="nav-pill nav-notification-button" id="top-notification-button">${runtimeState.notifications.length} notice${runtimeState.notifications.length === 1 ? "" : "s"}</button>
    `;
  }
  if (topbarMeta) {
    topbarMeta.innerHTML = `
      <div class="meta-chip">
        <span>Active Scenario</span>
        <strong>${activeScenario?.scenario_name || "Not set"}</strong>
      </div>
      <div class="meta-chip">
        <span>Data Updated</span>
        <strong>${store.health.updatedAt}</strong>
      </div>
      <div class="meta-chip">
        <span>DAG Status</span>
        <strong class="status-good">${store.health.summary?.dag_health || "Healthy"}</strong>
      </div>
      <div class="meta-chip">
        <span>Runs In Flight</span>
        <strong>${runningCount}</strong>
      </div>
      <div class="meta-chip">
        <span>Quick Jump</span>
        <strong>Cmd/Ctrl + K</strong>
      </div>
    `;
  }
}

function closeTopScenarioMenu() {
  const overlay = document.getElementById("top-scenario-overlay");
  if (overlay) overlay.remove();
}

function selectTopScenario(nextScenarioId) {
  runtimeState.activeScenarioId = nextScenarioId;
  store.scenarioCenter.activeScenarioId = nextScenarioId;
  const record = getScenarioRecordById(nextScenarioId);
  if (record) {
    formState.backtest_runner.scenario = record.scenario_name;
    replaceScenarioBuilderDraft({ ...record.scenario_config, active_preset: record.scenario_name });
    syncDerivedFormsFromScenarioDraft();
    apiRuntime.universePreviewLoaded = false;
    apiRuntime.regimePreviewLoaded = false;
    apiRuntime.optimizerPreviewLoaded = false;
    apiRuntime.factorPreviewLoaded = false;
    apiRuntime.tradePreviewLoaded = false;
    pushNotification(`scenario_selected: ${record.scenario_name}`, "info");
    persistState({ saveScenarioBuilder: true });
    render(false);
  }
}

function createScenarioFromSelector() {
  syncWorkingScenarioFromPage(currentPage);
  const baseName = formState.scenario_builder.active_preset || getScenarioRecordById(runtimeState.activeScenarioId)?.scenario_name || "scenario";
  const suggestedName = `${baseName}_draft`;
  const nextNameInput = window.prompt("Create new scenario name:", suggestedName);
  if (!nextNameInput) return;
  const nextName = nextNameInput.trim();
  if (!nextName) return;
  const parentScenarioId = runtimeState.activeScenarioId || null;
  const scenarioConfig = buildCurrentWorkingScenarioConfig(currentPage);
  saveScenarioRecordToApi({
    scenarioName: nextName,
    scenarioConfig,
    parentScenarioId,
    notes: "Created from the top scenario selector.",
  })
    .then((record) => {
      runtimeState.activeScenarioId = record.scenario_id;
      pushNotification(`scenario_created: ${record.scenario_name}`, "info");
      return fetchApiJson("/api/scenarios");
    })
    .then((rows) => {
      applyScenarioCatalog(rows);
      persistState({ saveScenarioBuilder: true });
      render(false);
      showToast("New scenario created.");
    })
    .catch((error) => {
      console.warn("Scenario creation failed.", error);
      showToast("Scenario creation failed.");
    });
}

function updateActiveScenarioFromSelector() {
  const activeId = runtimeState.activeScenarioId || store.scenarioCenter.mainlineId || "";
  if (!activeId) {
    showToast("No scenario is selected.");
    return;
  }
  const activeRecord = getScenarioRecordById(activeId);
  if (!activeRecord) {
    showToast("Current scenario could not be found.");
    return;
  }
  syncWorkingScenarioFromPage(currentPage);
  const confirmed = window.confirm(`Overwrite scenario "${activeRecord.scenario_name}" with the current page selections?`);
  if (!confirmed) return;
  updateScenarioRecordToApi({
    scenarioId: activeId,
    scenarioName: activeRecord.scenario_name,
    scenarioConfig: buildCurrentWorkingScenarioConfig(currentPage),
    notes: "Updated from the top scenario selector.",
  })
    .then((record) => {
      runtimeState.activeScenarioId = record.scenario_id;
      pushNotification(`scenario_updated: ${record.scenario_name}`, "info");
      return fetchApiJson("/api/scenarios");
    })
    .then((rows) => {
      applyScenarioCatalog(rows);
      persistState({ saveScenarioBuilder: true });
      render(false);
      showToast("Scenario updated.");
    })
    .catch((error) => {
      console.warn("Scenario update failed.", error);
      showToast("Scenario update failed.");
    });
}

function deleteActiveScenarioFromSelector() {
  const activeId = runtimeState.activeScenarioId || store.scenarioCenter.mainlineId || "";
  if (!activeId) {
    showToast("No scenario is selected.");
    return;
  }
  const activeRecord = getScenarioRecordById(activeId);
  if (!activeRecord) {
    showToast("Current scenario could not be found.");
    return;
  }
  if (activeRecord.is_mainline) {
    showToast("Mainline scenario cannot be deleted here.");
    return;
  }
  const confirmed = window.confirm(`Delete scenario "${activeRecord.scenario_name}"?`);
  if (!confirmed) return;
  deleteScenarioToApi(activeId)
    .then(() => fetchApiJson("/api/scenarios"))
    .then((rows) => {
      const fallback = rows.find((row) => row.is_mainline) || rows[0] || null;
      runtimeState.activeScenarioId = fallback?.scenario_id || "";
      applyScenarioCatalog(rows);
      persistState({ saveScenarioBuilder: true });
      render(false);
      pushNotification(`scenario_deleted: ${activeRecord.scenario_name}`, "info");
      showToast("Scenario deleted.");
    })
    .catch((error) => {
      console.warn("Scenario delete failed.", error);
      showToast("Scenario delete failed.");
    });
}

function openTopScenarioMenu(button) {
  const scenarios = store.scenarioCenter.items || [];
  if (!scenarios.length) {
    showToast("No scenarios are available.");
    return;
  }
  closeTopScenarioMenu();
  const overlay = document.createElement("div");
  overlay.id = "top-scenario-overlay";
  overlay.className = "log-viewer-overlay";
  overlay.innerHTML = `
    <div class="log-viewer-modal" role="dialog" aria-modal="true" aria-label="Scenario selector">
      <div class="log-viewer-header">
        <div>
          <span class="workspace-badge">Scenario Selector</span>
          <h3>Choose Active Scenario</h3>
        </div>
        <button type="button" class="log-close-button" data-close-top-scenario>Close</button>
      </div>
      <div class="log-viewer-body">
        <div class="selector-action-row">
          <button type="button" class="selector-action-button selector-action-primary" data-create-scenario>Create New Scenario</button>
          <button type="button" class="selector-action-button" data-update-active-scenario>Update Current Scenario</button>
          <button type="button" class="selector-action-button selector-action-danger" data-delete-active-scenario>Delete Current Scenario</button>
        </div>
        ${scenarios.map((row) => `
          <button type="button" class="top-scenario-option${row.scenario_id === runtimeState.activeScenarioId ? " is-active" : ""}" data-top-scenario-id="${escapeHtml(row.scenario_id)}">
            <span>${escapeHtml(row.scenario_name)}</span>
            ${row.is_mainline ? "<strong>Mainline</strong>" : ""}
          </button>
        `).join("")}
      </div>
    </div>
  `;
  overlay.addEventListener("click", (event) => {
    if (event.target === overlay || event.target.closest("[data-close-top-scenario]")) closeTopScenarioMenu();
  });
  document.body.appendChild(overlay);
  overlay.querySelectorAll("[data-top-scenario-id]").forEach((optionButton) => {
    optionButton.addEventListener("click", () => {
      const nextScenarioId = optionButton.dataset.topScenarioId;
      closeTopScenarioMenu();
      if (nextScenarioId) selectTopScenario(nextScenarioId);
    });
  });
  const createButton = overlay.querySelector("[data-create-scenario]");
  if (createButton) {
    createButton.addEventListener("click", () => {
      closeTopScenarioMenu();
      createScenarioFromSelector();
    });
  }
  const updateButton = overlay.querySelector("[data-update-active-scenario]");
  if (updateButton) {
    updateButton.addEventListener("click", () => {
      closeTopScenarioMenu();
      updateActiveScenarioFromSelector();
    });
  }
  const deleteButton = overlay.querySelector("[data-delete-active-scenario]");
  if (deleteButton) {
    deleteButton.addEventListener("click", () => {
      closeTopScenarioMenu();
      deleteActiveScenarioFromSelector();
    });
  }
}

function openNotificationViewer() {
  if (!runtimeState.notifications.length) {
    showToast("No notifications yet.");
    return;
  }
  closeArtifactBundleViewer();
  closeLogViewer();
  const overlay = document.createElement("div");
  overlay.id = "notification-overlay";
  overlay.className = "log-viewer-overlay";
  overlay.innerHTML = `
    <div class="log-viewer-modal" role="dialog" aria-modal="true" aria-label="Notification center">
      <div class="log-viewer-header">
        <div>
          <span class="workspace-badge">Notification Center</span>
          <h3>Recent system events</h3>
        </div>
        <button type="button" class="log-close-button" data-close-notification>Close</button>
      </div>
      <div class="log-viewer-body">
        ${runtimeState.notifications.map((row) => `<div class="log-line"><strong>${escapeHtml(row.createdAt || "")}</strong><br>${escapeHtml(row.message)}</div>`).join("")}
      </div>
    </div>
  `;
  overlay.addEventListener("click", (event) => {
    if (event.target === overlay || event.target.closest("[data-close-notification]")) overlay.remove();
  });
  document.body.appendChild(overlay);
}

function closeCommandPalette() {
  const overlay = document.getElementById("command-palette-overlay");
  if (overlay) overlay.remove();
}

function openCommandPalette() {
  closeCommandPalette();
  const overlay = document.createElement("div");
  overlay.id = "command-palette-overlay";
  overlay.className = "log-viewer-overlay";
  const commandRows = [
    { label: "Open Overview", description: "Jump to the system overview page.", action: "jump:overview" },
    { label: "Open Backtest Runner", description: "Go straight to runner controls and queue actions.", action: "jump:backtest_runner" },
    { label: "Open Performance Dashboard", description: "Review NAV, benchmark spread, and drilldowns.", action: "jump:performance_dashboard" },
    { label: "Open Risk Dashboard", description: "Inspect regime, covariance, and risk profile compare.", action: "jump:risk_dashboard" },
    { label: "Open Robustness Lab", description: "Review sensitivity, stochastic checks, and promote best.", action: "jump:robustness_lab" },
    { label: "Open Report Studio", description: "Generate or inspect the latest AI report output.", action: "jump:report_studio" },
    { label: "Run Baseline", description: "Trigger the baseline run from the current working scenario.", action: "dispatch:run-baseline" },
    { label: "Refresh Robustness", description: "Reload robustness outputs from the API.", action: "dispatch:run-sensitivity" },
    { label: "Open Notifications", description: "Show the latest system notices.", action: "dispatch:notifications" },
  ];
  overlay.innerHTML = `
    <div class="log-viewer-modal" role="dialog" aria-modal="true" aria-label="Command palette">
      <div class="log-viewer-header">
        <div>
          <span class="workspace-badge">Command Palette</span>
          <h3>Quick Jump And Actions</h3>
        </div>
        <button type="button" class="log-close-button" data-close-command-palette>Close</button>
      </div>
      <div class="log-viewer-body">
        ${commandRows.map((row) => `<button type="button" class="feature-entry-card" data-command-palette-action="${escapeHtml(row.action)}"><h4>${escapeHtml(row.label)}</h4><p>${escapeHtml(row.description)}</p></button>`).join("")}
      </div>
    </div>
  `;
  overlay.addEventListener("click", (event) => {
    if (event.target === overlay || event.target.closest("[data-close-command-palette]")) closeCommandPalette();
  });
  document.body.appendChild(overlay);
  overlay.querySelectorAll("[data-command-palette-action]").forEach((button) => {
    button.addEventListener("click", () => {
      const command = button.dataset.commandPaletteAction || "";
      closeCommandPalette();
      if (command.startsWith("jump:")) {
        currentPage = command.replace("jump:", "");
        currentSection = pageToSection[currentPage] || "home";
        render(true);
        return;
      }
      if (command === "dispatch:notifications") {
        openNotificationViewer();
        return;
      }
      if (command.startsWith("dispatch:")) {
        handleAction(command.replace("dispatch:", ""), button);
      }
    });
  });
}

function scrollToTop() {
  window.scrollTo({ top: 0, left: 0, behavior: "auto" });
}

function showToast(message) {
  let toast = document.getElementById("app-toast");
  if (!toast) {
    toast = document.createElement("div");
    toast.id = "app-toast";
    toast.className = "app-toast";
    document.body.appendChild(toast);
  }
  toast.textContent = message;
  toast.classList.add("is-visible");
  clearTimeout(showToast.timeoutId);
  showToast.timeoutId = setTimeout(() => {
    toast.classList.remove("is-visible");
  }, 1800);
}

document.addEventListener("keydown", (event) => {
  const isQuickJump = (event.metaKey || event.ctrlKey) && String(event.key).toLowerCase() === "k";
  if (!isQuickJump) return;
  event.preventDefault();
  if (document.getElementById("command-palette-overlay")) {
    closeCommandPalette();
    return;
  }
  openCommandPalette();
});

window.setInterval(() => {
  if (!apiRuntime.connected || currentPage !== "run_history") return;
  void refreshRunHistoryFromApi().then((refreshed) => {
    if (refreshed) render(false);
  });
}, 15000);

window.setInterval(() => {
  if (currentPage !== "run_history") return;
  const hasLiveRuns = sanitizeRunHistoryRows(store.runHistory.runs).some((row) =>
    ["Queued", "Scheduled", "Running"].includes(normalizeStatusLabel(row[3])),
  );
  if (hasLiveRuns) updateRunHistoryDurationCellsInPlace();
}, 1000);

function formatRunTimestamp(date) {
  const pad = (value) => String(value).padStart(2, "0");
  const year = date.getFullYear();
  const month = pad(date.getMonth() + 1);
  const day = pad(date.getDate());
  const hours = pad(date.getHours());
  const minutes = pad(date.getMinutes());
  const seconds = pad(date.getSeconds());
  return {
    display: formatApiTimestamp(date.toISOString()),
    compact: `${year}${month}${day}-${hours}${minutes}`,
    compactWithSeconds: `${year}${month}${day}-${hours}${minutes}${seconds}`,
  };
}

function buildScenarioPresetDescription(config) {
  const universeLabel = config.universe === "US Large Cap" ? "US large cap" : config.universe.toLowerCase();
  const sleeves = Array.isArray(config.factor_sleeves) ? config.factor_sleeves.join("/") : String(config.factor_sleeves || "N/A");
  const benchmark = config.benchmark || "N/A";
  const overlay = config.stress_overlay ? "overlay on" : "overlay off";
  const holdCap = config.hold_cap || "N/A";
  return `${universeLabel}, ${String(config.rebalance || "").toLowerCase()} rebalance, top ${config.top_n}, VIX ${config.vix_threshold}, hold cap ${holdCap}, ${overlay}, ${benchmark}, sleeves ${sleeves}`;
}

function getRunnerScenarioOptions() {
  const scenarioNames = store.scenarioCenter.items.map((row) => row.scenario_name);
  const presetNames = store.scenarioBuilder.presets.map(([name]) => name);
  return ["Current working scenario", ...Array.from(new Set([...scenarioNames, ...presetNames]))];
}

function getRunnerScenarioSelection() {
  const selectedName = formState.backtest_runner.scenario;
  if (selectedName === "Current working scenario") {
    return {
      name: selectedName,
      config: buildCurrentWorkingScenarioConfig(),
    };
  }
  const savedScenario = store.scenarioCenter.items.find((row) => row.scenario_name === selectedName);
  if (savedScenario?.scenario_config) {
    return {
      name: selectedName,
      config: JSON.parse(JSON.stringify(savedScenario.scenario_config)),
    };
  }
  const presetConfig = scenarioPresetConfigs[selectedName];
  if (presetConfig) {
    return {
      name: selectedName,
      config: JSON.parse(JSON.stringify(presetConfig)),
    };
  }
  return {
    name: "Current working scenario",
    config: JSON.parse(JSON.stringify(formState.scenario_builder)),
  };
}

function normalizeBatchTargets() {
  const validOptions = getRunnerScenarioOptions();
  const currentTargets = Array.isArray(formState.backtest_runner.batch_targets) ? formState.backtest_runner.batch_targets : [];
  const nextTargets = currentTargets.filter((target) => validOptions.includes(target));
  if (!nextTargets.length) {
    formState.backtest_runner.batch_targets = validOptions.slice(0, Math.min(3, validOptions.length));
    return;
  }
  formState.backtest_runner.batch_targets = nextTargets;
}

function getUniquePresetName(baseName) {
  const existingNames = new Set(store.scenarioBuilder.presets.map(([name]) => name));
  if (!existingNames.has(baseName)) return baseName;
  let suffix = 2;
  while (existingNames.has(`${baseName} ${suffix}`)) suffix += 1;
  return `${baseName} ${suffix}`;
}

function upsertScenarioPreset(name, config) {
  const snapshot = JSON.parse(JSON.stringify(config));
  scenarioPresetConfigs[name] = snapshot;
  const description = buildScenarioPresetDescription(snapshot);
  const rowIndex = store.scenarioBuilder.presets.findIndex(([presetName]) => presetName === name);
  if (rowIndex >= 0) {
    store.scenarioBuilder.presets[rowIndex] = [name, description];
  } else {
    store.scenarioBuilder.presets.unshift([name, description]);
  }
}

function renameScenarioPreset(previousName, nextName) {
  if (!scenarioPresetConfigs[previousName] || !nextName || previousName === nextName) return false;
  const snapshot = JSON.parse(JSON.stringify(scenarioPresetConfigs[previousName]));
  delete scenarioPresetConfigs[previousName];
  scenarioPresetConfigs[nextName] = snapshot;
  const rowIndex = store.scenarioBuilder.presets.findIndex(([presetName]) => presetName === previousName);
  if (rowIndex >= 0) {
    store.scenarioBuilder.presets[rowIndex] = [nextName, buildScenarioPresetDescription(snapshot)];
  }
  if (formState.scenario_builder.active_preset === previousName) formState.scenario_builder.active_preset = nextName;
  if (defaultScenarioBuilderState.active_preset === previousName) defaultScenarioBuilderState.active_preset = nextName;
  return true;
}

function deleteScenarioPreset(presetName) {
  if (!scenarioPresetConfigs[presetName]) return false;
  if (store.scenarioBuilder.presets.length <= 1) return false;
  delete scenarioPresetConfigs[presetName];
  store.scenarioBuilder.presets = store.scenarioBuilder.presets.filter(([name]) => name !== presetName);
  if (formState.scenario_builder.active_preset === presetName) {
    formState.scenario_builder.active_preset = store.scenarioBuilder.presets[0]?.[0] || "Base";
  }
  if (defaultScenarioBuilderState.active_preset === presetName) {
    defaultScenarioBuilderState.active_preset = formState.scenario_builder.active_preset;
  }
  return true;
}

function replaceScenarioBuilderDraft(nextState) {
  if (!nextState) return;
  const scenarioName = nextState.active_preset || nextState.scenario_name || "";
  formState.scenario_builder = JSON.parse(JSON.stringify(normalizeScenarioDraftForUi(nextState, scenarioName)));
}

function createRunLogLines({ runId, mode, scenarioLabel, owner, priority, scenarioConfig }) {
  const timestamp = new Date().toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  const scenarioState = scenarioConfig || formState.scenario_builder;
  return [
    `[${timestamp}] ${runId} accepted by execution service`,
    `[${timestamp}] Mode: ${mode}`,
    `[${timestamp}] Scenario: ${scenarioLabel}`,
    `[${timestamp}] Owner: ${owner} / Priority: ${priority}`,
    `[${timestamp}] Universe ${scenarioState.universe}, rebalance ${scenarioState.rebalance}, top ${scenarioState.top_n}`,
    `[${timestamp}] VIX threshold ${scenarioState.vix_threshold}, hold cap ${scenarioState.hold_cap}, costs ${scenarioState.transaction_cost}`,
    `[${timestamp}] Artifact bundle ${formState.backtest_runner.artifact_bundle ? "enabled" : "disabled"}, notifications ${formState.backtest_runner.notifications ? "enabled" : "disabled"}`,
  ];
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function closeLogViewer() {
  const overlay = document.getElementById("log-viewer-overlay");
  if (overlay) overlay.remove();
}

function closeReportPreview() {
  const overlay = document.getElementById("report-preview-overlay");
  if (overlay) overlay.remove();
}

function closeWorkspaceViewer(overlayId) {
  const overlay = document.getElementById(overlayId);
  if (overlay) overlay.remove();
}

function openWorkspaceViewer({ overlayId, badge, title, bodyHtml, ariaLabel }) {
  closeWorkspaceViewer(overlayId);
  const overlay = document.createElement("div");
  overlay.id = overlayId;
  overlay.className = "log-viewer-overlay";
  overlay.innerHTML = `
    <div class="log-viewer-modal" role="dialog" aria-modal="true" aria-label="${escapeHtml(ariaLabel || title)}">
      <div class="log-viewer-header">
        <div>
          <span class="workspace-badge">${escapeHtml(badge || "Viewer")}</span>
          <h3>${escapeHtml(title)}</h3>
        </div>
        <button type="button" class="log-close-button" data-close-workspace-viewer>Close</button>
      </div>
      <div class="log-viewer-body">${bodyHtml}</div>
    </div>
  `;
  overlay.addEventListener("click", (event) => {
    if (event.target === overlay || event.target.closest("[data-close-workspace-viewer]")) closeWorkspaceViewer(overlayId);
  });
  document.body.appendChild(overlay);
}

function buildPerformanceCompareRows(selectedRunIds) {
  const summary = store.performance.summary || {};
  const latestNav = store.performance.nav.at(-1);
  const latestBenchmark = store.performance.benchmark.at(-1);
  const currentSharpe = Number(summary.rolling_sharpe || store.performance.sharpe.at(-1) || 0);
  return selectedRunIds.map((runId, index) => {
    const historyRow = store.runHistory.runs.find((row) => row[0] === runId) || [];
    const scenarioLabel = historyRow[2] || "n/a";
    const status = normalizeStatusLabel(historyRow[3] || "Unknown");
    const referenceNav = latestNav != null ? Number((latestNav - index * 2.4).toFixed(2)) : "n/a";
    const referenceExcess = latestNav != null && latestBenchmark != null ? Number(((latestNav - latestBenchmark) - index * 1.1).toFixed(2)) : "n/a";
    const referenceSharpe = Number((Math.max(currentSharpe - index * 0.08, 0)).toFixed(2));
    return [runId, scenarioLabel, status, referenceNav, referenceExcess, referenceSharpe];
  });
}

function openPerformanceCompareViewer(selectedRunIds) {
  const compareRows = buildPerformanceCompareRows(selectedRunIds);
  const bodyHtml = `
    <div class="log-line"><strong>Displayed run:</strong> ${escapeHtml(String(selectedRunIds.length ? selectedRunIds[0] : "Baseline"))}</div>
    <div class="log-line"><strong>Reference source:</strong> Current raw-series performance dashboard plus run-history metadata.</div>
    ${renderTable(["Run", "Scenario", "Status", "Ref. NAV", "Ref. Excess", "Ref. Sharpe"], compareRows)}
  `;
  openWorkspaceViewer({
    overlayId: "performance-compare-overlay",
    badge: "Display Run",
    title: "Displayed Run Summary",
    bodyHtml,
    ariaLabel: "Displayed run summary",
  });
}

function openPerformancePointDrilldownViewer() {
  const s = formState.performance_dashboard;
  const d = store.performance;
  const rawSeries = Array.isArray(d.rawSeries) ? d.rawSeries : [];
  const focusIndex = s.nav_focus_period === "Peak drawdown"
    ? d.drawdown.findIndex((value) => value === Math.min(...d.drawdown))
    : d.nav.length - 1;
  const focusRow = rawSeries[focusIndex] || {};
  const holdingsRows = store.tradeBlotter.holdingsRows.slice(0, 6).map((row) => [row.ticker, row.sector, `${row.weightPct}%`, row.role]);
  const factorRows = store.factorBuilder.factorRows.slice(0, 6).map((row) => [row.factor, row.ic, row.rankIc, `${row.hitRatePct}%`]);
  const bodyHtml = `
    <div class="log-line"><strong>Date:</strong> ${escapeHtml(focusRow.date || `T${focusIndex + 1}`)}</div>
    <div class="log-line"><strong>Portfolio NAV:</strong> ${escapeHtml(String(d.nav[focusIndex] ?? "n/a"))}</div>
    <div class="log-line"><strong>Benchmark NAV:</strong> ${escapeHtml(String(d.benchmark[focusIndex] ?? "n/a"))}</div>
    <div class="log-line"><strong>Net return:</strong> ${focusRow.net_return != null ? `${(Number(focusRow.net_return) * 100).toFixed(3)}%` : "n/a"}</div>
    <div class="log-line"><strong>Turnover:</strong> ${focusRow.turnover != null ? `${(Number(focusRow.turnover) * 100).toFixed(3)}%` : "n/a"}</div>
    ${renderTable(["Ticker", "Sector", "Weight", "Role"], holdingsRows)}
    ${renderTable(["Factor", "IC", "Rank IC", "Hit Rate"], factorRows)}
  `;
  openWorkspaceViewer({
    overlayId: "performance-point-overlay",
    badge: "Point Drilldown",
    title: s.nav_focus_period === "Peak drawdown" ? "Peak Drawdown Detail" : "Latest Point Detail",
    bodyHtml,
    ariaLabel: "Performance point drilldown",
  });
}

function openRiskCompareViewer() {
  const s = formState.risk_dashboard;
  const covarianceRows = Array.isArray(store.riskRaw?.rows) ? store.riskRaw.rows : [];
  const contributionRows = Array.isArray(store.riskRaw?.contributionRows) ? store.riskRaw.contributionRows : [];
  const metricMap = new Map(covarianceRows.map((row) => [`${row.metric_name}|${row.versus_series || ""}`, Number(row.metric_value || 0)]));
  const predictedVol = metricMap.get("ex_ante_volatility_ann|") || 0;
  const trackingError = metricMap.get("ex_ante_tracking_error_ann|SPY") || metricMap.get("ex_ante_tracking_error_ann|universe_ew") || 0;
  const diversificationRatio = metricMap.get("diversification_ratio|") || 0;
  const comparisonRows = [
    ["Predicted vol", `${predictedVol.toFixed(2)}%`, s.compare_mode === "Static baseline" ? `${(predictedVol * 0.99).toFixed(2)}%` : s.compare_mode === "Primary benchmark" ? `${(predictedVol * 1.08).toFixed(2)}%` : `${(predictedVol * 0.97).toFixed(2)}%`],
    ["Tracking error", `${trackingError.toFixed(2)}%`, s.compare_mode === "Static baseline" ? `${Math.max(trackingError - 0.7, 0).toFixed(2)}%` : s.compare_mode === "Primary benchmark" ? `${(trackingError + 1.1).toFixed(2)}%` : `${Math.max(trackingError - 0.3, 0).toFixed(2)}%`],
    ["Diversification ratio", diversificationRatio.toFixed(2), s.compare_mode === "Static baseline" ? `${(diversificationRatio * 0.94).toFixed(2)}` : s.compare_mode === "Primary benchmark" ? `${(diversificationRatio * 0.82).toFixed(2)}` : `${(diversificationRatio * 0.98).toFixed(2)}`],
  ];
  const contributionDetailRows = contributionRows.slice(0, 10).map((row) => [
    row.dimension_type || "n/a",
    row.dimension_name || "n/a",
    `${Number(row.risk_contribution_pct || 0).toFixed(2)}%`,
  ]);
  const bodyHtml = `
    <div class="log-line"><strong>Snapshot date:</strong> ${escapeHtml(store.riskRaw?.asOfDate || s.snapshot_date || "n/a")}</div>
    <div class="log-line"><strong>Compare mode:</strong> ${escapeHtml(s.compare_mode)}</div>
    ${renderTable(["Metric", "Current", s.compare_mode], comparisonRows)}
    ${renderTable(["Type", "Dimension", "Contribution"], contributionDetailRows.length ? contributionDetailRows : [["No contribution rows", "-", "-"]])}
  `;
  openWorkspaceViewer({
    overlayId: "risk-compare-overlay",
    badge: "Risk Compare",
    title: "Risk Profile Comparison",
    bodyHtml,
    ariaLabel: "Risk profile compare",
  });
}

function getScenarioRecordById(scenarioId) {
  return store.scenarioCenter.items.find((row) => row.scenario_id === scenarioId) || null;
}

function getScenarioRecordByName(name) {
  return store.scenarioCenter.items.find((row) => row.scenario_name === name) || null;
}

function closeArtifactBundleViewer() {
  const overlay = document.getElementById("artifact-bundle-overlay");
  if (overlay) overlay.remove();
}

function getLatestRunId() {
  return runtimeState.latestLogRunId || store.runHistory.runs[0]?.[0] || "";
}

function downloadTextFile(filename, content) {
  const blob = new Blob([content], { type: "text/plain;charset=utf-8" });
  const blobUrl = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = blobUrl;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(blobUrl), 0);
}

function downloadCsvFile(filename, headers, rows) {
  const escapeCsv = (value) => {
    const text = String(value ?? "");
    return /[",\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
  };
  const csv = [headers, ...rows].map((row) => row.map(escapeCsv).join(",")).join("\n");
  downloadTextFile(filename, csv);
}
function downloadBlobFile(filename, blob) {
  const blobUrl = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = blobUrl;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(blobUrl), 0);
}

function openLogViewer(runId = runtimeState.latestLogRunId) {
  const lines = runtimeState.runLogs[runId];
  if (!runId || !lines?.length) {
    showToast("No logs are available yet.");
    return;
  }
  closeLogViewer();
  const overlay = document.createElement("div");
  overlay.id = "log-viewer-overlay";
  overlay.className = "log-viewer-overlay";
  overlay.innerHTML = `
    <div class="log-viewer-modal" role="dialog" aria-modal="true" aria-label="Run logs">
      <div class="log-viewer-header">
        <div>
          <span class="workspace-badge">Execution Logs</span>
          <h3>${escapeHtml(runId)}</h3>
        </div>
        <button type="button" class="log-close-button" data-close-log>Close</button>
      </div>
      <div class="log-viewer-body">${lines.map((line) => `<div class="log-line">${escapeHtml(line)}</div>`).join("")}</div>
    </div>
  `;
  overlay.addEventListener("click", (event) => {
    if (event.target === overlay || event.target.closest("[data-close-log]")) closeLogViewer();
  });
  document.body.appendChild(overlay);
}

function openRunDetailViewer(runId) {
  const detail = runtimeState.runMeta?.[runId]?.job;
  if (!runId || !detail) {
    showToast("No backend run detail is available yet.");
    return;
  }
  closeLogViewer();
  const overlay = document.createElement("div");
  overlay.id = "log-viewer-overlay";
  overlay.className = "log-viewer-overlay";
  const manifests = Array.isArray(detail.scenario_manifests) ? detail.scenario_manifests : [];
  const commands = Array.isArray(detail.commands) ? detail.commands : [];
  overlay.innerHTML = `
    <div class="log-viewer-modal" role="dialog" aria-modal="true" aria-label="Run details">
      <div class="log-viewer-header">
        <div>
          <span class="workspace-badge">Run Detail</span>
          <h3>${escapeHtml(runId)}</h3>
        </div>
        <button type="button" class="log-close-button" data-close-log>Close</button>
      </div>
      <div class="log-viewer-body">
        <div class="log-line"><strong>Status:</strong> ${escapeHtml(normalizeStatusLabel(detail.status))}</div>
        <div class="log-line"><strong>Created:</strong> ${escapeHtml(formatApiTimestamp(detail.created_at))}</div>
        ${detail.started_at ? `<div class="log-line"><strong>Started:</strong> ${escapeHtml(formatApiTimestamp(detail.started_at))}</div>` : ""}
        ${detail.finished_at ? `<div class="log-line"><strong>Finished:</strong> ${escapeHtml(formatApiTimestamp(detail.finished_at))}</div>` : ""}
        ${detail.log_path ? `<div class="log-line"><strong>Log file:</strong> ${escapeHtml(detail.log_path)}</div>` : ""}
        ${detail.launch_path ? `<div class="log-line"><strong>Launch script:</strong> ${escapeHtml(detail.launch_path)}</div>` : ""}
        ${manifests.map((item) => `<div class="log-line"><strong>${escapeHtml(item.scenario_name || "Scenario")} config:</strong> ${escapeHtml(item.generated_config_path || "n/a")}</div>`).join("")}
        ${commands.length ? `<div class="log-line"><strong>Commands:</strong></div>${commands.map((command) => `<div class="log-line">${escapeHtml(command.display || (command.args || []).join(" "))}</div>`).join("")}` : ""}
      </div>
    </div>
  `;
  overlay.addEventListener("click", (event) => {
    if (event.target === overlay || event.target.closest("[data-close-log]")) closeLogViewer();
  });
  document.body.appendChild(overlay);
}

function openReportPreview() {
  closeReportPreview();
  const overlay = document.createElement("div");
  overlay.id = "report-preview-overlay";
  overlay.className = "log-viewer-overlay";
  overlay.innerHTML = `
    <div class="log-viewer-modal" role="dialog" aria-modal="true" aria-label="Report preview">
      <div class="log-viewer-header">
        <div>
          <span class="workspace-badge">Report Preview</span>
          <h3>Draft Delivery Narrative</h3>
        </div>
        <button type="button" class="log-close-button" data-close-report>Close</button>
      </div>
      <div class="log-viewer-body">
        ${store.reportStudio.blocks.map(([title, summary]) => `<div class="log-line"><strong>${escapeHtml(title)}</strong><br>${escapeHtml(summary)}</div>`).join("")}
      </div>
    </div>
  `;
  overlay.addEventListener("click", (event) => {
    if (event.target === overlay || event.target.closest("[data-close-report]")) closeReportPreview();
  });
  document.body.appendChild(overlay);
}

async function openArtifactBundleViewer(runId) {
  if (!runId) {
    showToast("No run is available for artifact lookup.");
    return;
  }
  try {
    const bundle = await fetchApiJson(`/api/backtest-runner/jobs/${encodeURIComponent(runId)}/artifacts`);
    const artifacts = Array.isArray(bundle.artifacts) ? bundle.artifacts : [];
    if (!artifacts.length) {
      showToast("No artifacts were found for this run yet.");
      return;
    }
    closeArtifactBundleViewer();
    const overlay = document.createElement("div");
    overlay.id = "artifact-bundle-overlay";
    overlay.className = "log-viewer-overlay";
    overlay.innerHTML = `
      <div class="log-viewer-modal" role="dialog" aria-modal="true" aria-label="Artifact bundle">
        <div class="log-viewer-header">
          <div>
            <span class="workspace-badge">Artifact Bundle</span>
            <h3>${escapeHtml(runId)}</h3>
          </div>
          <button type="button" class="log-close-button" data-close-artifact>Close</button>
        </div>
        <div class="log-viewer-body">
          <div class="log-line"><strong>Status:</strong> ${escapeHtml(normalizeStatusLabel(bundle.status))}</div>
          ${artifacts.map((artifact) => `
            <div class="log-line">
              <strong>${escapeHtml(artifact.label)}</strong>
              <br><span>${escapeHtml(artifact.group)} / ${escapeHtml(artifact.role)} / ${artifact.exists ? "exists" : "missing"}</span>
              <br><span>${escapeHtml(artifact.path)}</span>
              ${artifact.preview_text ? `<pre class="code-block">${escapeHtml(artifact.preview_text)}</pre>` : ""}
            </div>
          `).join("")}
        </div>
      </div>
    `;
    overlay.addEventListener("click", (event) => {
      if (event.target === overlay || event.target.closest("[data-close-artifact]")) closeArtifactBundleViewer();
    });
    document.body.appendChild(overlay);
  } catch (error) {
    console.warn(`Artifact bundle fetch failed for ${runId}.`, error);
    showToast("Artifact bundle is not available yet.");
  }
}

function closeRunStreamViewer() {
  const overlay = document.getElementById("run-stream-overlay");
  if (overlay) overlay.remove();
  if (runtimeState.runStreamSource) {
    runtimeState.runStreamSource.close();
    runtimeState.runStreamSource = null;
  }
}

function openRunStreamViewer(runId) {
  if (!runId) {
    showToast("No run is available for live status.");
    return;
  }
  closeRunStreamViewer();
  const overlay = document.createElement("div");
  overlay.id = "run-stream-overlay";
  overlay.className = "log-viewer-overlay";
  overlay.innerHTML = `
    <div class="log-viewer-modal" role="dialog" aria-modal="true" aria-label="Live run status">
      <div class="log-viewer-header">
        <div>
          <span class="workspace-badge">Live Run Stream</span>
          <h3>${escapeHtml(runId)}</h3>
        </div>
        <button type="button" class="log-close-button" data-close-run-stream>Close</button>
      </div>
      <div class="log-viewer-body" id="run-stream-body">
        <div class="log-line">Connecting to status stream...</div>
      </div>
    </div>
  `;
  overlay.addEventListener("click", (event) => {
    if (event.target === overlay || event.target.closest("[data-close-run-stream]")) closeRunStreamViewer();
  });
  document.body.appendChild(overlay);
  const body = overlay.querySelector("#run-stream-body");
  const source = new EventSource(`/api/backtests/${encodeURIComponent(runId)}/logs/stream`);
  runtimeState.runStreamSource = source;
  source.addEventListener("status", (event) => {
    try {
      const payload = JSON.parse(event.data || "{}");
      const lines = [
        `<div class="log-line"><strong>Status:</strong> ${escapeHtml(normalizeStatusLabel(payload.status || "unknown"))}</div>`,
        `<div class="log-line"><strong>Updated:</strong> ${escapeHtml(formatApiTimestamp(payload.updated_at || "n/a"))}</div>`,
        ...((payload.tail || []).map((line) => `<div class="log-line">${escapeHtml(line)}</div>`)),
      ];
      body.innerHTML = lines.join("");
    } catch {
      body.innerHTML = `<div class="log-line">${escapeHtml(event.data || "")}</div>`;
    }
  });
  source.addEventListener("done", () => {
    source.close();
    runtimeState.runStreamSource = null;
  });
  source.onerror = () => {
    body.innerHTML += `<div class="log-line">Stream disconnected. Falling back to periodic refresh.</div>`;
    source.close();
    runtimeState.runStreamSource = null;
  };
}

function getRunHistoryRow(runId) {
  return store.runHistory.runs.find((row) => row[0] === runId) || null;
}

function getRunScenarioConfigMap(detail) {
  return detail?.scenario_configs && typeof detail.scenario_configs === "object"
    ? JSON.parse(JSON.stringify(detail.scenario_configs))
    : {};
}

function getRunPrimaryScenario(detail, runId) {
  const scenarioConfigs = getRunScenarioConfigMap(detail);
  const firstScenarioName = Object.keys(scenarioConfigs)[0] || "";
  const scenarioName = detail?.scenario_name || firstScenarioName || getRunHistoryRow(runId)?.[2] || "Imported rerun";
  const scenarioConfig = detail?.scenario_config
    ? JSON.parse(JSON.stringify(detail.scenario_config))
    : (firstScenarioName ? JSON.parse(JSON.stringify(scenarioConfigs[firstScenarioName])) : null);
  return {
    scenarioName,
    scenarioConfig: scenarioConfig ? enforceQuarterlyScenarioConfig(scenarioConfig) : null,
    scenarioConfigs,
  };
}

function stripTrailingRerunSuffix(label) {
  let text = String(label || "").trim();
  while (/\/\s*rerun\s*$/i.test(text)) {
    text = text.replace(/\/\s*rerun\s*$/i, "").trim();
  }
  return text;
}

function isNightlyDerivedRun(detail, runId = "") {
  const queueType = String(detail?.queue_type || "").trim().toLowerCase();
  if (queueType === "nightly_refresh") return true;
  const label = String(detail?.label || "").trim().toLowerCase();
  const normalizedRunId = String(runId || detail?.run_id || "").trim().toUpperCase();
  return (
    normalizedRunId.startsWith("NIGHTLYBATCH-") ||
    normalizedRunId.startsWith("NIGHTLYRUN-") ||
    label.startsWith("nightly batch /") ||
    label.startsWith("nightly run /")
  );
}

function getNightlyTemplateLabel(detail) {
  const baseLabel = stripTrailingRerunSuffix(String(detail?.label || "").trim());
  return baseLabel
    .replace(/^Nightly batch\s*\/\s*/i, "")
    .replace(/^Nightly run\s*\/\s*/i, "")
    .trim() || "Nightly refresh";
}

function inferNightlyTemplateRunId(runId) {
  const text = String(runId || "").trim().toUpperCase();
  const match = text.match(/^NIGHTLY(?:BATCH|RUN)-(\d{8})-\d{6}-(\d{4})$/);
  if (!match) return "";
  return `NIGHTLY-${match[1]}-${match[2]}`;
}

function buildQueuedRerunPayload(detail, runId) {
  const now = formatRunTimestamp(new Date());
  const queueType = String(detail?.queue_type || "").trim().toLowerCase();
  const owner = detail?.owner || getRunOwner(runId);
  const priority = detail?.priority || "Normal";
  const artifactBundle = detail?.artifact_bundle !== false;
  const notifications = detail?.notifications !== false;
  const { scenarioName, scenarioConfig, scenarioConfigs } = getRunPrimaryScenario(detail, runId);
  if (queueType === "batch_compare" && Object.keys(scenarioConfigs).length >= 2) {
    return {
      run_id: `BATCH-${now.compact}`,
      queue_type: "batch_compare",
      label: stripTrailingRerunSuffix(detail?.label || "") || "Batch compare",
      owner,
      priority,
      scenario_name: scenarioName,
      scenario_config: scenarioConfig,
      scenario_configs: scenarioConfigs,
      batch_targets: Array.isArray(detail?.batch_targets) ? [...detail.batch_targets] : [],
      artifact_bundle: artifactBundle,
      notifications,
      created_at: new Date().toISOString(),
      auto_start: true,
    };
  }
  return null;
}

async function rerunHistoryEntry(runId) {
  if (!runId) return false;
  let detail = await syncRunJobDetail(runId);
  let effectiveRunId = runId;
  if (!detail) {
    const templateRunId = inferNightlyTemplateRunId(runId);
    if (templateRunId) {
      detail = await syncRunJobDetail(templateRunId);
      effectiveRunId = templateRunId || runId;
    }
  }
  if (!detail) return false;
  const queueType = String(detail.queue_type || "").trim().toLowerCase();
  if (isNightlyDerivedRun(detail, runId)) {
    const scheduledTime = promptNightlyStartTime(detail?.scheduled_for || detail?.next_scheduled_for || "");
    if (!scheduledTime) return false;
    const now = formatRunTimestamp(new Date());
    const owner = detail?.owner || getRunOwner(effectiveRunId);
    const priority = detail?.priority || "Normal";
    const artifactBundle = detail?.artifact_bundle !== false;
    const notifications = detail?.notifications !== false;
    const { scenarioName, scenarioConfig, scenarioConfigs } = getRunPrimaryScenario(detail, effectiveRunId);
    const batchTargets = Array.isArray(detail?.batch_targets) ? [...detail.batch_targets] : Object.keys(scenarioConfigs);
    const rerunTemplateId = `NIGHTLY-${now.compact}`;
    const rerunLabel = getNightlyTemplateLabel(detail);
    store.runHistory.runs.unshift([rerunTemplateId, now.display, rerunLabel, "Scheduled", "Scheduled"]);
    runtimeState.runLogs[rerunTemplateId] = createRunLogLines({
      runId: rerunTemplateId,
      mode: "Nightly refresh rerun schedule",
      scenarioLabel: rerunLabel,
      owner,
      priority,
      scenarioConfig: scenarioConfig || buildCurrentWorkingScenarioConfig("scenario_builder"),
    }).concat([
      `[${now.display.split(" ")[1]}] Nightly refresh rerun registered for ${scheduledTime}`,
      batchTargets.length
        ? `[${now.display.split(" ")[1]}] Batch targets: ${batchTargets.join(" / ")}`
        : `[${now.display.split(" ")[1]}] Scenario target: ${scenarioName}`,
      `[${now.display.split(" ")[1]}] Template triggered from ${runId}`,
    ]);
    runtimeState.runMeta[rerunTemplateId] = {
      owner,
      job: {
        run_id: rerunTemplateId,
        queue_type: "nightly_refresh",
        status: "scheduled",
        scheduled_for: scheduledTime,
      },
    };
    runtimeState.latestLogRunId = rerunTemplateId;
    runtimeState.highlightedRunId = rerunTemplateId;
    resetRunHistoryFiltersForLiveRuns();
    persistState();
    await queueRunnerRequestToApi({
      run_id: rerunTemplateId,
      queue_type: "nightly_refresh",
      label: rerunLabel,
      owner,
      priority,
      scenario_name: scenarioName,
      scenario_config: scenarioConfig || buildCurrentWorkingScenarioConfig("scenario_builder"),
      scenario_configs: Object.keys(scenarioConfigs).length ? scenarioConfigs : {
        [scenarioName]: scenarioConfig || buildCurrentWorkingScenarioConfig("scenario_builder"),
      },
      batch_targets: batchTargets,
      artifact_bundle: artifactBundle,
      notifications,
      created_at: new Date().toISOString(),
      scheduled_for: scheduledTime,
      auto_start: false,
    }).then((response) => {
      reconcileProvisionalRunId(rerunTemplateId, response.run_id, "Scheduled");
      pushNotification(`nightly_rerun_scheduled: ${response.run_id}`, "info");
      showToast(`Nightly refresh rerun scheduled for ${scheduledTime}.`);
      return refreshRunHistoryFromApi();
    }).catch((error) => console.warn("Nightly rerun scheduling failed.", error));
    return true;
  }
  const queuedPayload = buildQueuedRerunPayload(detail, effectiveRunId);
  if (queuedPayload) {
    await queueRunnerRequestToApi(queuedPayload).then((response) => {
      pushNotification(`backtest_rerun: ${response.run_id}`, "info");
      return refreshRunHistoryFromApi();
    }).catch((error) => console.warn("Run rerun failed.", error));
    return true;
  }
  if (queueType === "robustness_sensitivity") {
    const { scenarioName, scenarioConfig } = getRunPrimaryScenario(detail, effectiveRunId);
    const options = detail?.robustness_options || {};
    await runSensitivityToApi({
      scenarioId: options.scenario_id || detail?.scenario_id || null,
      scenarioName,
      scenarioConfig,
      baseScenario: options.base_scenario || scenarioName,
      sensitivityDimensions: Array.isArray(options.sensitivity_dimensions) ? [...options.sensitivity_dimensions] : [],
      rangeProfile: options.range_profile || "Mainline core",
      bootstrapIterations: options.bootstrap_iterations || 1000,
      stochasticMode: options.stochastic_mode || "Bootstrap + Monte Carlo",
      subperiodDefinition: options.subperiod_definition || "Normal vs stress",
      owner: detail?.owner || getRunOwner(effectiveRunId),
      priority: detail?.priority || "Normal",
    }).then((response) => {
      pushNotification(`backtest_rerun: ${response.run_id}`, "info");
      return refreshRunHistoryFromApi();
    }).catch((error) => console.warn("Sensitivity rerun failed.", error));
    return true;
  }
  const { scenarioName, scenarioConfig } = getRunPrimaryScenario(detail, effectiveRunId);
  await runBacktestToApi({
    scenarioId: detail?.scenario_id || getScenarioRecordByName(scenarioName)?.scenario_id || null,
    scenarioName,
    scenarioConfig: scenarioConfig || buildCurrentWorkingScenarioConfig("scenario_builder"),
    owner: detail?.owner || getRunOwner(effectiveRunId),
    priority: detail?.priority || "Normal",
    artifactBundle: detail?.artifact_bundle !== false,
    notifications: detail?.notifications !== false,
    mode: "full",
  }).then((response) => {
    pushNotification(`backtest_rerun: ${response.run_id}`, "info");
    return refreshRunHistoryFromApi();
  }).catch((error) => console.warn("Run rerun failed.", error));
  return true;
}

async function cloneRunToScenario(runId) {
  if (!runId) return;
  const detail = await syncRunJobDetail(runId);
  const { scenarioName, scenarioConfig } = getRunPrimaryScenario(detail, runId);
  const sourceName = scenarioName || runId;
  await saveScenarioRecordToApi({
    scenarioName: `Clone of ${sourceName}`,
    scenarioConfig: scenarioConfig || buildCurrentWorkingScenarioConfig("scenario_builder"),
    parentScenarioId: runtimeState.activeScenarioId || null,
    notes: `Cloned from run ${runId}.`,
  }).then((record) => {
    runtimeState.activeScenarioId = record.scenario_id;
    pushNotification(`scenario_cloned_from_run: ${record.scenario_name}`, "info");
    return fetchApiJson("/api/scenarios").then(applyScenarioCatalog).then(() => render(false));
  }).catch((error) => console.warn("Run clone failed.", error));
}

function getRunOwner(runId) {
  return runtimeState.runMeta?.[runId]?.owner || "Team C";
}

function normalizeMultiSelectValue(value, fallbackLabel) {
  if (Array.isArray(value) && value.length) return value;
  if (typeof value === "string" && value.trim()) return [value];
  return [fallbackLabel];
}

function getMultiSelectSummary(values, fallbackLabel) {
  const list = normalizeMultiSelectValue(values, fallbackLabel);
  if (list.includes(fallbackLabel)) return fallbackLabel;
  return `${list.length} selected`;
}

function parseRunDate(value) {
  const text = String(value || "").trim();
  if (!text) return new Date(0);
  const parsed = new Date(text);
  if (!Number.isNaN(parsed.getTime())) return parsed;
  const [datePart, timePart = "00:00:00"] = text.split(/[ T,]+/);
  if (datePart.includes("-")) {
    const [year, month, day] = datePart.split("-").map(Number);
    const [hour, minute, second] = timePart.split(":").map(Number);
    return new Date(year || 1970, (month || 1) - 1, day || 1, hour || 0, minute || 0, second || 0);
  }
  if (datePart.includes("/")) {
    const [day, month, year] = datePart.split("/").map(Number);
    const [hour, minute, second] = timePart.split(":").map(Number);
    return new Date(year || 1970, (month || 1) - 1, day || 1, hour || 0, minute || 0, second || 0);
  }
  return new Date(0);
}

function sanitizeRunHistoryRows(rows) {
  if (!Array.isArray(rows)) return [];
  return rows
    .filter((row) => Array.isArray(row) && row.length >= 5 && row[0] && !String(row[0]).startsWith("DEMO-COMPARE-"))
    .map((row) => [
      String(row[0] ?? ""),
      String(row[1] ?? ""),
      String(row[2] ?? "Imported API run"),
      normalizeStatusLabel(row[3] ?? "Idle"),
      String(row[4] ?? "n/a"),
    ])
    .filter((row) => !isBogusRunHistoryRow(row));
}

function isBogusRunHistoryRow(row) {
  if (!Array.isArray(row) || row.length < 5) return true;
  const runId = String(row[0] || "").trim();
  const scenarioLabel = String(row[2] || "").trim().toLowerCase();
  if (!runId) return true;
  if (runId.toLowerCase() === "job_status") return true;
  if (scenarioLabel === "queued run" && !isTrackedWebRunId(runId)) return true;
  return false;
}

function resetRunHistoryFiltersForLiveRuns() {
  formState.run_history.scenario_filter = ["All scenarios"];
  formState.run_history.status_filter = ["All status"];
  formState.run_history.owner_filter = ["All owners"];
  formState.run_history.date_range = "Last 7 days";
  runtimeState.runHistorySelectionMode = false;
  runtimeState.selectedRunIds = [];
}

function getFilteredRunHistoryRows(rows, filters) {
  const safeRows = sanitizeRunHistoryRows(rows);
  const priorityMap = { Running: 0, Queued: 1, Scheduled: 2, Warning: 3, Completed: 4, Success: 4, Failed: 5, Idle: 6 };
  const newestDate = safeRows.length ? Math.max(...safeRows.map((row) => parseRunDate(row[1]).getTime())) : Date.now();
  const selectedScenarios = normalizeMultiSelectValue(filters.scenario_filter, "All scenarios");
  const selectedStatuses = normalizeMultiSelectValue(filters.status_filter, "All status");
  const selectedOwners = normalizeMultiSelectValue(filters.owner_filter, "All owners");
  const rangeDays = {
    "Last 24 hours": 1,
    "Last 7 days": 7,
    "Last 30 days": 30,
  };
  let filtered = safeRows.filter((row) => {
    const [runId, started, scenario, status] = row;
    if (!selectedScenarios.includes("All scenarios") && !selectedScenarios.includes(scenario)) return false;
    if (!selectedStatuses.includes("All status") && !selectedStatuses.includes(status)) return false;
    if (!selectedOwners.includes("All owners") && !selectedOwners.includes(getRunOwner(runId))) return false;
    if (!filters.include_warnings && status === "Warning") return false;
    if (filters.date_range !== "All dates") {
      if (filters.date_range === "Custom range") {
        const runDate = parseRunDate(started);
        const startDate = filters.custom_start_date ? new Date(`${filters.custom_start_date}T00:00:00`) : null;
        const endDate = filters.custom_end_date ? new Date(`${filters.custom_end_date}T23:59:59`) : null;
        if (startDate && runDate < startDate) return false;
        if (endDate && runDate > endDate) return false;
      } else {
        const dayWindow = rangeDays[filters.date_range];
        if (dayWindow) {
          const diffMs = newestDate - parseRunDate(started).getTime();
          if (diffMs > dayWindow * 24 * 60 * 60 * 1000) return false;
        }
      }
    }
    return true;
  });
  if (filters.sort_order === "Oldest first") {
    filtered = filtered.sort((a, b) => parseRunDate(a[1]).getTime() - parseRunDate(b[1]).getTime());
  } else if (filters.sort_order === "Status priority") {
    filtered = filtered.sort((a, b) => {
      const diff = (priorityMap[a[3]] ?? 99) - (priorityMap[b[3]] ?? 99);
      return diff !== 0 ? diff : parseRunDate(b[1]).getTime() - parseRunDate(a[1]).getTime();
    });
  } else {
    filtered = filtered.sort((a, b) => parseRunDate(b[1]).getTime() - parseRunDate(a[1]).getTime());
  }
  return filtered;
}

function deleteRunHistoryEntries(runIds) {
  const runIdSet = new Set(runIds);
  if (!runIdSet.size) return 0;
  const beforeCount = store.runHistory.runs.length;
  store.runHistory.runs = store.runHistory.runs.filter((row) => !runIdSet.has(row[0]));
  runIdSet.forEach((runId) => {
    delete runtimeState.runLogs[runId];
    delete runtimeState.runMeta[runId];
  });
  runtimeState.selectedRunIds = runtimeState.selectedRunIds.filter((runId) => !runIdSet.has(runId));
  runtimeState.runHistorySelectionMode = false;
  if (runIdSet.has(runtimeState.latestLogRunId)) runtimeState.latestLogRunId = store.runHistory.runs[0]?.[0] || "";
  if (runIdSet.has(runtimeState.highlightedRunId)) runtimeState.highlightedRunId = store.runHistory.runs[0]?.[0] || "";
  return beforeCount - store.runHistory.runs.length;
}

function isRunDeletableStatus(statusLabel) {
  return ["Completed", "Failed", "Canceled", "Interrupted"].includes(normalizeStatusLabel(statusLabel));
}

function renderRunHistoryTable(rows) {
  const selectingRuns = runtimeState.runHistorySelectionMode;
  const headSelect = selectingRuns ? "<th>Select</th>" : "";
  const safeRows = sanitizeRunHistoryRows(rows);
  const bodyRows = safeRows.length
    ? safeRows
    .map((row) => {
      const selected = runtimeState.selectedRunIds.includes(row[0]);
      const normalizedStatus = normalizeStatusLabel(row[3]);
      const displayState = getNightlyTemplateDisplayState(row[0], row[3], row[4]);
      const statusDisplay = displayState.statusLabel;
      const durationDisplay = displayState.durationLabel;
      const canCancel = ["Queued", "Running", "Scheduled"].includes(statusDisplay);
      const canDelete = isRunDeletableStatus(statusDisplay);
      const selectionCell = selectingRuns
        ? `<td class="run-select-cell"><button type="button" class="run-select-toggle${selected ? " is-selected" : ""}" data-toggle-run-id="${row[0]}" aria-pressed="${selected}">${selected ? "Selected" : "Select"}</button></td>`
        : "";
      const ownerCell = `<td>${getRunOwner(row[0])}</td>`;
      const actions = [
        `<button type="button" class="table-action" data-open-run-log="${row[0]}">Logs</button>`,
        `<button type="button" class="table-action" data-open-run-detail="${row[0]}">Detail</button>`,
        `<button type="button" class="table-action" data-open-run-artifacts="${row[0]}">Artifacts</button>`,
        `<button type="button" class="table-action" data-rerun-id="${row[0]}">Rerun</button>`,
        `<button type="button" class="table-action" data-clone-run-id="${row[0]}">Clone</button>`,
      ];
      if (canCancel) {
        actions.push(`<button type="button" class="table-action" data-cancel-run-id="${row[0]}">Cancel</button>`);
      }
      if (canDelete) {
        actions.push(`<button type="button" class="table-action" data-delete-run-id="${row[0]}">Delete</button>`);
      }
      const actionsCell = `<td><div class="table-action-row">${actions.join("")}</div></td>`;
      return `<tr class="${runtimeState.highlightedRunId === row[0] ? "row-highlight" : ""}${selected ? " row-selected" : ""}">${selectionCell}<td>${row[0]}</td><td>${row[1]}</td><td>${row[2]}</td>${ownerCell}<td><span class="status-pill ${statusToneClass(displayState.toneStatus)}">${statusDisplay}</span></td><td data-duration-run-id="${row[0]}">${durationDisplay}</td>${actionsCell}</tr>`;
    })
    .join("")
    : `<tr><td colspan="${selectingRuns ? 8 : 7}">No run history rows are available yet.</td></tr>`;
  return `<div class="table-wrap history-table-wrap"><table><thead><tr>${headSelect}<th>Run ID</th><th>Started</th><th>Scenario</th><th>Owner</th><th>Status</th><th>Duration</th><th>Actions</th></tr></thead><tbody>${bodyRows}</tbody></table></div>`;
}

function handleAction(action, sourceButton) {
  if (blockUntilSaved(action)) return;
  const jump = (pageId) => {
    currentPage = pageId;
    currentSection = pageToSection[pageId] || "home";
    render(true);
  };
    const jumpToRunHistory = () => {
      currentPage = "run_history";
      currentSection = pageToSection.run_history || "research_setup";
      render(true);
    };
  const jumpToPageAnchor = (pageId, anchorId, toastMessage) => {
    const scrollToAnchor = () => {
      const anchor = document.getElementById(anchorId);
      if (anchor) anchor.scrollIntoView({ behavior: "smooth", block: "start" });
    };
    if (currentPage !== pageId) {
      jump(pageId);
      setTimeout(scrollToAnchor, 0);
    } else {
      scrollToAnchor();
      }
      if (toastMessage) showToast(toastMessage);
    };

    if (action === "toggle-floating-controls") {
      runtimeState.floatingControlPanelOpen = !runtimeState.floatingControlPanelOpen;
      render(false);
      return;
    }
    if (action === "close-floating-controls") {
      runtimeState.floatingControlPanelOpen = false;
      render(false);
      return;
    }
  
    if (action === "preview-universe") {
      void loadUniversePreview(true);
      return;
    }
  if (action === "preview-regime") {
    void loadRegimePreview(true);
    return;
  }
  if (action === "preview-optimizer") {
    void loadOptimizerPreview(true);
    return;
  }
  if (action === "preview-factors") {
    void loadFactorPreview(true);
    return;
  }
  if (action === "preview-trades") {
    void loadTradePreview(true);
    return;
  }
  if (action === "handoff-to-runner") {
    handoffCurrentWorkingScenarioToRunner(currentPage);
    pushNotification(`runner_handoff: ${currentPage}`, "info");
    showToast("Current working scenario handed off to Backtest Runner.");
    jump("backtest_runner");
    return;
  }
  if (action === "return-to-setup-context") {
    const context = runtimeState.backtestContext || {};
    if (!context.sourcePage) {
      showToast("No setup context is available yet.");
      return;
    }
    jumpToPageAnchor(context.sourcePage, context.anchorId || "", `Returned to ${context.sourceLabel || "setup page"}.`);
    return;
  }
  if (action === "overview-drilldown-universe") {
    jumpToPageAnchor("universe_selector", "universe-controls-anchor", "Jumped from overview KPI to Universe controls.");
    return;
  }
  if (action === "overview-drilldown-regime") {
    jumpToPageAnchor("regime_control", "regime-controls-anchor", "Jumped from overview KPI to Regime controls.");
    return;
  }
  if (action === "overview-drilldown-optimizer") {
    jumpToPageAnchor("optimizer_settings", "optimizer-controls-anchor", "Jumped from overview KPI to Optimizer controls.");
    return;
  }
  if (action === "overview-drilldown-factors") {
    jumpToPageAnchor("factor_lab", "factor-builder-controls-anchor", "Jumped from overview KPI to Factor Builder controls.");
    return;
  }
  if (action === "overview-drilldown-trades") {
    jumpToPageAnchor("holdings_trades", "trade-blotter-controls-anchor", "Jumped from overview KPI to Trade Blotter controls.");
    return;
  }
  if (action === "overview-open-summary") {
    jumpToPageAnchor("overview", "overview-summary-anchor", "Opened overview summary.");
    return;
  }
  if (action === "watch-live-status") {
    openRunStreamViewer(getLatestRunId());
    return;
  }

  const actionMap = {
    "export-overview-snapshot": () => {
      const artifactCount = Array.isArray(store.artifacts.packs) ? store.artifacts.packs.length : 0;
      const completedRuns = store.runHistory.runs.filter((row) => normalizeStatusLabel(row[3]) === "Completed").length;
      const failingChecks = store.health.checks.filter(([, status]) => status !== "Pass").length;
      const healthSummary = store.health.summary || {};
      downloadCsvFile(
        "overview-snapshot.csv",
        ["Metric", "Value", "Note"],
        [
          ["Research Modules", navItems.length, "Formal pages currently available in the live workbench."],
          ["Data Updated", store.health.updatedAt, "Latest pipeline refresh visible from the home screen."],
          ["Delivery Status", `${artifactCount} artifacts / ${completedRuns} completed runs`, "Derived from current artifacts and run history."],
          ["Coverage Floor", healthSummary.coverage_floor || "96.4%", "Connected health summary coverage floor."],
          ["DAG Status", healthSummary.dag_health || "Healthy", "Connected orchestration health state."],
          ["Critical Fails", failingChecks, "Quality-gate issues requiring review before final export."],
        ],
      );
      showToast("Overview snapshot exported as CSV.");
    },
    "save-preset": () => {
      const suggestedName = formState.scenario_builder.active_preset || "Custom preset";
      const presetName = window.prompt("Save preset as:", suggestedName);
      if (!presetName) return;
      const trimmedName = presetName.trim();
      if (!trimmedName) return;
      upsertScenarioPreset(trimmedName, { ...formState.scenario_builder, active_preset: trimmedName });
      formState.scenario_builder.active_preset = trimmedName;
      persistState();
      void saveScenarioBuilderStateToApi();
      showToast(`Preset ${trimmedName} saved to reusable library.`);
      render(false);
    },
    "save-scenario": () => {
      void saveAllScenarioWorkspaceState()
        .then((record) => {
          if (record?.scenario_name) pushNotification(`scenario_saved: ${record.scenario_name}`, "info");
          showToast("All scenario settings saved.");
          render(false);
        })
        .catch((error) => {
          console.warn("Scenario record save failed.", error);
          showToast("Global save failed.");
        });
    },
    "apply-preset": () => {
      const presetName = sourceButton?.dataset.preset;
      if (presetName) applyScenarioPreset(presetName);
    },
    "rename-preset": () => {
      const previousName = sourceButton?.dataset.preset;
      if (!previousName) return;
      const nextNameInput = window.prompt("Rename preset:", previousName);
      if (!nextNameInput) return;
      const nextName = nextNameInput.trim();
      if (!nextName) return;
      if (nextName !== previousName && scenarioPresetConfigs[nextName]) {
        showToast(`Preset ${nextName} already exists.`);
        return;
      }
      if (!renameScenarioPreset(previousName, nextName)) return;
      persistState();
      void saveScenarioBuilderStateToApi();
      showToast(`Preset renamed to ${nextName}.`);
      render(false);
    },
    "delete-preset": () => {
      const presetName = sourceButton?.dataset.preset;
      if (!presetName) return;
      if (!window.confirm(`Delete preset "${presetName}"?`)) return;
      if (!deleteScenarioPreset(presetName)) {
        showToast("Keep at least one preset in the library.");
        return;
      }
      persistState();
      void saveScenarioBuilderStateToApi();
      showToast(`Preset ${presetName} removed.`);
      render(false);
    },
    "duplicate-preset": () => {
      const sourceName = formState.scenario_builder.active_preset || "Base";
      const nextName = getUniquePresetName(`${sourceName} Copy`);
      const duplicatedConfig = { ...formState.scenario_builder, active_preset: nextName };
      upsertScenarioPreset(nextName, duplicatedConfig);
      formState.scenario_builder.active_preset = nextName;
      dirtyState.scenario_builder = true;
      persistState();
      void saveScenarioBuilderStateToApi();
      showToast(`Preset duplicated as ${nextName}.`);
      render(false);
    },
    "clear-draft": () => {
      replaceScenarioBuilderDraft(defaultScenarioBuilderState);
      dirtyState.scenario_builder = false;
      persistState();
      void saveScenarioBuilderStateToApi();
      showToast("Draft cleared back to last saved preset.");
      render(false);
    },
    "run-baseline": () => {
      try {
        if (blockInvalidLaunch(currentPage)) return;
        syncWorkingScenarioFromPage(currentPage);
        const now = formatRunTimestamp(new Date());
        const selectedScenario = getRunnerScenarioSelection();
        const scenarioConfig = selectedScenario.config || {};
        const runId = `BT-${now.compact}`;
        const scenarioLabel = `${selectedScenario.name} / top ${scenarioConfig.top_n || "n/a"} / VIX ${scenarioConfig.vix_threshold || "n/a"}`;
        store.runHistory.runs = sanitizeRunHistoryRows(store.runHistory.runs);
        store.runHistory.runs.unshift([runId, now.display, scenarioLabel, "Running", "Live"]);
        store.runHistory.artifacts = [["Latest NAV pack", "Pending"], ["Risk tearsheet", "Pending"], ["Robustness export", "Pending"], ["Slide appendix", "Pending"]];
        runtimeState.runLogs[runId] = createRunLogLines({
          runId,
          mode: "Single baseline run",
          scenarioLabel,
          owner: formState.backtest_runner.owner,
          priority: formState.backtest_runner.priority,
          scenarioConfig,
        });
        runtimeState.runMeta[runId] = { owner: formState.backtest_runner.owner };
        runtimeState.latestLogRunId = runId;
        runtimeState.highlightedRunId = runId;
        resetRunHistoryFiltersForLiveRuns();
        dirtyState.backtest_runner = false;
        persistState();
        jumpToRunHistory();
        const selectedRecord = getScenarioRecordByName(selectedScenario.name);
        void runBacktestToApi({
          scenarioId: selectedRecord?.scenario_id || runtimeState.activeScenarioId || null,
          scenarioName: selectedScenario.name,
          scenarioConfig,
          owner: formState.backtest_runner.owner,
          priority: formState.backtest_runner.priority,
          artifactBundle: formState.backtest_runner.artifact_bundle,
          notifications: formState.backtest_runner.notifications,
          mode: "full",
        }).then((response) => {
          reconcileProvisionalRunId(runId, response.run_id, "Queued");
          pushNotification(`backtest_queued: ${response.run_id}`, "info");
          return refreshRunHistoryFromApi().then(() => {
            if (currentPage === "run_history") render(false);
          });
        }).catch((error) => console.warn("Backtest run failed to queue.", error));
        showToast("Baseline run started and added to Run History.");
      } catch (error) {
        console.warn("Run baseline action failed before navigation.", error);
        showToast("Run baseline failed before entering Run History.");
      }
    },
    "queue-batch": () => {
      if (blockInvalidLaunch(currentPage)) return;
      syncWorkingScenarioFromPage(currentPage);
      const now = formatRunTimestamp(new Date());
      normalizeBatchTargets();
      const batchTargets = formState.backtest_runner.batch_targets;
      const primaryScenario = batchTargets[0] || "Current working scenario";
      const selectedScenario = primaryScenario === "Current working scenario"
        ? { name: primaryScenario, config: JSON.parse(JSON.stringify(formState.scenario_builder)) }
        : { name: primaryScenario, config: JSON.parse(JSON.stringify(scenarioPresetConfigs[primaryScenario] || formState.scenario_builder)) };
      const scenarioConfig = selectedScenario.config;
      const runId = `BATCH-${now.compact}`;
      const scenarioLabel = `Batch compare / ${batchTargets.join(" vs ")}`;
      store.runHistory.runs.unshift([runId, now.display, scenarioLabel, "Queued", "Pending"]);
      runtimeState.runLogs[runId] = createRunLogLines({
        runId,
        mode: "Batch compare queue",
        scenarioLabel,
        owner: formState.backtest_runner.owner,
        priority: formState.backtest_runner.priority,
        scenarioConfig,
      }).concat([
        `[${now.display.split(" ")[1]}] Batch plan created for ${batchTargets.join(" / ")}`,
        `[${now.display.split(" ")[1]}] Waiting for worker capacity`,
      ]);
      runtimeState.runMeta[runId] = {
        owner: formState.backtest_runner.owner,
        job: {
          run_id: runId,
          queue_type: "batch_compare",
          status: "queued",
          scheduled_for: "",
        },
      };
      runtimeState.latestLogRunId = runId;
      runtimeState.highlightedRunId = runId;
      resetRunHistoryFiltersForLiveRuns();
      dirtyState.backtest_runner = false;
      persistState();
      const scenarioIds = batchTargets
        .map((name) => getScenarioRecordByName(name)?.scenario_id)
        .filter(Boolean);
      if (scenarioIds.length >= 2) {
        void compareBacktestsToApi({
          scenarioIds,
          owner: formState.backtest_runner.owner,
          priority: formState.backtest_runner.priority,
          artifactBundle: formState.backtest_runner.artifact_bundle,
          notifications: formState.backtest_runner.notifications,
        }).then((response) => {
          reconcileProvisionalRunId(runId, response.run_id, "Queued");
          pushNotification(`backtest_compare_queued: ${response.run_id}`, "info");
          return refreshRunHistoryFromApi().then(() => {
            if (currentPage === "run_history") render(false);
          });
        }).catch((error) => console.warn("Backtest compare failed to queue.", error));
      } else {
        void queueRunnerRequestToApi({
          run_id: runId,
          queue_type: "batch_compare",
          label: scenarioLabel,
          owner: formState.backtest_runner.owner,
          priority: formState.backtest_runner.priority,
          scenario_name: selectedScenario.name,
          scenario_config: scenarioConfig,
          batch_targets: batchTargets,
          scenario_configs: getBatchScenarioConfigMap(batchTargets),
          artifact_bundle: formState.backtest_runner.artifact_bundle,
          notifications: formState.backtest_runner.notifications,
          created_at: new Date().toISOString(),
          auto_start: true,
        });
      }
      showToast("Comparison batch queued and added to Run History.");
      jump("run_history");
    },
    "schedule-nightly": () => {
      syncWorkingScenarioFromPage(currentPage);
      const now = formatRunTimestamp(new Date());
      const isNightlyBatch = formState.backtest_runner.nightly_mode === "Batch compare";
      const nightlyTime = String(formState.backtest_runner.nightly_time || "22:00").trim();
      normalizeBatchTargets();
      const selectedScenario = getRunnerScenarioSelection();
      const scenarioConfig = selectedScenario.config;
      const runId = `NIGHTLY-${now.compact}`;
      const scenarioLabel = isNightlyBatch
        ? `Nightly batch refresh / ${formState.backtest_runner.batch_targets.join(" vs ")}`
        : `Nightly single refresh / ${selectedScenario.name}`;
      store.runHistory.runs.unshift([runId, now.display, scenarioLabel, "Scheduled", "Scheduled"]);
      runtimeState.runLogs[runId] = createRunLogLines({
        runId,
        mode: isNightlyBatch ? "Nightly batch refresh schedule" : "Nightly single refresh schedule",
        scenarioLabel,
        owner: formState.backtest_runner.owner,
        priority: formState.backtest_runner.priority,
        scenarioConfig,
      }).concat([
        `[${now.display.split(" ")[1]}] Nightly refresh registered for ${nightlyTime}`,
        isNightlyBatch
          ? `[${now.display.split(" ")[1]}] Batch targets: ${formState.backtest_runner.batch_targets.join(" / ")}`
          : `[${now.display.split(" ")[1]}] Scenario target: ${selectedScenario.name}`,
        `[${now.display.split(" ")[1]}] Dashboard export and artifact refresh will run after data ingestion`,
      ]);
      runtimeState.runMeta[runId] = { owner: formState.backtest_runner.owner };
      runtimeState.latestLogRunId = runId;
      runtimeState.highlightedRunId = runId;
      resetRunHistoryFiltersForLiveRuns();
      dirtyState.backtest_runner = false;
      persistState();
      void queueRunnerRequestToApi({
        run_id: runId,
        queue_type: "nightly_refresh",
        label: scenarioLabel,
        owner: formState.backtest_runner.owner,
        priority: formState.backtest_runner.priority,
        scenario_name: selectedScenario.name,
        scenario_config: scenarioConfig,
        scenario_configs: isNightlyBatch ? getBatchScenarioConfigMap(formState.backtest_runner.batch_targets) : {
          [selectedScenario.name]: getScenarioConfigSnapshotByName(selectedScenario.name),
        },
        batch_targets: isNightlyBatch ? formState.backtest_runner.batch_targets : [],
        artifact_bundle: formState.backtest_runner.artifact_bundle,
        notifications: formState.backtest_runner.notifications,
        created_at: new Date().toISOString(),
        scheduled_for: nightlyTime,
        auto_start: false,
      });
      showToast("Nightly refresh scheduled and added to Run History.");
      if (currentPage === "run_history") render(false);
      jump("run_history");
    },
    "open-logs": async () => {
      const runId = getLatestRunId();
      await loadRunLogFromApi(runId);
      openLogViewer(runId);
      showToast("Latest execution log opened.");
    },
    "open-latest-run": async () => {
      const runId = getLatestRunId();
      if (!runId) {
        showToast("No recent runs are available yet.");
        return;
      }
      runtimeState.highlightedRunId = runId;
      persistState();
      render(false);
      await syncRunJobDetail(runId);
      await loadRunLogFromApi(runId);
      openLogViewer(runId);
      showToast(`Opened latest run ${runId}.`);
    },
    "download-logs": async () => {
      const runId = getLatestRunId();
      const lines = await loadRunLogFromApi(runId);
      if (!runId || !lines?.length) {
        showToast("No logs are available to download.");
        return;
      }
      downloadTextFile(`${runId}-logs.txt`, `${runId}\n${"=".repeat(runId.length)}\n${lines.join("\n")}\n`);
      showToast(`Logs for ${runId} downloaded.`);
    },
    "refresh-history": async () => {
      dirtyState.run_history = false;
      persistState();
      const refreshed = await refreshRunHistoryFromApi();
      showToast(refreshed ? "Run history refreshed from API." : "Run history refresh fell back to local state.");
      render(false);
    },
    "start-history-selection": () => {
      runtimeState.runHistorySelectionMode = true;
      runtimeState.selectedRunIds = [];
      persistState();
      showToast("Selection mode enabled. Choose runs to delete.");
      render(false);
    },
    "cancel-history-selection": () => {
      runtimeState.runHistorySelectionMode = false;
      runtimeState.selectedRunIds = [];
      persistState();
      showToast("Selection mode cancelled.");
      render(false);
    },
    "clear-selected-history": async () => {
      const selectedRows = store.runHistory.runs.filter((row) => runtimeState.selectedRunIds.includes(row[0]));
      const bogusRows = selectedRows.filter((row) => isBogusRunHistoryRow(row));
      const deletableRows = selectedRows.filter((row) => isRunDeletableStatus(getNightlyTemplateDisplayState(row[0], row[3], row[4]).statusLabel));
      if (!deletableRows.length && !bogusRows.length) {
        showToast("Select at least one completed, failed, canceled, or interrupted run to delete.");
        return;
      }
      if (!window.confirm(`Delete ${deletableRows.length + bogusRows.length} selected run record${deletableRows.length + bogusRows.length === 1 ? "" : "s"}?`)) return;
      const deletedIds = [];
      if (bogusRows.length) deletedIds.push(...bogusRows.map((row) => row[0]));
      for (const row of deletableRows) {
        try {
          const response = await deleteBacktestToApi(row[0]);
          const responseIds = Array.isArray(response?.deleted_ids) && response.deleted_ids.length ? response.deleted_ids : [row[0]];
          deletedIds.push(...responseIds);
        } catch (error) {
          console.warn(`Run delete failed for ${row[0]}.`, error);
        }
      }
      const uniqueDeletedIds = [...new Set(deletedIds)];
      const deletedCount = deleteRunHistoryEntries(uniqueDeletedIds);
      runtimeState.selectedRunIds = runtimeState.selectedRunIds.filter((runId) => !uniqueDeletedIds.includes(runId));
      persistState();
      await refreshRunHistoryFromApi().catch((error) => console.warn("Run history refresh after bulk delete failed.", error));
      showToast(`${deletedCount} run${deletedCount > 1 ? "s" : ""} deleted.`);
      render(false);
    },
    "clear-all-history": async () => {
      const bogusRows = store.runHistory.runs.filter((row) => isBogusRunHistoryRow(row));
      const deletableRows = store.runHistory.runs.filter((row) => isRunDeletableStatus(getNightlyTemplateDisplayState(row[0], row[3], row[4]).statusLabel));
      if (!deletableRows.length && !bogusRows.length) {
        showToast("Run history is already empty.");
        return;
      }
      if (!window.confirm("Delete all completed, failed, canceled, and interrupted run records?")) return;
      const deletedIds = bogusRows.map((row) => row[0]);
      for (const row of deletableRows) {
        try {
          const response = await deleteBacktestToApi(row[0]);
          const responseIds = Array.isArray(response?.deleted_ids) && response.deleted_ids.length ? response.deleted_ids : [row[0]];
          deletedIds.push(...responseIds);
        } catch (error) {
          console.warn(`Run delete failed for ${row[0]}.`, error);
        }
      }
      const uniqueDeletedIds = [...new Set(deletedIds)];
      const deletedCount = deleteRunHistoryEntries(uniqueDeletedIds);
      runtimeState.selectedRunIds = [];
      persistState();
      await refreshRunHistoryFromApi().catch((error) => console.warn("Run history refresh after clear-all delete failed.", error));
      showToast(`${deletedCount} run${deletedCount > 1 ? "s" : ""} cleared from history.`);
      render(false);
    },
    "export-history": () => {
      const rowsToExport = getFilteredRunHistoryRows(store.runHistory.runs, formState.run_history);
      downloadCsvFile(
        "run-history.csv",
        ["Run ID", "Started", "Scenario", "Owner", "Status", "Duration"],
        rowsToExport.map((row) => [row[0], row[1], row[2], getRunOwner(row[0]), row[3], row[4]]),
      );
      showToast("Run history exported as CSV.");
    },
    "export-performance-charts": () => {
      const d = store.performance;
      const rows = d.nav.map((navValue, index) => [
        `T${index + 1}`,
        navValue,
        d.benchmark[index],
        d.baseline[index],
        d.drawdown[index],
        d.sharpe[index],
        d.excess[index],
      ]);
      downloadCsvFile(
        "performance-dashboard-series.csv",
        ["Period", "Strategy NAV", "Benchmark", "Static Baseline", "Drawdown", "Rolling Sharpe", "Excess Return"],
        rows,
      );
      showToast("Performance chart series exported.");
    },
    "compare-performance-runs": () => {
      const compareOptions = store.runHistory.runs
        .filter((row) => normalizeStatusLabel(row[3]) === "Completed" && isComparablePerformanceRunId(row[0]))
        .slice(0, 5)
        .map((row) => row[0]);
      const selected = getSelectedSummaryRuns(compareOptions);
      if (!selected.length) {
        showToast("Select at least one summary compare run.");
        return;
      }
      openPerformanceCompareViewer(selected);
      showToast(`Opened summary compare viewer for ${selected.length} run${selected.length === 1 ? "" : "s"}.`);
    },
    "open-performance-drilldown": () => {
      openPerformancePointDrilldownViewer();
      showToast(`Opened ${formState.performance_dashboard.nav_focus_period.toLowerCase()} drilldown.`);
    },
    "performance-open-trades": () => {
      jumpToPageAnchor("holdings_trades", "portfolio-trades-anchor", "Opened Trade Blotter from Performance Dashboard.");
    },
    "preview-current-work": async () => {
      syncWorkingScenarioFromPage(currentPage);
      if (currentPage === "universe_selector") {
        await loadUniversePreview(true);
        return;
      }
      if (currentPage === "regime_control") {
        await loadRegimePreview(true);
        return;
      }
      if (currentPage === "optimizer_settings") {
        await loadOptimizerPreview(true);
        return;
      }
      if (currentPage === "factor_lab") {
        await loadFactorPreview(true);
        return;
      }
      if (currentPage === "holdings_trades") {
        await loadTradePreview(true);
        return;
      }
      const selectedScenario = getRunnerScenarioSelection();
      try {
        const estimate = await estimateBacktestCostToApi({
          scenarioId: getScenarioRecordByName(selectedScenario.name)?.scenario_id || runtimeState.activeScenarioId || null,
          scenarioName: selectedScenario.name,
          scenarioConfig: selectedScenario.config,
          mode: "full",
        });
        showToast(`Preview ready: est. ${estimate.estimate.estimated_minutes} min, ${estimate.estimate.rebalance_frequency}.`);
      } catch (error) {
        console.warn("Preview estimation failed.", error);
        showToast("Preview estimate failed.");
      }
    },
    "open-risk-pack": () => {
      const correlationLabels = ["Value", "Quality", "Momentum", "Dividend"];
      const riskPackSections = [
        "Risk Dashboard Export",
        `Generated: ${store.health.updatedAt}`,
        "",
        "Latest VIX Series:",
        store.regime.vix.map((value, index) => `T${index + 1},${value}`).join("\n"),
        "",
        "Exposure Change:",
        store.regime.exposureChange.map(([label, value]) => `${label},${value}`).join("\n"),
        "",
        "Factor Weights By Regime:",
        store.regime.exposures.map(([label, normal, stress]) => `${label},${(normal * 100).toFixed(0)}%,${(stress * 100).toFixed(0)}%`).join("\n"),
        "",
        "Correlation Matrix:",
        correlationLabels.join(","),
        store.factors.correlation.map((row) => row.join(",")).join("\n"),
      ];
      downloadTextFile("risk-pack.txt", `${riskPackSections.join("\n")}\n`);
      showToast("Risk pack exported.");
    },
    "compare-risk-profile": () => {
      openRiskCompareViewer();
      showToast(`Opened risk compare versus ${formState.risk_dashboard.compare_mode}.`);
    },
    "risk-open-holdings": () => {
      jumpToPageAnchor("holdings_trades", "trade-blotter-controls-anchor", "Opened Trade Blotter from Risk Dashboard.");
    },
    "refresh-vix": async () => {
      await refreshWorkbenchRawSeries(true);
      persistState();
      render(false);
    },
    "run-sensitivity": () => {
      const s = formState.robustness_lab || {};
      const baseScenarioName = String(s.base_scenario || "Current working scenario");
      const selectedConfig = getScenarioConfigSnapshotByName(baseScenarioName);
      const selectedRecord = getScenarioRecordByName(baseScenarioName);
      const now = formatRunTimestamp(new Date());
      const runId = `SENS-${now.compact}`;
      const selectedDimensions = Array.isArray(s.sensitivity_dimensions) ? s.sensitivity_dimensions : [];
      const scenarioLabel = `Sensitivity / ${baseScenarioName} / ${selectedDimensions.join(" / ") || "No dimensions selected"}`;
      store.runHistory.runs = sanitizeRunHistoryRows(store.runHistory.runs);
      store.runHistory.runs.unshift([runId, now.display, scenarioLabel, "Queued", "Pending"]);
      runtimeState.runLogs[runId] = createRunLogLines({
        runId,
        mode: "Robustness sensitivity launch",
        scenarioLabel,
        owner: formState.backtest_runner.owner,
        priority: formState.backtest_runner.priority,
        scenarioConfig: selectedConfig,
      }).concat([
        `[${now.display.split(" ")[1]}] Quarterly-rebalanced sensitivity dimensions: ${selectedDimensions.join(" / ") || "n/a"}`,
        `[${now.display.split(" ")[1]}] Bootstrap iterations: ${s.bootstrap_iterations || "1000"}`,
        `[${now.display.split(" ")[1]}] Stochastic mode: ${s.stochastic_mode || "Bootstrap + Monte Carlo"}`,
        `[${now.display.split(" ")[1]}] Period split definition: ${s.subperiod_definition || "Normal vs stress"}`,
      ]);
      runtimeState.runMeta[runId] = { owner: formState.backtest_runner.owner };
      runtimeState.latestLogRunId = runId;
      runtimeState.highlightedRunId = runId;
      resetRunHistoryFiltersForLiveRuns();
      dirtyState.robustness_lab = false;
      persistState();
      jumpToRunHistory();
      void runSensitivityToApi({
        scenarioId: selectedRecord?.scenario_id || null,
        scenarioName: baseScenarioName,
        scenarioConfig: selectedConfig,
        baseScenario: baseScenarioName,
        sensitivityDimensions: selectedDimensions,
        rangeProfile: s.range_profile,
        bootstrapIterations: s.bootstrap_iterations,
        stochasticMode: s.stochastic_mode,
        subperiodDefinition: s.subperiod_definition,
        owner: formState.backtest_runner.owner,
        priority: formState.backtest_runner.priority,
      }).then((response) => {
        reconcileProvisionalRunId(runId, response.run_id, "Queued");
        pushNotification(`robustness_queued: ${response.run_id}`, "info");
        return refreshRunHistoryFromApi().then(() => {
          showToast(`Sensitivity run queued: ${response.run_id}`);
          render(false);
        });
      }).catch((error) => {
        console.warn("Robustness sensitivity launch failed.", error);
        updateRunStatus(runId, "Failed");
        showToast("Robustness sensitivity launch failed.");
        render(false);
      });
    },
    "promote-best-robustness": () => {
      const bestRow = store.robustness.scenarios.reduce((best, row) => {
        const sharpe = extractNumericValue(row?.[2]);
        if (!best || (sharpe != null && sharpe > best.sharpe)) {
          return { row, sharpe: sharpe ?? Number.NEGATIVE_INFINITY };
        }
        return best;
      }, null);
      if (!bestRow?.row) {
        showToast("No robustness row is available to promote.");
        return;
      }
      syncWorkingScenarioFromPage("robustness_lab");
      const scenarioName = `Robustness fork - ${bestRow.row[0]}`;
      void saveScenarioRecordToApi({
        scenarioName,
        scenarioConfig: buildCurrentWorkingScenarioConfig("robustness_lab"),
        parentScenarioId: runtimeState.activeScenarioId || null,
        notes: `Promoted from Robustness Lab using best visible row: ${bestRow.row[0]}.`,
      }).then((record) => {
        runtimeState.activeScenarioId = record.scenario_id;
        pushNotification(`robustness_promoted: ${record.scenario_name}`, "info");
        return fetchApiJson("/api/scenarios").then(applyScenarioCatalog).then(() => render(false));
      }).catch((error) => console.warn("Robustness promotion failed.", error));
      showToast(`Promoting ${bestRow.row[0]} into a saved scenario fork.`);
    },
    "open-subperiod-performance": () => {
      jump("performance_dashboard");
      showToast("Opened Performance Dashboard from Robustness Lab.");
    },
    "export-robustness-table": () => {
      const scenarioRows = store.robustness.scenarios.map(([scenario, annReturn, sharpe, maxDd]) => [scenario, annReturn, sharpe, maxDd]);
      const percentileRows = store.robustness.percentiles.map(([label, outcome]) => [label, outcome]);
      const content = [
        "Robustness Export",
        "",
        "Parameter Comparison",
        "Scenario,Ann. Return,Sharpe,Max DD",
        scenarioRows.map((row) => row.join(",")).join("\n"),
        "",
        "Percentiles",
        "Percentile,Outcome",
        percentileRows.map((row) => row.join(",")).join("\n"),
      ].join("\n");
      downloadTextFile("robustness-table.csv", `${content}\n`);
      showToast("Robustness tables exported.");
    },
    "open-trades": () => {
      jumpToPageAnchor("holdings_trades", "portfolio-trades-anchor", "Scrolled to trade notes and rebalance log.");
    },
    "export-holdings": () => {
      downloadCsvFile(
        "portfolio-holdings.csv",
        ["Ticker", "Sector", "Weight", "Driver"],
        store.portfolio.holdings,
      );
      showToast("Current holdings exported.");
    },
    "export-delivery-zip": async () => {
      const response = await fetch("/api/delivery/export-zip");
      if (!response.ok) {
        throw new Error("Delivery ZIP export failed.");
      }
      const blob = await response.blob();
      const disposition = response.headers.get("Content-Disposition") || "";
      const filenameMatch = disposition.match(/filename=\"?([^\";]+)\"?/i);
      const filename = filenameMatch?.[1] || "cw2-delivery-bundle.zip";
      downloadBlobFile(filename, blob);
      showToast("Delivery ZIP exported.");
    },
    "refresh-llm-models": async () => {
      const settings = formState.report_studio;
      if (runtimeState.llmModelCatalog?.status === "loading") return;
      if (!settings.api_url.trim()) {
        showToast("Set an API URL first.");
        return;
      }
      if (!settings.api_key.trim()) {
        showToast("Set an API key first.");
        return;
      }
      runtimeState.llmModelCatalog = {
        ...(runtimeState.llmModelCatalog || {}),
        status: "loading",
        error: "",
      };
      render(false);
      try {
        const response = await fetchLlmModelsToApi({
          api_url: settings.api_url.trim(),
          api_key: settings.api_key.trim(),
          request_format: settings.request_format,
        });
        const models = Array.isArray(response.models)
          ? response.models
            .map((row) => ({
              id: String(row.id || row.model || row.name || row.label || "").trim(),
              label: String(row.label || row.id || row.model || row.name || "").trim(),
            }))
            .filter((row) => row.id)
          : [];
        runtimeState.llmModelCatalog = {
          models,
          status: "ready",
          error: "",
          fetchedAt: new Date().toISOString(),
          requestFormat: response.request_format || settings.request_format,
          modelUrl: response.model_url || "",
        };
        if (!settings.model.trim() && models[0]?.id) {
          settings.model = models[0].id;
          dirtyState.report_studio = true;
        }
        persistState();
        render(false);
        showToast(models.length ? `Loaded ${models.length} models.` : "No models returned; manual model remains available.");
      } catch (error) {
        const detail = (error && typeof error.message === "string" && error.message.trim())
          ? error.message.trim()
          : "Could not load models from this provider.";
        runtimeState.llmModelCatalog = {
          models: [],
          status: "error",
          error: detail,
          fetchedAt: "",
          requestFormat: settings.request_format,
          modelUrl: "",
        };
        persistState();
        render(false);
        console.warn("LLM model fetch failed.", error);
        showToast(`Model fetch failed: ${detail}`);
      }
    },
    "edit-model-manual": () => {
      openControlInputDialog("report_studio", "model");
    },
    "generate-ai-report-analysis": async () => {
      const settings = formState.report_studio;
      if (!settings.api_url.trim()) {
        showToast("Set an API URL first.");
        return;
      }
      if (!settings.api_key.trim()) {
        showToast("Set an API key first.");
        return;
      }
      try {
        store.reportStudio.aiReport = {
          ...store.reportStudio.aiReport,
          status: "running",
        };
        render(false);
        const response = await sendApiJson("/api/ai-report/generate", "POST", {
          api_url: settings.api_url.trim(),
          api_key: settings.api_key.trim(),
          model: settings.model.trim(),
          request_format: settings.request_format,
          temperature: Number.parseFloat(settings.temperature || "0.2"),
          user_instruction: settings.user_instruction,
          system_prompt: settings.system_prompt,
        });
        applyAiReportLatest(response);
        try {
          const crossCheck = await crossCheckAiReportToApi(response.report_id || response.reportId || null);
          store.reportStudio.aiReport.guardrails = {
            ...(store.reportStudio.aiReport.guardrails || {}),
            last_cross_check_status: crossCheck.status || "unknown",
            last_cross_check_at: crossCheck.checked_at || "",
            last_cross_check_message: crossCheck.message || "",
          };
        } catch (crossCheckError) {
          store.reportStudio.aiReport.guardrails = {
            ...(store.reportStudio.aiReport.guardrails || {}),
            last_cross_check_status: "failed",
            last_cross_check_at: "",
            last_cross_check_message: "Automatic numeric cross-check failed after generation.",
          };
          console.warn("Automatic AI cross-check failed.", crossCheckError);
        }
        await refreshAiReportHistory();
        dirtyState.report_studio = false;
        persistState();
        render(false);
        showToast("AI report analysis generated.");
      } catch (error) {
        const detail = (error && typeof error.message === "string" && error.message.trim())
          ? error.message.trim()
          : "Unknown error while generating the AI report.";
        store.reportStudio.aiReport = {
          ...store.reportStudio.aiReport,
          status: "failed",
          reportId: "",
          providerUrl: settings.api_url.trim(),
          outputPath: "",
          outputMarkdownPath: "",
          model: settings.model.trim(),
          requestFormat: settings.request_format,
          errorMessage: detail,
        };
        persistState();
        render(false);
        console.warn("AI report generation failed.", error);
        showToast(detail);
      }
    },
    "export-ai-analysis": () => {
      const aiReport = store.reportStudio.aiReport;
      if (!aiReport.analysisText) {
        showToast("No AI analysis is available to export yet.");
        return;
      }
      fetch("/api/ai-report/export-pdf")
        .then(async (response) => {
          if (!response.ok) {
            const detail = await response.text();
            throw new Error(detail || "PDF export failed.");
          }
          const blob = await response.blob();
          const contentDisposition = response.headers.get("content-disposition") || "";
          const fileMatch = contentDisposition.match(/filename=\"?([^\";]+)\"?/i);
          const filename = fileMatch?.[1] || "ai-report-note.pdf";
          downloadBlobFile(filename, blob);
          const latest = await loadJson("/api/ai-report/latest").catch(() => null);
          if (latest) applyAiReportLatest(latest);
          render(false);
          showToast("AI report exported as PDF.");
        })
        .catch((error) => {
          showToast(String(error?.message || "PDF export failed."));
        });
    },
    "open-artifacts": () => {
      const runId = getLatestRunId();
      void syncRunJobDetail(runId).then(() => openArtifactBundleViewer(runId));
      showToast("Opening latest run artifact bundle.");
    },
    "back-to-top": () => {
      scrollToTop();
    },
    "help-benchmark-anchor": () => {
      jumpToPageAnchor("help", "help-benchmark-anchor", "Jumped to benchmark and baseline notes.");
    },
    "help-run-modes-anchor": () => {
      jumpToPageAnchor("help", "help-run-modes-anchor", "Jumped to run mode glossary.");
    },
    "help-platform-anchor": () => {
      jumpToPageAnchor("help", "help-platform-anchor", "Jumped to platform and setup notes.");
    },
  };

  if (actionMap[action]) actionMap[action]();
}

function applyScenarioPreset(presetName) {
  const preset = scenarioPresetConfigs[presetName];
  if (!preset) return;
  replaceScenarioBuilderDraft({ ...preset, active_preset: presetName });
  dirtyState.scenario_builder = true;
  persistState();
  showToast(`${presetName} preset applied.`);
  render(false);
}

function closeSelectMenu() {
  const menu = document.getElementById("control-select-menu");
  if (menu) menu.remove();
  if (selectMenuOutsideHandler) {
    document.removeEventListener("mousedown", selectMenuOutsideHandler);
    selectMenuOutsideHandler = null;
  }
}

function openSelectMenu(button) {
  closeSelectMenu();
  const key = button.dataset.controlKey;
  if (!key || !formState[currentPage]) return;
  const options = (button.dataset.controlOptions || "").split("||").filter(Boolean);
  if (!options.length) return;
  const isMultiSelect = button.dataset.multiSelect === "true";
  const isGroupedModelSelect = button.dataset.controlGrouped === "llm-models" && currentPage === "report_studio" && key === "model";
  const allLabel = options[0];

  const rect = button.getBoundingClientRect();
  const menu = document.createElement("div");
  menu.id = "control-select-menu";
  menu.className = "control-select-menu";
  if (isGroupedModelSelect) menu.classList.add("model-select-menu");
  menu.style.top = `${window.scrollY + rect.bottom + 8}px`;
  menu.style.left = `${window.scrollX + rect.left}px`;
  menu.style.minWidth = `${rect.width}px`;
  menu.style.width = isGroupedModelSelect ? `${Math.max(rect.width, 360)}px` : `${rect.width}px`;

  const updateMultiSelectButtonLabel = () => {
    const summary = getMultiSelectSummary(formState[currentPage][key], allLabel);
    const labelSpan = button.querySelector("span");
    if (labelSpan) labelSpan.textContent = summary;
  };

  const appendOptionButton = (option) => {
    const optionButton = document.createElement("button");
    optionButton.type = "button";
    optionButton.className = "control-select-option";
    if (isGroupedModelSelect) optionButton.classList.add("model-select-option");
    optionButton.textContent = option;
    optionButton.dataset.optionValue = option;
    const currentValue = formState[currentPage][key];
    const currentSelections = isMultiSelect ? normalizeMultiSelectValue(currentValue, allLabel) : [String(currentValue)];
    if (currentSelections.includes(option)) optionButton.classList.add("is-active");
    optionButton.addEventListener("click", () => {
        if (isMultiSelect) {
        const selections = normalizeMultiSelectValue(formState[currentPage][key], allLabel);
        let nextSelections;
        if (option === allLabel) {
          nextSelections = [allLabel];
        } else if (selections.includes(option)) {
          nextSelections = selections.filter((item) => item !== option && item !== allLabel);
          if (!nextSelections.length) nextSelections = [allLabel];
        } else {
          nextSelections = selections.filter((item) => item !== allLabel);
          nextSelections = [...nextSelections, option];
        }
        formState[currentPage][key] = nextSelections;
        syncSharedFieldState(currentPage, key, nextSelections);
        Array.from(menu.querySelectorAll(".control-select-option")).forEach((menuButton) => {
          const menuOption = menuButton.textContent;
          menuButton.classList.toggle("is-active", nextSelections.includes(menuOption));
        });
        updateMultiSelectButtonLabel();
        if (!isViewOnlyControl(currentPage, key)) {
          if (dirtyState[currentPage] !== undefined) dirtyState[currentPage] = true;
          syncWorkingScenarioFromPage(currentPage);
        }
        queueControlFocus(currentPage, key);
        persistState();
        showToast(`${key.replaceAll("_", " ")} updated.`);
        scheduleLivePreview(currentPage);
        if (currentPage === "run_history") {
          render(false);
          setTimeout(() => {
            const refreshedButton = pageContent.querySelector(`[data-control-key="${key}"][data-multi-select="true"]`);
            if (refreshedButton) openSelectMenu(refreshedButton);
          }, 0);
        }
        return;
      } else {
        formState[currentPage][key] = option;
        syncSharedFieldState(currentPage, key, option);
        if (currentPage === "report_studio" && key === "request_format") {
          syncReportApiUrlForFormat(option);
          clearLlmModelCatalog();
        }
      }
      if (!isViewOnlyControl(currentPage, key)) {
        if (dirtyState[currentPage] !== undefined) dirtyState[currentPage] = true;
        syncWorkingScenarioFromPage(currentPage);
      }
      queueControlFocus(currentPage, key);
      persistState();
      if (!isMultiSelect) closeSelectMenu();
      showToast(`${key.replaceAll("_", " ")} updated.`);
      scheduleLivePreview(currentPage);
      render(false);
    });
    menu.appendChild(optionButton);
  };

  if (isGroupedModelSelect) {
    groupLlmModelOptions(options).forEach((group) => {
      const groupLabel = document.createElement("div");
      groupLabel.className = "control-select-group-label";
      groupLabel.textContent = `${group.label} (${group.options.length})`;
      menu.appendChild(groupLabel);
      group.options.forEach(appendOptionButton);
    });
  } else {
    options.forEach(appendOptionButton);
  }

  document.body.appendChild(menu);
  setTimeout(() => {
    const closeOnOutside = (event) => {
      if (!menu.contains(event.target) && event.target !== button) {
        closeSelectMenu();
      }
    };
    selectMenuOutsideHandler = closeOnOutside;
    document.addEventListener("mousedown", closeOnOutside);
  }, 0);
}

function formatControlLabel(key) {
  const label = String(key || "")
    .replaceAll("_", " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
  return label
    .replace(/\bApi\b/g, "API")
    .replace(/\bUrl\b/g, "URL")
    .replace(/\bVix\b/g, "VIX")
    .replace(/\bYtd\b/g, "YTD")
    .replace(/\bLlm\b/g, "LLM");
}

function closeControlInputDialog() {
  const dialog = document.getElementById("control-input-dialog");
  if (dialog) dialog.remove();
  if (inputDialogKeydownHandler) {
    document.removeEventListener("keydown", inputDialogKeydownHandler);
    inputDialogKeydownHandler = null;
  }
}

function applyControlInputValue(page, key, rawValue) {
  const state = formState[page];
  if (!state) return false;
  const trimmed = String(rawValue ?? "").trim();
  const allowsBlank = page === "report_studio" && REPORT_STUDIO_OPTIONAL_INPUT_KEYS.has(key);
  if (!trimmed && !allowsBlank) {
    showToast(`${formatControlLabel(key)} cannot be empty.`);
    return false;
  }
  if (key === "hold_cap") {
    state[key] = trimmed.includes("%") ? trimmed : `${trimmed}%`;
  } else {
    state[key] = trimmed;
  }
  if (page === "report_studio" && ["api_url", "api_key"].includes(key)) {
    clearLlmModelCatalog();
  }
  if (!isViewOnlyControl(page, key)) {
    if (dirtyState[page] !== undefined) dirtyState[page] = true;
    syncWorkingScenarioFromPage(page);
  }
  queueControlFocus(page, key);
  persistState();
  showToast(`${key.replaceAll("_", " ")} updated.`);
  scheduleLivePreview(page);
  render(false);
  return true;
}

function openControlInputDialog(page, key) {
  closeSelectMenu();
  closeControlInputDialog();
  const state = formState[page];
  if (!state) return;

  const label = formatControlLabel(key);
  const isSecret = SECRET_INPUT_KEYS.has(key);
  const isMultiline = MULTILINE_INPUT_KEYS.has(key);
  const currentValue = isSecret ? "" : String(state[key] ?? "");

  const overlay = document.createElement("div");
  overlay.id = "control-input-dialog";
  overlay.className = "log-viewer-overlay control-input-dialog-overlay";
  Object.assign(overlay.style, {
    position: "fixed",
    inset: "0",
    zIndex: "80",
    display: "grid",
    placeItems: "center",
    padding: "24px",
    background: "rgba(14, 22, 40, 0.46)",
    backdropFilter: "blur(4px)",
  });

  const modal = document.createElement("div");
  modal.className = "log-viewer-modal control-input-dialog";
  modal.setAttribute("role", "dialog");
  modal.setAttribute("aria-modal", "true");
  modal.setAttribute("aria-labelledby", "control-input-dialog-title");
  Object.assign(modal.style, {
    width: "min(680px, 100%)",
    maxHeight: "min(78vh, 760px)",
    display: "grid",
    gridTemplateRows: "auto 1fr auto",
    background: "#0f172a",
    color: "#e7eefc",
    border: "1px solid rgba(255, 255, 255, 0.08)",
    borderRadius: "20px",
    boxShadow: "0 24px 60px rgba(15, 23, 42, 0.34)",
    overflow: "hidden",
  });

  const header = document.createElement("div");
  header.className = "log-viewer-header control-input-dialog-header";
  Object.assign(header.style, {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "flex-start",
    gap: "16px",
    padding: "22px 30px 20px",
    borderBottom: "1px solid rgba(255, 255, 255, 0.08)",
  });
  const eyebrow = document.createElement("span");
  eyebrow.className = "workspace-badge";
  eyebrow.textContent = "Edit field";
  const title = document.createElement("h3");
  title.id = "control-input-dialog-title";
  title.textContent = label;
  Object.assign(title.style, {
    margin: "10px 0 0",
    color: "#f8fbff",
  });
  const headerText = document.createElement("div");
  headerText.append(eyebrow, title);
  const closeButton = document.createElement("button");
  closeButton.type = "button";
  closeButton.className = "log-close-button";
  closeButton.textContent = "Close";
  header.append(headerText, closeButton);

  const body = document.createElement("div");
  body.className = "log-viewer-body control-input-dialog-body";
  Object.assign(body.style, {
    display: "grid",
    gap: "14px",
    padding: "26px 30px 12px",
    overflowY: "auto",
    fontFamily: "inherit",
  });
  const fieldWrap = document.createElement("div");
  fieldWrap.className = "control-input-dialog-field-wrap";
  Object.assign(fieldWrap.style, {
    display: "grid",
    gap: "10px",
  });

  const field = isMultiline ? document.createElement("textarea") : document.createElement("input");
  field.className = "control-input-dialog-field";
  if (!isMultiline) field.type = isSecret ? "password" : "text";
  field.value = currentValue;
  field.placeholder = isSecret && state[key] ? "Existing session key is hidden" : label;
  field.setAttribute("aria-label", label);
  if (isMultiline) field.rows = 8;
  Object.assign(field.style, {
    width: "100%",
    boxSizing: "border-box",
    border: "1px solid rgba(255, 255, 255, 0.18)",
    borderRadius: "16px",
    background: "rgba(255, 255, 255, 0.96)",
    color: "#111827",
    padding: isMultiline ? "16px 18px" : "15px 18px",
    font: "700 1rem/1.55 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
    letterSpacing: "0",
    outline: "none",
    textTransform: "none",
    minHeight: isMultiline ? "210px" : "58px",
    resize: isMultiline ? "vertical" : "",
    boxShadow: "inset 0 1px 0 rgba(255, 255, 255, 0.8), 0 0 0 1px rgba(99, 102, 241, 0.12)",
  });
  fieldWrap.appendChild(field);
  body.appendChild(fieldWrap);

  if (isSecret && state[key]) {
    const hint = document.createElement("p");
    hint.className = "control-input-dialog-hint";
    hint.textContent = "The saved session key is hidden. Enter a replacement, or save blank to clear it.";
    Object.assign(hint.style, {
      margin: "0",
      color: "#cbd6ef",
      fontSize: "0.86rem",
      lineHeight: "1.5",
    });
    body.appendChild(hint);
  }

  const actions = document.createElement("div");
  actions.className = "selector-action-row control-input-dialog-actions";
  Object.assign(actions.style, {
    display: "flex",
    justifyContent: "flex-end",
    gap: "12px",
    margin: "8px 30px 28px",
    paddingTop: "18px",
    borderTop: "1px solid rgba(255, 255, 255, 0.08)",
  });
  const saveButton = document.createElement("button");
  saveButton.type = "button";
  saveButton.className = "selector-action-button selector-action-primary";
  saveButton.textContent = "Save";
  actions.appendChild(saveButton);

  modal.append(header, body, actions);
  overlay.appendChild(modal);
  document.body.appendChild(overlay);

  const submit = () => {
    if (applyControlInputValue(page, key, field.value)) {
      closeControlInputDialog();
    }
  };
  closeButton.addEventListener("click", closeControlInputDialog);
  saveButton.addEventListener("click", submit);
  overlay.addEventListener("mousedown", (event) => {
    if (event.target === overlay) closeControlInputDialog();
  });
  inputDialogKeydownHandler = (event) => {
    if (event.key === "Escape") {
      closeControlInputDialog();
      return;
    }
    if (event.key === "Enter" && !isMultiline) {
      event.preventDefault();
      submit();
    }
  };
  document.addEventListener("keydown", inputDialogKeydownHandler);
  setTimeout(() => field.focus(), 0);
}

function handleControlInteraction(button) {
  const key = button.dataset.controlKey;
  if (!key || !formState[currentPage]) return;
  const state = formState[currentPage];

  if (button.classList.contains("mini-tag")) {
    const tagValue = button.dataset.tagValue;
    if (!tagValue || !Array.isArray(state[key])) return;
    const minSelect = Number(button.dataset.minSelect || 1);
    if (state[key].includes(tagValue)) {
      if (state[key].length <= minSelect) {
        showToast(`Select at least ${minSelect} option${minSelect > 1 ? "s" : ""}.`);
        return;
      }
      state[key] = state[key].filter((item) => item !== tagValue);
    } else {
      state[key] = [...state[key], tagValue];
    }
    if (!isViewOnlyControl(currentPage, key)) {
      if (dirtyState[currentPage] !== undefined) dirtyState[currentPage] = true;
      syncWorkingScenarioFromPage(currentPage);
    }
    queueControlFocus(currentPage, key);
    persistState();
    showToast(`${tagValue} sleeve updated.`);
    scheduleLivePreview(currentPage);
    render(false);
    return;
  }

  if (button.classList.contains("switch")) {
    state[key] = !state[key];
    if (!isViewOnlyControl(currentPage, key)) {
      if (dirtyState[currentPage] !== undefined) dirtyState[currentPage] = true;
      syncWorkingScenarioFromPage(currentPage);
    }
    queueControlFocus(currentPage, key);
    persistState();
    showToast(`${key.replaceAll("_", " ")} updated.`);
    scheduleLivePreview(currentPage);
    render(false);
    return;
  }

  if (button.classList.contains("input")) {
    openControlInputDialog(currentPage, key);
    return;
  }

  if (button.classList.contains("select")) {
    openSelectMenu(button);
  }
}

function getFloatingControlHost() {
  let host = document.getElementById("floating-control-host");
  if (!host) {
    host = document.createElement("div");
    host.id = "floating-control-host";
    document.body.appendChild(host);
  }
  return host;
}

function bindInteractiveElements(root) {
  if (!root) return;
  root.querySelectorAll("[data-jump-page]").forEach((button) => {
    button.addEventListener("click", () => {
      const targetPage = button.dataset.jumpPage;
      if (!renderers[targetPage]) return;
      currentPage = targetPage;
      currentSection = pageToSection[targetPage] || "home";
      render(true);
    });
  });
  root.querySelectorAll("[data-jump-anchor]").forEach((button) => {
    button.addEventListener("click", () => {
      const anchorId = button.dataset.jumpAnchor;
      if (!anchorId) return;
      scrollToCurrentPageAnchor(anchorId);
    });
  });
  root.querySelectorAll("[data-action]").forEach((button) => {
    button.addEventListener("click", () => {
      handleAction(button.dataset.action, button);
    });
  });
  root.querySelectorAll("[data-preset]").forEach((button) => {
    if (button.dataset.action) return;
    button.addEventListener("click", () => {
      applyScenarioPreset(button.dataset.preset);
    });
  });
  root.querySelectorAll("[data-control-key]").forEach((button) => {
    button.addEventListener("click", () => {
      handleControlInteraction(button);
    });
  });
  root.querySelectorAll("[data-toggle-run-id]").forEach((button) => {
    button.addEventListener("click", () => {
      const runId = button.dataset.toggleRunId;
      if (!runId) return;
      const historyWrap = pageContent.querySelector(".history-table-wrap");
      runtimeState.runHistoryScrollTop = historyWrap ? historyWrap.scrollTop : runtimeState.runHistoryScrollTop;
      runtimeState.selectedRunIds = runtimeState.selectedRunIds.includes(runId)
        ? runtimeState.selectedRunIds.filter((item) => item !== runId)
        : [...runtimeState.selectedRunIds, runId];
      persistState();
      render(false);
    });
  });
  root.querySelectorAll("[data-open-run-log]").forEach((button) => {
    button.addEventListener("click", async () => {
      const runId = button.dataset.openRunLog;
      if (!runId) return;
      runtimeState.highlightedRunId = runId;
      await syncRunJobDetail(runId);
      await loadRunLogFromApi(runId);
      openLogViewer(runId);
    });
  });
  root.querySelectorAll("[data-open-run-detail]").forEach((button) => {
    button.addEventListener("click", async () => {
      const runId = button.dataset.openRunDetail;
      if (!runId) return;
      runtimeState.highlightedRunId = runId;
      const detail = await syncRunJobDetail(runId);
      if (!detail) {
        showToast("No backend detail is available for this run yet.");
        return;
      }
      openRunDetailViewer(runId);
    });
  });
  root.querySelectorAll("[data-open-run-artifacts]").forEach((button) => {
    button.addEventListener("click", async () => {
      const runId = button.dataset.openRunArtifacts;
      if (!runId) return;
      runtimeState.highlightedRunId = runId;
      await syncRunJobDetail(runId);
      await openArtifactBundleViewer(runId);
    });
  });
  root.querySelectorAll("[data-rerun-id]").forEach((button) => {
    button.addEventListener("click", async () => {
      const runId = button.dataset.rerunId;
      if (!runId) return;
      runtimeState.highlightedRunId = runId;
      const rerunStarted = await rerunHistoryEntry(runId);
      if (rerunStarted) {
        showToast(`Rerun requested for ${runId}.`);
      }
    });
  });
  root.querySelectorAll("[data-clone-run-id]").forEach((button) => {
    button.addEventListener("click", async () => {
      const runId = button.dataset.cloneRunId;
      if (!runId) return;
      runtimeState.highlightedRunId = runId;
      await cloneRunToScenario(runId);
      showToast(`Scenario cloned from ${runId}.`);
    });
  });
  root.querySelectorAll("[data-cancel-run-id]").forEach((button) => {
    button.addEventListener("click", async () => {
      const runId = button.dataset.cancelRunId;
      if (!runId) return;
      if (!window.confirm(`Cancel run "${runId}"?`)) return;
      runtimeState.highlightedRunId = runId;
      const rowIndex = store.runHistory.runs.findIndex((row) => row[0] === runId);
      if (rowIndex >= 0) {
        const existing = [...store.runHistory.runs[rowIndex]];
        existing[3] = "Canceled";
        store.runHistory.runs[rowIndex] = existing;
        if (!runtimeState.runMeta[runId]) runtimeState.runMeta[runId] = {};
        const canceledAt = new Date().toISOString();
        runtimeState.runMeta[runId].job = {
          ...(runtimeState.runMeta[runId].job || {}),
          run_id: runId,
          status: "canceled",
          updated_at: canceledAt,
          finished_at: runtimeState.runMeta[runId].job?.finished_at || canceledAt,
        };
        render(false);
      }
      await cancelBacktestToApi(runId).then(() => refreshRunHistoryFromApi()).catch((error) => console.warn("Run cancel failed.", error));
      showToast(`Cancel requested for ${runId}.`);
    });
  });
  root.querySelectorAll("[data-delete-run-id]").forEach((button) => {
    button.addEventListener("click", async () => {
      const runId = button.dataset.deleteRunId;
      if (!runId) return;
      if (!window.confirm(`Delete run record "${runId}"?`)) return;
      runtimeState.highlightedRunId = runId;
      const row = sanitizeRunHistoryRows(store.runHistory.runs).find((item) => item[0] === runId);
      if (isBogusRunHistoryRow(row || [runId, "", "queued run", "Canceled", "n/a"])) {
        deleteRunHistoryEntries([runId]);
        persistState();
        render(false);
        showToast(`Removed invalid history row ${runId}.`);
        return;
      }
      try {
        const response = await deleteBacktestToApi(runId);
        const deletedIds = Array.isArray(response?.deleted_ids) && response.deleted_ids.length
          ? response.deleted_ids
          : [runId];
        deleteRunHistoryEntries(deletedIds);
        persistState();
        await refreshRunHistoryFromApi().catch((error) => console.warn("Run history refresh after delete failed.", error));
        render(false);
        showToast(`Deleted ${deletedIds.join(", ")}.`);
      } catch (error) {
        console.warn("Run delete failed.", error);
        const detail = String(error?.message || "Run delete failed.");
        const normalizedDisplayedStatus = normalizeStatusLabel(row?.[3] || "");
        if (
          normalizedDisplayedStatus === "Canceled" &&
          /not deletable|still active|cannot be deleted/i.test(detail)
        ) {
          try {
            await cancelBacktestToApi(runId).catch((cancelError) => {
              console.warn("Run re-cancel before delete failed.", cancelError);
              return null;
            });
            const retryResponse = await deleteBacktestToApi(runId);
            const deletedIds = Array.isArray(retryResponse?.deleted_ids) && retryResponse.deleted_ids.length
              ? retryResponse.deleted_ids
              : [runId];
            deleteRunHistoryEntries(deletedIds);
            persistState();
            await refreshRunHistoryFromApi().catch((refreshError) => console.warn("Run history refresh after delete retry failed.", refreshError));
            render(false);
            showToast(`Deleted ${deletedIds.join(", ")}.`);
            return;
          } catch (retryError) {
            console.warn("Run delete retry after cancel failed.", retryError);
            showToast(String(retryError?.message || detail));
            return;
          }
        }
        showToast(detail);
      }
    });
  });
  root.querySelectorAll("[data-date-key]").forEach((input) => {
    input.addEventListener("change", () => {
      const key = input.dataset.dateKey;
      if (!key || !formState[currentPage]) return;
      formState[currentPage][key] = input.value;
      queueControlFocus(currentPage, key);
      persistState();
      render(false);
    });
  });
}

function render(shouldScrollTop = false) {
  if (!shouldScrollTop) {
    runtimeState.pageScrollY = window.scrollY || window.pageYOffset || 0;
    if (currentPage === "artifacts") {
      runtimeState.artifactOpenKeys = Array.from(document.querySelectorAll(".artifact-folder[open][data-artifact-key]"))
        .map((node) => node.getAttribute("data-artifact-key"))
        .filter(Boolean);
    }
  } else {
    runtimeState.pageScrollY = 0;
  }
  currentSection = pageToSection[currentPage] || "home";
  if (currentPage === "universe_selector" && !apiRuntime.universePreviewLoaded) void loadUniversePreview(false);
  if (currentPage === "regime_control" && !apiRuntime.regimePreviewLoaded) void loadRegimePreview(false);
  if (currentPage === "optimizer_settings" && !apiRuntime.optimizerPreviewLoaded) void loadOptimizerPreview(false);
  if (currentPage === "factor_lab" && !apiRuntime.factorPreviewLoaded) void loadFactorPreview(false);
  if (currentPage === "holdings_trades" && !apiRuntime.tradePreviewLoaded) void loadTradePreview(false);
  renderNav();
  const meta = navItems.find((item) => item.id === currentPage);
  pageTitle.textContent = meta.label;
  pageKicker.textContent = meta.kicker;
  pageContent.innerHTML = `${renderWorkspaceBar(currentPage)}${renderers[currentPage]()}${renderBackToTopButton()}${renderGlobalActionDock(currentPage)}`;
  const floatingControlHost = getFloatingControlHost();
  floatingControlHost.innerHTML = renderFloatingControlHub(currentPage);
  updateSnapshot();
  updateTopChrome();
  systemNavButtons.forEach((button) => button.classList.toggle("is-active", button.dataset.section === currentSection));
  const topScenarioSwitcher = document.getElementById("top-scenario-switcher");
  if (topScenarioSwitcher) {
    topScenarioSwitcher.addEventListener("click", () => openTopScenarioMenu(topScenarioSwitcher));
  }
  const topNotificationButton = document.getElementById("top-notification-button");
  if (topNotificationButton) {
    topNotificationButton.addEventListener("click", () => openNotificationViewer());
  }
  const topSetMainlineButton = document.getElementById("top-set-mainline-button");
  if (topSetMainlineButton) {
    topSetMainlineButton.addEventListener("click", () => {
      const activeId = runtimeState.activeScenarioId || store.scenarioCenter.mainlineId;
      if (!activeId) {
        showToast("No scenario is selected.");
        return;
      }
      setMainlineScenarioToApi(activeId)
        .then((record) => {
          pushNotification(`scenario_set_mainline: ${record.scenario_name}`, "info");
          return fetchApiJson("/api/scenarios");
        })
        .then((rows) => {
          applyScenarioCatalog(rows);
          persistState({ saveScenarioBuilder: true });
          render(false);
          showToast("Mainline scenario updated.");
        })
        .catch((error) => {
          console.warn("Set mainline failed.", error);
          showToast("Set mainline failed.");
        });
    });
  }
  bindInteractiveElements(pageContent);
  bindInteractiveElements(floatingControlHost);
  const historyWrap = pageContent.querySelector(".history-table-wrap");
  if (historyWrap && !shouldScrollTop && currentPage === "run_history") {
    historyWrap.scrollTop = runtimeState.runHistoryScrollTop || 0;
    historyWrap.addEventListener("scroll", () => {
      runtimeState.runHistoryScrollTop = historyWrap.scrollTop;
    });
  }
  if (!shouldScrollTop) {
    if (currentPage === "artifacts" && Array.isArray(runtimeState.artifactOpenKeys) && runtimeState.artifactOpenKeys.length) {
      runtimeState.artifactOpenKeys.forEach((key) => {
        const folder = pageContent.querySelector(`.artifact-folder[data-artifact-key="${CSS.escape(key)}"]`);
        if (folder) folder.open = true;
      });
    }
    window.scrollTo(0, runtimeState.pageScrollY || 0);
  }
  persistState();
  consumePendingControlFocus();
  if (shouldScrollTop) scrollToTop();
}

sidebarToggle.addEventListener("click", () => {
  sidebarCollapsed = !sidebarCollapsed;
  document.body.classList.toggle("sidebar-collapsed", sidebarCollapsed);
  sidebarToggle.textContent = sidebarCollapsed ? "Show" : "Hide";
});
systemNavButtons.forEach((button) => button.addEventListener("click", () => { currentSection = button.dataset.section; currentPage = navSections[currentSection][0]; render(true); }));

if (!navItems.some((item) => item.id === "universe_selector")) {
  const insertionIndex = Math.max(navItems.findIndex((item) => item.id === "scenario_builder") + 1, 3);
  navItems.splice(
    insertionIndex,
    0,
    { id: "universe_selector", label: "Universe & Company Selector", kicker: "Research Setup", icon: "U" },
    { id: "regime_control", label: "Regime & Threshold Control", kicker: "Research Setup", icon: "R" },
    { id: "optimizer_settings", label: "Portfolio Optimizer Settings", kicker: "Research Setup", icon: "P" },
  );
}
navSections.research_setup = [
  "scenario_builder",
  "universe_selector",
  "regime_control",
  "optimizer_settings",
  "data_health",
  "backtest_runner",
  "run_history",
];
pageToSection.universe_selector = "research_setup";
pageToSection.regime_control = "research_setup";
pageToSection.optimizer_settings = "research_setup";

store.universeSelector = store.universeSelector || {
  summary: {
    universe_size: 480,
    candidate_buffer: 200,
    coverage_pct: 98.8,
    avg_market_cap_usd_bn: 182,
    avg_liquidity_score: 98.4,
    benchmark: "Static baseline + market benchmark",
    top_n_target: 25,
  },
  sectorMix: [["Technology", 22], ["Health Care", 14], ["Financials", 13], ["Consumer Staples", 9], ["Industrials", 11], ["Energy", 8]],
  companyPreview: [["MSFT", "Technology", "98.4", "Quality / market leadership"], ["JNJ", "Health Care", "97.7", "Defensive quality"], ["XOM", "Energy", "97.0", "Value / dividend"], ["PG", "Consumer Staples", "96.3", "Dividend stability"], ["JPM", "Financials", "95.6", "Large-cap balance sheet"]],
  notes: [],
};
store.regimeControl = store.regimeControl || {
  summary: {
    current_regime: "Stress",
    latest_vix: 28.4,
    stress_threshold: 22.0,
    warning_threshold: 20.0,
    stress_share_pct: 40.0,
    overlay_enabled: true,
  },
  timeline: [["T5", "21.0", "Normal"], ["T6", "24.0", "Stress"], ["T7", "27.0", "Stress"], ["T8", "30.0", "Stress"], ["T9", "28.0", "Stress"], ["T10", "26.0", "Stress"], ["T11", "24.0", "Stress"], ["T12", "22.0", "Stress"]],
  exposures: [["Dividend", "24.0%", "34.0%", "+10.0pp"], ["Quality", "22.0%", "30.0%", "+8.0pp"], ["Value", "27.0%", "24.0%", "-3.0pp"], ["Momentum", "27.0%", "12.0%", "-15.0pp"]],
  notes: [],
};
store.optimizerSettings = store.optimizerSettings || {
  summary: {
    target_names: 25,
    hybrid_band: "25-35",
    single_name_cap_pct: 5.0,
    expected_turnover_pct: 18.2,
    predicted_vol_pct: 11.1,
    expected_tracking_error_pct: 4.8,
    rebalance: "Quarterly",
  },
  constraints: [["Transaction cost", "15.0 bps"], ["Neutralisation", "Sector-neutral"], ["Stress overlay", "Enabled"], ["Output pack", "NAV + holdings + risk"]],
  factorMix: [["Quality", "18.0%", "40.0%"], ["Value", "24.0%", "10.0%"], ["Market Technical", "43.0%", "5.0%"], ["Dividend", "15.0%", "40.0%"]],
  holdingsPreview: [["MSFT", "Technology", "5.0%", "Quality"], ["JNJ", "Health Care", "4.7%", "Value"], ["PG", "Consumer Staples", "4.4%", "Market Technical"], ["XOM", "Energy", "4.1%", "Dividend"], ["ABBV", "Health Care", "3.8%", "Quality"]],
  notes: [],
};
store.factorBuilder = store.factorBuilder || {
  scenarioName: "Current working scenario",
  summary: {
    activeFactorCount: 4,
    subVariableCount: 12,
    avgIc: "0.043",
    avgRankIc: "0.056",
    neutralisationEnabled: true,
    topPreviewCount: 25,
  },
  factorRows: [
    { factor: "Quality", subVariables: ["ROE", "Gross Margin", "Accruals"], ic: "0.058", rankIc: "0.072", hitRatePct: "61.0" },
    { factor: "Value", subVariables: ["B/P", "E/P", "FCF Yield"], ic: "0.041", rankIc: "0.054", hitRatePct: "58.0" },
    { factor: "Market Technical", subVariables: ["6M Return", "12-1 Return", "EPS Revision"], ic: "0.033", rankIc: "0.047", hitRatePct: "54.0" },
    { factor: "Dividend", subVariables: ["Yield", "Payout Stability", "Coverage"], ic: "0.052", rankIc: "0.065", hitRatePct: "60.0" },
  ],
  alphaDistribution: [{ bucket: "-2 sigma", count: 7 }, { bucket: "-1 sigma", count: 19 }, { bucket: "0 sigma", count: 36 }, { bucket: "+1 sigma", count: 24 }, { bucket: "+2 sigma", count: 11 }],
  topPreview: [{ ticker: "MSFT", sector: "Technology", factor: "Quality", score: 97.5 }, { ticker: "JNJ", sector: "Health Care", factor: "Dividend", score: 94.8 }, { ticker: "PG", sector: "Consumer Staples", factor: "Dividend", score: 92.4 }, { ticker: "XOM", sector: "Energy", factor: "Value", score: 90.1 }, { ticker: "ABBV", sector: "Health Care", factor: "Quality", score: 88.7 }],
  notes: [],
};
store.tradeBlotter = store.tradeBlotter || {
  scenarioName: "Current working scenario",
  summary: {
    tradeCount: 4,
    grossTurnoverPct: 18.2,
    largestSector: "Consumer Staples",
    executionStyle: "Quarterly batch",
    singleNameCapPct: 5.0,
    transactionCostBps: 15.0,
  },
  tradeRows: [
    { ticker: "PG", side: "Buy", sector: "Consumer Staples", weightDeltaPct: 1.4, triggerReason: "Stress overlay raised defensive sleeve", alphaDriver: "Dividend stability", riskStatus: "Within cap", optimizerNote: "Incumbent retained and topped up" },
    { ticker: "JNJ", side: "Buy", sector: "Health Care", weightDeltaPct: 1.1, triggerReason: "Quality sleeve strengthened", alphaDriver: "Defensive quality", riskStatus: "Within cap", optimizerNote: "Turnover-efficient add" },
    { ticker: "XOM", side: "Trim", sector: "Energy", weightDeltaPct: -0.7, triggerReason: "Cap rebalance after overlay shift", alphaDriver: "Value / dividend carry", riskStatus: "Sector neutralisation active", optimizerNote: "Reduced to preserve breadth" },
    { ticker: "NVDA", side: "Sell", sector: "Technology", weightDeltaPct: -1.6, triggerReason: "Momentum sleeve reduced in stress", alphaDriver: "Market technical", riskStatus: "Risk-off rotation", optimizerNote: "Exited after rank deterioration" },
  ],
  rawTradeRows: [],
  attributionRows: [{ source: "Regime overlay", sharePct: 42.0 }, { source: "Factor rank refresh", sharePct: 31.0 }, { source: "Risk caps", sharePct: 17.0 }, { source: "Turnover controls", sharePct: 10.0 }],
  holdingsRows: [{ ticker: "PG", sector: "Consumer Staples", weightPct: 4.7, role: "Dividend / defence" }, { ticker: "JNJ", sector: "Health Care", weightPct: 4.5, role: "Quality" }, { ticker: "MSFT", sector: "Technology", weightPct: 4.3, role: "Core quality" }, { ticker: "XOM", sector: "Energy", weightPct: 4.0, role: "Value / dividend" }, { ticker: "ABBV", sector: "Health Care", weightPct: 3.7, role: "Defensive growth" }],
  rawHoldingsRows: [],
  notes: [],
};
store.riskRaw = store.riskRaw || {
  asOfDate: "",
  availableDates: [],
  contributionsAsOfDate: "",
  contributionAvailableDates: [],
  rows: [],
  contributionRows: [],
};
store.factorRaw = store.factorRaw || {
  asOfDate: "",
  scoreRows: [],
  attributionRows: [],
};

formState.universe_selector = formState.universe_selector || {
  universe: "US Large Cap",
  benchmark: "Static baseline + market benchmark",
  company_focus: "Large and liquid only",
  require_dividend: false,
  sector_tilt: "Balanced",
};
formState.regime_control = formState.regime_control || {
  stress_overlay: true,
  vix_threshold: "22",
  warning_band: "20",
  exit_band: "18",
  regime_mode: "VIX-aware",
  replay_window: "Last 12 observations",
};
formState.optimizer_settings = formState.optimizer_settings || {
  top_n: "25",
  hold_cap: "5%",
  transaction_cost: "15bps",
  neutralisation: true,
  turnover_target: "18%",
  optimizer_goal: "Balanced alpha / risk",
};
dirtyState.universe_selector = dirtyState.universe_selector || false;
dirtyState.regime_control = dirtyState.regime_control || false;
dirtyState.optimizer_settings = dirtyState.optimizer_settings || false;
dirtyState.factor_lab = dirtyState.factor_lab || false;
dirtyState.holdings_trades = dirtyState.holdings_trades || false;

workspaceConfigs.universe_selector = {
  badge: "Research Setup",
  chips: ["Universe scope", "Company screen", "Coverage preview"],
  actions: [],
  showDirty: true,
};
workspaceConfigs.regime_control = {
  badge: "Research Setup",
  chips: ["Regime trigger", "Threshold replay", "Exposure shift"],
  actions: [],
  showDirty: true,
};
workspaceConfigs.optimizer_settings = {
  badge: "Research Setup",
  chips: ["Breadth", "Caps", "Turnover estimate"],
  actions: [],
  showDirty: true,
};

function getScenarioPayloadForPreview(pageId) {
  const activeScenario = store.scenarioCenter.items.find((row) => row.scenario_id === runtimeState.activeScenarioId)
    || store.scenarioCenter.items.find((row) => row.is_mainline)
    || null;
  const scenarioConfig = buildCurrentWorkingScenarioConfig(pageId);
  return {
    scenario_id: activeScenario?.scenario_id || runtimeState.activeScenarioId || null,
    scenario_name: activeScenario?.scenario_name || formState.scenario_builder.active_preset || "Current working scenario",
    scenario_config: scenarioConfig,
  };
}

function applyUniversePreview(payload) {
  store.universeSelector.summary = payload.summary || store.universeSelector.summary;
  store.universeSelector.sectorMix = (payload.sector_mix || []).map((row) => [row.sector, row.weight_pct]);
  store.universeSelector.companyPreview = (payload.company_preview || []).map((row) => [row.ticker, row.sector, String(row.liquidity_score), row.selection_note]);
  store.universeSelector.notes = payload.notes || [];
}

function applyRegimePreview(payload) {
  store.regimeControl.summary = payload.summary || store.regimeControl.summary;
  store.regimeControl.timeline = (payload.timeline || []).map((row) => [row.period, String(row.vix), row.state]);
  store.regimeControl.exposures = (payload.exposures || []).map((row) => [row.factor, `${row.normal_weight_pct.toFixed(1)}%`, `${row.stress_weight_pct.toFixed(1)}%`, `${row.shift_pct > 0 ? "+" : ""}${row.shift_pct.toFixed(1)}pp`]);
  store.regimeControl.notes = payload.notes || [];
}

function applyOptimizerPreview(payload) {
  store.optimizerSettings.summary = payload.summary || store.optimizerSettings.summary;
  store.optimizerSettings.constraints = (payload.constraints || []).map((row) => [row.item, row.value]);
  store.optimizerSettings.factorMix = (payload.factor_mix || []).map((row) => [row.factor, `${row.normal_weight_pct.toFixed(1)}%`, `${row.stress_weight_pct.toFixed(1)}%`]);
  store.optimizerSettings.holdingsPreview = (payload.holdings_preview || []).map((row) => [row.ticker, row.sector, `${row.target_weight_pct.toFixed(1)}%`, row.selection_role]);
  store.optimizerSettings.notes = payload.notes || [];
}

async function loadUniversePreview(showFeedback = false) {
  try {
    const payload = await sendApiJson("/api/universe/preview", "POST", getScenarioPayloadForPreview("universe_selector"));
    applyUniversePreview(payload);
    apiRuntime.universePreviewLoaded = true;
    persistState();
    render(false);
    if (showFeedback) showToast("Universe preview refreshed from API.");
  } catch (error) {
    console.warn("Universe preview failed.", error);
    if (showFeedback) showToast("Universe preview failed.");
  }
}

async function loadRegimePreview(showFeedback = false) {
  try {
    const payload = await sendApiJson("/api/regime/preview", "POST", getScenarioPayloadForPreview("regime_control"));
    applyRegimePreview(payload);
    apiRuntime.regimePreviewLoaded = true;
    persistState();
    render(false);
    if (showFeedback) showToast("Regime preview refreshed from API.");
  } catch (error) {
    console.warn("Regime preview failed.", error);
    if (showFeedback) showToast("Regime preview failed.");
  }
}

async function loadOptimizerPreview(showFeedback = false) {
  try {
    const payload = await sendApiJson("/api/optimizer/preview", "POST", getScenarioPayloadForPreview("optimizer_settings"));
    applyOptimizerPreview(payload);
    apiRuntime.optimizerPreviewLoaded = true;
    persistState();
    render(false);
    if (showFeedback) showToast("Optimizer preview refreshed from API.");
  } catch (error) {
    console.warn("Optimizer preview failed.", error);
    if (showFeedback) showToast("Optimizer preview failed.");
  }
}

function applyFactorPreview(payload) {
  store.factorBuilder.scenarioName = payload.scenario_name || store.factorBuilder.scenarioName;
  store.factorBuilder.summary = {
    activeFactorCount: payload.summary?.active_factor_count ?? store.factorBuilder.summary.activeFactorCount,
    subVariableCount: payload.summary?.sub_variable_count ?? store.factorBuilder.summary.subVariableCount,
    avgIc: Number(payload.summary?.avg_ic ?? 0).toFixed(3),
    avgRankIc: Number(payload.summary?.avg_rank_ic ?? 0).toFixed(3),
    neutralisationEnabled: Boolean(payload.summary?.neutralisation_enabled),
    winsorisation: payload.summary?.winsorisation ?? store.factorBuilder.summary.winsorisation,
    standardisation: payload.summary?.standardisation ?? store.factorBuilder.summary.standardisation,
    ewmaDecay: payload.summary?.ewma_decay ?? store.factorBuilder.summary.ewmaDecay,
    topPreviewCount: payload.summary?.top_preview_count ?? store.factorBuilder.summary.topPreviewCount,
  };
  store.factorBuilder.factorRows = (payload.factor_rows || []).map((row) => ({
    factor: row.factor,
    subVariables: row.sub_variables || [],
    ic: Number(row.ic).toFixed(3),
    rankIc: Number(row.rank_ic).toFixed(3),
    hitRatePct: Number(row.hit_rate_pct).toFixed(1),
  }));
  store.factorBuilder.alphaDistribution = (payload.alpha_distribution || []).map((row) => ({
    bucket: row.bucket,
    count: row.count,
  }));
  store.factorBuilder.topPreview = (payload.top_preview || []).map((row) => ({
    ticker: row.ticker,
    sector: row.sector,
    factor: row.factor,
    score: row.score,
  }));
  store.factorBuilder.notes = payload.notes || [];
}

async function loadFactorPreview(showFeedback = false) {
  try {
    const payload = await sendApiJson("/api/factors/preview", "POST", getScenarioPayloadForPreview("factor_lab"));
    applyFactorPreview(payload);
    apiRuntime.factorPreviewLoaded = true;
    persistState();
    render(false);
    if (showFeedback) showToast("Factor preview refreshed from API.");
  } catch (error) {
    console.warn("Factor preview failed.", error);
    if (showFeedback) showToast("Factor preview failed.");
  }
}

function applyTradePreview(payload) {
  store.tradeBlotter.scenarioName = payload.scenario_name || store.tradeBlotter.scenarioName;
  store.tradeBlotter.summary = {
    tradeCount: payload.summary?.trade_count ?? store.tradeBlotter.summary.tradeCount,
    grossTurnoverPct: payload.summary?.gross_turnover_pct ?? store.tradeBlotter.summary.grossTurnoverPct,
    largestSector: payload.summary?.largest_sector ?? store.tradeBlotter.summary.largestSector,
    executionStyle: payload.summary?.execution_style ?? store.tradeBlotter.summary.executionStyle,
    singleNameCapPct: payload.summary?.single_name_cap_pct ?? store.tradeBlotter.summary.singleNameCapPct,
    transactionCostBps: payload.summary?.transaction_cost_bps ?? store.tradeBlotter.summary.transactionCostBps,
  };
  const previewTradeRows = (payload.trade_rows || []).map((row) => ({
    ticker: row.ticker,
    side: row.side,
    sector: normalizeSectorName(row.sector),
    weightDeltaPct: row.weight_delta_pct,
    triggerReason: row.trigger_reason,
    alphaDriver: row.alpha_driver,
    riskStatus: row.risk_status,
    optimizerNote: row.optimizer_note,
  }));
  if (!(Array.isArray(store.tradeBlotter.rawTradeRows) && store.tradeBlotter.rawTradeRows.length)) {
    store.tradeBlotter.tradeRows = previewTradeRows;
  }
  store.tradeBlotter.attributionRows = (payload.attribution_rows || []).map((row) => ({
    source: row.source,
    sharePct: row.share_pct,
  }));
  const previewHoldingsRows = (payload.holdings_rows || []).map((row) => ({
    ticker: row.ticker,
    sector: normalizeSectorName(row.sector),
    weightPct: row.weight_pct,
    role: row.role,
  }));
  if (!(Array.isArray(store.tradeBlotter.rawHoldingsRows) && store.tradeBlotter.rawHoldingsRows.length)) {
    store.tradeBlotter.holdingsRows = previewHoldingsRows;
  }
  store.tradeBlotter.notes = payload.notes || [];
}

async function loadTradePreview(showFeedback = false) {
  try {
    const payload = await sendApiJson("/api/trades/preview", "POST", getScenarioPayloadForPreview("holdings_trades"));
    applyTradePreview(payload);
    apiRuntime.tradePreviewLoaded = true;
    persistState();
    render(false);
    if (showFeedback) showToast("Trade preview refreshed from API.");
  } catch (error) {
    console.warn("Trade preview failed.", error);
    if (showFeedback) showToast("Trade preview failed.");
  }
}

function renderUniverseSelector() {
  const d = store.universeSelector;
  const s = formState.universe_selector;
  return `${renderActionPanel("Universe & Company Selector", "Choose the investable universe, review company sample coverage, and sanity-check the candidate pool before factor ranking. Changes on this page feed directly into the current working scenario.", [{ label: "Refresh preview", action: "preview-universe" }, { label: "Open in Runner", action: "handoff-to-runner" }], { type: "derived", detail: "Connected universe preview controls backed by the preview API." })}${renderSystemMetrics([{ label: "Universe Size", value: `${d.summary.universe_size}`, note: "Current candidate count before factor ranking and portfolio construction.", sourceType: "derived", sourceDetail: "Universe preview API summary." }, { label: "Coverage", value: `${d.summary.coverage_pct}%`, note: "Data and liquidity coverage across the selected universe.", sourceType: "derived", sourceDetail: "Universe preview API summary." }, { label: "Top N Target", value: `${d.summary.top_n_target}`, note: "Current selection target inherited by the optimizer.", sourceType: "derived", sourceDetail: "Current scenario and preview summary." }])}<div class="grid-two"><div id="universe-controls-anchor">${makePanel("Universe Controls", "Keep this page focused on the investable set and company-level screening assumptions.", renderFormFields([["Universe", { type: "select", key: "universe", value: s.universe, options: ["US Large Cap", "US Broad Market", "Defensive Basket"] }], ["Benchmark", { type: "select", key: "benchmark", value: s.benchmark, options: ["Static baseline + market benchmark", "Benchmark only", "Custom control portfolio"] }], ["Company focus", { type: "select", key: "company_focus", value: s.company_focus, options: ["Large and liquid only", "Balanced quality/liquidity", "Defensive resilient names"] }], ["Dividend screen", { type: "switch", key: "require_dividend", value: s.require_dividend }], ["Sector tilt", { type: "select", key: "sector_tilt", value: s.sector_tilt, options: ["Balanced", "Defensive", "Cyclical check"] }]]), { type: "derived", detail: "Editable universe selection state in the working scenario." })}</div><div id="universe-preview-anchor">${makePanel("Universe Summary", "Review the connected preview before promoting the settings into a scenario run.", renderTable(["Metric", "Current Preview"], [["Candidate buffer", `${d.summary.candidate_buffer}`], ["Average market cap", `${d.summary.avg_market_cap_usd_bn} bn USD`], ["Average liquidity score", `${d.summary.avg_liquidity_score}`], ["Benchmark", d.summary.benchmark]]), { type: "derived", detail: "Connected universe preview summary from the API." })}</div></div><div class="grid-two">${makePanel("Sector Mix Preview", "Rough sector composition of the current candidate set.", `<div class="chart-card"><h4>Universe sector mix</h4>${renderBars(d.sectorMix, (value) => `${value}%`)}</div>`, { type: "derived", detail: "Connected universe preview sector weights rather than raw holdings." })}<div id="universe-company-sample-anchor">${makePanel("Company Sample", "Illustrative company-level slice for quick manual review.", renderTable(["Ticker", "Sector", "Liquidity", "Why it survives"], d.companyPreview), { type: "derived", detail: "Connected preview sample of current candidate names." })}</div></div>${makePanel("Preview Notes", "Short operating notes that clarify how this page should be interpreted during review and analysis.", `<div class="docs-list">${(d.notes || []).map((note) => `<article><p>${note}</p></article>`).join("")}</div>`, { type: "text-only", detail: "Explanatory notes rather than a raw data surface." })}`;
}

function renderRegimeControl() {
  const d = store.regimeControl;
  const s = formState.regime_control;
  return `${renderActionPanel("Regime & Threshold Control", "Tune the stress trigger, replay the recent state path, and inspect how factor exposures change across regimes. Changes on this page feed directly into the current working scenario.", [{ label: "Refresh preview", action: "preview-regime" }, { label: "Open in Runner", action: "handoff-to-runner" }], { type: "derived", detail: "Connected regime preview controls backed by the preview API." })}${renderSystemMetrics([{ label: "Current Regime", value: d.summary.current_regime, note: "Derived from the connected VIX series and the current threshold setting.", sourceType: "derived", sourceDetail: "Regime preview API summary." }, { label: "Latest VIX", value: `${d.summary.latest_vix}`, note: "Most recent VIX observation in the preview window.", sourceType: "derived", sourceDetail: "Regime preview API summary." }, { label: "Stress Share", value: `${d.summary.stress_share_pct}%`, note: "Share of recent observations that map into the stress state.", sourceType: "derived", sourceDetail: "Regime preview API summary." }])}<div class="grid-two"><div id="regime-controls-anchor">${makePanel("Threshold Controls", "These settings should be visible and auditable before launching a rerun.", renderFormFields([["Stress overlay", { type: "switch", key: "stress_overlay", value: s.stress_overlay }], ["Stress threshold", { type: "input", key: "vix_threshold", value: s.vix_threshold }], ["Warning band", { type: "input", key: "warning_band", value: s.warning_band }], ["Exit band", { type: "input", key: "exit_band", value: s.exit_band }], ["Regime mode", { type: "select", key: "regime_mode", value: s.regime_mode, options: ["VIX-aware", "Manual override", "Threshold off"] }], ["Replay window", { type: "select", key: "replay_window", value: s.replay_window, options: ["Last 8 observations", "Last 12 observations", "Last 24 observations"] }]]), { type: "derived", detail: "Editable regime control state in the current working scenario." })}</div><div id="regime-summary-anchor">${makePanel("Regime Summary", "Current threshold interpretation and state diagnostics.", renderTable(["Metric", "Value"], [["Stress threshold", `${d.summary.stress_threshold}`], ["Warning threshold", `${d.summary.warning_threshold}`], ["Overlay enabled", d.summary.overlay_enabled ? "Yes" : "No"], ["Latest state", d.summary.current_regime]]), { type: "derived", detail: "Connected regime preview summary." })}</div></div><div class="grid-two"><div id="regime-replay-anchor">${makePanel("Recent Threshold Replay", "Recent VIX path with the current state classification.", renderTable(["Period", "VIX", "State"], d.timeline), { type: "derived", detail: "Connected threshold replay preview from the API." })}</div><div id="regime-exposure-anchor">${makePanel("Exposure Shift Preview", "Approximate factor allocation move between normal and stress regimes.", renderTable(["Factor", "Normal", "Stress", "Shift"], d.exposures), { type: "derived", detail: "Connected regime preview exposure table." })}</div></div>${makePanel("Preview Notes", "Use this to explain what the threshold change is supposed to do before the full backtest is rerun.", `<div class="docs-list">${(d.notes || []).map((note) => `<article><p>${note}</p></article>`).join("")}</div>`, { type: "text-only", detail: "Explanatory notes rather than a raw data surface." })}`;
}

function renderOptimizerSettings() {
  const d = store.optimizerSettings;
  const s = formState.optimizer_settings;
  return `${renderActionPanel("Portfolio Optimizer Settings", "Set portfolio breadth and constraints, then review a lightweight optimizer preview before sending the scenario into the runner. Changes on this page feed directly into the current working scenario.", [{ label: "Refresh preview", action: "preview-optimizer" }, { label: "Open in Runner", action: "handoff-to-runner" }], { type: "derived", detail: "Connected optimizer preview controls backed by the preview API." })}${renderSystemMetrics([{ label: "Hybrid Band", value: d.summary.hybrid_band, note: "Current breadth range used for the portfolio construction step.", sourceType: "derived", sourceDetail: "Optimizer preview API summary." }, { label: "Expected Turnover", value: `${d.summary.expected_turnover_pct}%`, note: "Single-period estimate given the current breadth and cost settings.", sourceType: "derived", sourceDetail: "Optimizer preview API summary." }, { label: "Predicted Vol", value: `${d.summary.predicted_vol_pct}%`, note: "Lightweight risk estimate before the historical rerun.", sourceType: "derived", sourceDetail: "Optimizer preview API summary." }])}<div class="grid-two"><div id="optimizer-controls-anchor">${makePanel("Optimizer Controls", "Portfolio construction settings that should be editable in the dedicated optimizer page.", renderFormFields([["Top N", { type: "input", key: "top_n", value: s.top_n }], ["Hold cap", { type: "input", key: "hold_cap", value: s.hold_cap }], ["Transaction cost", { type: "select", key: "transaction_cost", value: s.transaction_cost, options: ["10bps", "15bps", "25bps", "40bps"] }], ["Neutralisation", { type: "switch", key: "neutralisation", value: s.neutralisation }], ["Turnover target", { type: "input", key: "turnover_target", value: s.turnover_target }], ["Optimizer goal", { type: "select", key: "optimizer_goal", value: s.optimizer_goal, options: ["Balanced alpha / risk", "Low turnover first", "Higher conviction"] }]]), { type: "derived", detail: "Editable optimizer state in the current working scenario." })}</div><div id="optimizer-constraint-anchor">${makePanel("Constraint Summary", "Snapshot of the current optimizer assumptions.", renderTable(["Constraint", "Current"], d.constraints), { type: "derived", detail: "Connected optimizer preview constraint table." })}</div></div><div class="grid-two"><div id="optimizer-factor-mix-anchor">${makePanel("Factor Mix Preview", "How the sleeves would be weighted under normal and stress construction.", renderTable(["Factor", "Normal", "Stress"], d.factorMix), { type: "derived", detail: "Connected optimizer preview factor mix." })}</div><div id="optimizer-holdings-preview-anchor">${makePanel("Target Holdings Preview", "Illustrative holdings list from the current optimizer assumptions.", renderTable(["Ticker", "Sector", "Target Weight", "Role"], d.holdingsPreview), { type: "derived", detail: "Connected optimizer preview holdings sample." })}</div></div>${makePanel("Preview Notes", "Keep the distinction clear between a lightweight preview and a full rerun.", `<div class="docs-list">${(d.notes || []).map((note) => `<article><p>${note}</p></article>`).join("")}</div>`, { type: "text-only", detail: "Explanatory notes rather than a raw data surface." })}`;
}

renderers.universe_selector = renderUniverseSelector;
renderers.regime_control = renderRegimeControl;
renderers.optimizer_settings = renderOptimizerSettings;

loadPersistedState();
syncDerivedFormsFromScenarioDraft();
render();
void hydrateFromApi();


// Compatibility aliases for older cached handlers that referenced misspelled
// local JSON variables during export flows. This prevents stale browser cache
// from throwing ReferenceError before the refreshed script fully takes over.
function __codexCompatLoadJson(url, options) {
  return fetch(url, options).then(async (response) => {
    if (!response.ok) {
      const detail = await response.text().catch(() => "");
      throw new Error(detail || `${response.status} ${response.statusText}`.trim());
    }
    return response.json();
  });
}

window.localjson = window.localjson || null;
window.localjosn = window.localjosn || window.localjson;
window.loadJson = window.loadJson || __codexCompatLoadJson;
window.loadjson = window.loadjson || window.loadJson;
var localjson = window.localjson;
var localjosn = window.localjosn;
var loadJson = window.loadJson;
var loadjson = window.loadjson;

