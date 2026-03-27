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
  blended_per_share: number;
}

export interface ForwardYearEstimate {
  year: string;
  eps: number;
  implied_price: number;
}

export interface YearlyPERange {
  fy: number;
  eps: number;
  pe_low: number;
  pe_high: number;
  pe_avg: number;
  price_high: number;
  price_low: number;
}

export interface ValuationResponse {
  ticker: string;
  current_price: number;
  bear: ScenarioResult;
  base: ScenarioResult;
  bull: ScenarioResult;
  forward_trend: ForwardYearEstimate[];
  historical_pe_ranges: YearlyPERange[];
  peer_comparison: PeerComparison | null;
  signal_adjustments: Record<string, unknown>;
  data_quality: Record<string, unknown>;
}
