import type { ValuationResponse, ValuationView } from "../types/financial";

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

function viewClass(view: ValuationView): string {
  if (view.verdict === "undervalued") return "upside";
  if (view.verdict === "overvalued") return "downside";
  return "";
}

export function ValuationSummary({ valuation }: ValuationSummaryProps) {
  const { bear, base, bull, current_price, dcf_view, pe_view, forward_eps_metadata } = valuation;
  const views = [dcf_view, pe_view];

  return (
    <div className="valuation-summary">
      <h3>Valuation Summary</h3>

      <div className="valuation-framework-note">
        DCF and Forward P/E are shown as separate valuation frameworks. The app no longer averages them into one blended target.
      </div>

      <div className="valuation-view-grid">
        {views.map((view) => (
          <div key={view.methodology} className="valuation-view-card">
            <div className="valuation-view-header">
              <div>
                <div className="valuation-view-kicker">{view.methodology.replace(/_/g, " ")}</div>
                <h4>{view.label}</h4>
              </div>
              <div className={`valuation-view-verdict ${viewClass(view)}`}>
                {view.verdict ? view.verdict.replace(/_/g, " ") : "N/A"}
              </div>
            </div>

            <div className="valuation-view-base">
              <span>Base</span>
              <strong>{money(view.base_value)}</strong>
              <em className={viewClass(view)}>{upside(view.upside_pct)} vs ${current_price.toFixed(2)}</em>
            </div>

            <div className="valuation-range-row">
              <div>
                <span>Bear</span>
                <strong>{money(view.bear_value)}</strong>
              </div>
              <div>
                <span>Bull</span>
                <strong>{money(view.bull_value)}</strong>
              </div>
            </div>

            <ul className="valuation-view-notes">
              {view.notes.map((note) => (
                <li key={note}>{note}</li>
              ))}
            </ul>
          </div>
        ))}
      </div>

      {forward_eps_metadata && (
        <div className="forward-eps-callout">
          <div className="forward-eps-title">Forward EPS Basis</div>
          <div className="forward-eps-grid">
            <div>
              <span>Basis</span>
              <strong>{forward_eps_metadata.basis.replace(/_/g, " ")}</strong>
            </div>
            <div>
              <span>Period</span>
              <strong>{forward_eps_metadata.period ?? "N/A"}</strong>
            </div>
            <div>
              <span>FY End</span>
              <strong>{forward_eps_metadata.fiscal_year_end ?? "N/A"}</strong>
            </div>
            <div>
              <span>EPS</span>
              <strong>{money(forward_eps_metadata.eps)}</strong>
            </div>
            <div>
              <span>Source</span>
              <strong>{forward_eps_metadata.source?.replace(/_/g, " ") ?? "N/A"}</strong>
            </div>
            <div>
              <span>As of</span>
              <strong>{forward_eps_metadata.as_of_date ?? "N/A"}</strong>
            </div>
          </div>
        </div>
      )}

      <div className="scenario-cards split-scenario-cards">
        {[bear, base, bull].map((s) => (
          <div key={s.label} className={`scenario-card scenario-${s.label}`}>
            <div className="scenario-label">{s.label}</div>
            <div className="scenario-breakdown">
              <div className="breakdown-row">
                <span className="breakdown-label">DCF value</span>
                <span className="breakdown-value">{money(s.dcf.per_share_value)}</span>
              </div>
              <div className="breakdown-row">
                <span className="breakdown-label">Forward P/E value</span>
                <span className="breakdown-value">{money(s.multiples.forward_pe_value)}</span>
              </div>
              {s.multiples.pe_multiple && (
                <div className="breakdown-row">
                  <span className="breakdown-label">P/E multiple</span>
                  <span className="breakdown-value">{s.multiples.pe_multiple.toFixed(1)}x</span>
                </div>
              )}
            </div>
            <div className="scenario-assumptions">
              <div>Rev growth: {pct(s.dcf.assumptions.revenue_growth_rate)}</div>
              <div>FCF margin: {pct(s.dcf.assumptions.fcf_margin)}</div>
              <div>WACC: {pct(s.dcf.assumptions.discount_rate)}</div>
              <div>Terminal g: {pct(s.dcf.assumptions.terminal_growth_rate)}</div>
            </div>
          </div>
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
