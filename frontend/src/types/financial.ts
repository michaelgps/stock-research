export interface CompanyInfo {
  ticker: string;
  name: string | null;
  sector: string | null;
  industry: string | null;
  market_cap: number | null;
  current_price: number | null;
  shares_outstanding: number | null;
}

export interface FinancialStatement {
  period: string;
  fiscal_year: number;
  fiscal_quarter: number | null;
  date: string;
  revenue: number | null;
  cost_of_revenue: number | null;
  gross_profit: number | null;
  operating_income: number | null;
  net_income: number | null;
  ebitda: number | null;
  cash_from_operations: number | null;
  capital_expenditures: number | null;
  free_cash_flow: number | null;
  total_cash: number | null;
  total_debt: number | null;
  total_assets: number | null;
  total_equity: number | null;
  diluted_shares: number | null;
  source: string | null;
}

export interface AnalystEstimate {
  period: string;
  revenue_estimate: number | null;
  eps_estimate: number | null;
  revenue_growth_estimate: number | null;
  buy_count: number | null;
  hold_count: number | null;
  sell_count: number | null;
  target_price: number | null;
  source: string | null;
}

export interface FinancialDataResponse {
  company: CompanyInfo;
  annual_statements: FinancialStatement[];
  quarterly_statements: FinancialStatement[];
  analyst_estimates: AnalystEstimate[];
}

// --- Valuation types (Phase 3 output) ---

export interface ScenarioAssumptions {
  revenue_growth_rate: number;
  fcf_margin: number;
  terminal_growth_rate: number;
  discount_rate: number;
  projection_years: number;
}

export interface DCFResult {
  projected_fcf: number[];
  terminal_value: number;
  present_value_fcfs: number;
  present_value_terminal: number;
  enterprise_value: number;
  equity_value: number;
  per_share_value: number;
  assumptions: ScenarioAssumptions;
}

export interface MultiplesResult {
  forward_pe_value: number | null;
  forward_eps: number | null;
  pe_multiple: number | null;
  justified_pe: number | null;
  details: Record<string, unknown>;
}

export interface PeerPEData {
  ticker: string;
  price: number;
  forward_eps: number;
  forward_pe: number;
  market_cap: number | null;
  eps_growth: number | null;
}

export interface PeerComparison {
  peers: PeerPEData[];
  median_pe: number | null;
  cap_weighted_pe: number | null;
  median_peg: number | null;
  growth_adjusted_pe: number | null;
}

export interface ScenarioResult {
  label: string;
  dcf: DCFResult;
  multiples: MultiplesResult;
  blended_per_share: number | null;
}

export interface ValuationView {
  label: string;
  methodology: string;
  bear_value: number | null;
  base_value: number | null;
  bull_value: number | null;
  upside_pct: number | null;
  verdict: string | null;
  notes: string[];
}

export interface ForwardEpsMetadata {
  basis: string;
  period: string | null;
  fiscal_year: number | null;
  fiscal_year_end: string | null;
  eps: number | null;
  source: string | null;
  as_of_date: string | null;
}

export interface ForwardYearEstimate {
  year: string;
  eps: number;
  pe_multiple: number | null;
  implied_price: number;
}

export interface FiscalYearPECase {
  label: string;
  method: string;
  pe_low: number;
  pe_mid: number;
  pe_high: number;
  value_low: number;
  value_mid: number;
  value_high: number;
  upside_low_pct: number | null;
  upside_mid_pct: number | null;
  upside_high_pct: number | null;
  verdict: string | null;
  weighted_eps_growth: number | null;
  growth_curve: string | null;
  quality_adjustment: number;
  deceleration_adjustment: number;
  uncertainty_adjustment: number;
  uncertainty_reasons: string[];
  historical_guardrail_pe: number | null;
  explanation: string;
}

export interface FiscalYearValuationWindow {
  fiscal_year: number;
  fiscal_year_end: string | null;
  valuation_date: string;
  years_from_valuation_date: number | null;
  time_distance_label: string;
  forward_eps: number;
  pe_multiple: number | null;
  forward_pe_value: number | null;
  forward_pe_upside_pct: number | null;
  forward_pe_verdict: string | null;
  pe_cases: FiscalYearPECase[];
  dcf_present_value: number | null;
  dcf_rolled_forward_value: number | null;
  dcf_rolled_forward_upside_pct: number | null;
  dcf_rolled_forward_verdict: string | null;
  discount_rate_used: number | null;
  discount_rate_source: string;
}

export interface YearlyPERange {
  fy: number;
  eps: number;
  eps_basis?: string | null;
  adjusted_eps_observations?: number | null;
  share_adjustment_factor?: number | null;
  pe_low: number;
  pe_high: number;
  pe_avg: number;
  pe_p25?: number | null;
  pe_p50?: number | null;
  pe_p75?: number | null;
  price_high: number;
  price_low: number;
}

export interface ValuationResponse {
  ticker: string;
  current_price: number;
  bear: ScenarioResult;
  base: ScenarioResult;
  bull: ScenarioResult;
  dcf_view: ValuationView;
  pe_view: ValuationView;
  forward_eps_metadata: ForwardEpsMetadata | null;
  fiscal_year_valuation_windows: FiscalYearValuationWindow[];
  forward_trend: ForwardYearEstimate[];
  historical_pe_ranges: YearlyPERange[];
  peer_comparison: PeerComparison | null;
  signal_adjustments: Record<string, unknown>;
  data_quality: Record<string, unknown>;
}
