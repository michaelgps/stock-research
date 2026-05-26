import type { FiscalYearValuationWindow, ValuationResponse } from "../types/financial";

interface ValuationSummaryProps {
  valuation: ValuationResponse;
}

function pct(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

function money(value: number | null | undefined): string {
  return value == null ? "N/A" : `$${value.toFixed(2)}`;
}

function upside(value: number | null): string {
  if (value == null) return "N/A";
  const pctValue = value * 100;
  return `${pctValue >= 0 ? "+" : ""}${pctValue.toFixed(1)}%`;
}

function verdictClass(verdict: string | null): string {
  if (verdict === "undervalued") return "upside";
  if (verdict === "overvalued") return "downside";
  return "";
}

interface ValuationWindowCard {
  title: string;
  label: string;
  fyWindow: FiscalYearValuationWindow | undefined;
  badgeClass: string;
}

function ValuationWindow({ title, label, fyWindow, badgeClass, currentPrice }: ValuationWindowCard & { currentPrice: number }) {
  const baseScenario = fyWindow?.pe_scenarios.find((scenario) => scenario.label === "base");

  return (
    <div className="valuation-view-card">
      <div className="valuation-view-header">
        <div>
          <div className="valuation-view-kicker">fiscal-year valuation window</div>
          <h4>{title}</h4>
          <div className="valuation-period-stack">
            <div className={`valuation-time-badge ${badgeClass}`}>
              Valuation period: FY{fyWindow?.fiscal_year ?? "N/A"}
              {fyWindow?.fiscal_year_end ? ` ending ${fyWindow.fiscal_year_end}` : ""} ({fyWindow?.time_distance_label ?? "date unknown"})
            </div>
          </div>
        </div>
        <div className={`valuation-view-verdict ${verdictClass(baseScenario?.verdict ?? null)}`}>
          {baseScenario?.verdict ? baseScenario.verdict.replace(/_/g, " ") : "N/A"}
        </div>
      </div>

      <div className="valuation-window-values">
        <div className="valuation-window-primary">
          <span>{label} Forward P/E target</span>
          <strong>{money(baseScenario?.forward_pe_value)}</strong>
          <div className="valuation-formula">
            <b>EPS {money(fyWindow?.forward_eps)}</b>
            <span>x</span>
            <b>{baseScenario?.pe_multiple != null ? `${baseScenario.pe_multiple.toFixed(1)}x` : "N/A"} P/E</b>
            <span>=</span>
            <b>{money(baseScenario?.forward_pe_value)}</b>
          </div>
          <em className={verdictClass(baseScenario?.verdict ?? null)}>
            {upside(baseScenario?.upside_pct ?? null)} vs ${currentPrice.toFixed(2)}
          </em>
        </div>
        <div className="valuation-window-secondary">
          <span>DCF rolled-forward value</span>
          <strong>{money(fyWindow?.dcf_rolled_forward_value)}</strong>
          <em className={verdictClass(fyWindow?.dcf_rolled_forward_verdict ?? null)}>
            present DCF {money(fyWindow?.dcf_present_value)} compounded at {fyWindow?.discount_rate_used != null ? pct(fyWindow.discount_rate_used) : "N/A"}
          </em>
        </div>
      </div>

      <div className="scenario-cards scenario-cards-inline">
        {(fyWindow?.pe_scenarios ?? []).map((scenario) => (
          <div key={scenario.label} className={`scenario-card scenario-${scenario.label}`}>
            <div className="scenario-label">{scenario.label}</div>
            <div className="scenario-breakdown">
              <div className="breakdown-row">
                <span className="breakdown-label">Historical P/E percentile</span>
                <span className="breakdown-value">{scenario.percentile}</span>
              </div>
              <div className="breakdown-row">
                <span className="breakdown-label">P/E multiple</span>
                <span className="breakdown-value">{scenario.pe_multiple != null ? `${scenario.pe_multiple.toFixed(1)}x` : "N/A"}</span>
              </div>
              <div className="breakdown-row">
                <span className="breakdown-label">Value</span>
                <span className="breakdown-value">{money(scenario.forward_pe_value)}</span>
              </div>
            </div>
          </div>
        ))}
      </div>

      <ul className="valuation-view-notes">
        <li>Forward P/E and DCF are aligned to the same fiscal-year end date.</li>
        <li>DCF rolled-forward uses the base DCF WACC; it is not blended with P/E.</li>
      </ul>
    </div>
  );
}

export function ValuationSummary({ valuation }: ValuationSummaryProps) {
  const { current_price, fiscal_year_valuation_windows } = valuation;
  const valuationWindowCards: ValuationWindowCard[] = [
    {
      title: "Forward P/E Market Multiple",
      label: "Next FY",
      fyWindow: fiscal_year_valuation_windows[0],
      badgeClass: "",
    },
    {
      title: "Following FY P/E Market Multiple",
      label: "Following FY",
      fyWindow: fiscal_year_valuation_windows[1],
      badgeClass: "secondary-time-badge",
    },
  ];

  return (
    <div className="valuation-summary">
      <h3>Valuation Summary</h3>

      <div className="valuation-framework-note">
        Forward P/E is shown by fiscal-year valuation period. Each window uses the ticker's 5-year historical P/E percentiles: P25, P50, and P75.
      </div>

      <div className="valuation-window-stack">
        {valuationWindowCards.map((card) => (
          <ValuationWindow key={card.label} {...card} currentPrice={current_price} />
        ))}
      </div>

      {Object.keys(valuation.data_quality).length > 0 && (
        <details className="data-quality">
          <summary>Data Quality Notes</summary>
          <div className="quality-grid">
            {Object.entries(valuation.data_quality).map(([key, value]) => (
              <div key={key} className="quality-item">
                <span className="quality-key">{key.replace(/_/g, " ")}</span>
                <span className="quality-value">{String(value)}</span>
              </div>
            ))}
          </div>
        </details>
      )}

      {Object.keys(valuation.signal_adjustments).length > 0 && (
        <details className="signal-adjustments">
          <summary>Signal Adjustments (LLM)</summary>
          <div className="quality-grid">
            {Object.entries(valuation.signal_adjustments).map(([key, value]) => (
              <div key={key} className="quality-item">
                <span className="quality-key">{key.replace(/_/g, " ")}</span>
                <span className="quality-value">{String(value)}</span>
              </div>
            ))}
          </div>
        </details>
      )}
    </div>
  );
}
