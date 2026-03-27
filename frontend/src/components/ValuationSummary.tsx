import type { ValuationResponse } from "../types/financial";

interface ValuationSummaryProps {
  valuation: ValuationResponse;
}

function pct(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

export function ValuationSummary({ valuation }: ValuationSummaryProps) {
  const { bear, base, bull, current_price } = valuation;

  // Price range for the visual bar
  const allPrices = [
    bear.blended_per_share,
    base.blended_per_share,
    bull.blended_per_share,
    current_price,
  ];
  const min = Math.min(...allPrices) * 0.85;
  const max = Math.max(...allPrices) * 1.1;
  const range = max - min;

  const toPercent = (price: number) =>
    Math.max(0, Math.min(100, ((price - min) / range) * 100));

  const bearPct = toPercent(bear.blended_per_share);
  const basePct = toPercent(base.blended_per_share);
  const bullPct = toPercent(bull.blended_per_share);
  const currentPct = toPercent(current_price);

  // Upside/downside from current price
  const baseUpside = ((base.blended_per_share - current_price) / current_price) * 100;

  return (
    <div className="valuation-summary">
      <h3>Valuation Summary</h3>

      {/* Price target bar */}
      <div className="price-bar-container">
        <div className="price-bar">
          <div
            className="price-bar-range"
            style={{ left: `${bearPct}%`, width: `${bullPct - bearPct}%` }}
          />
          <div
            className="price-marker price-marker-bear"
            style={{ left: `${bearPct}%` }}
            title={`Bear: $${bear.blended_per_share}`}
          />
          <div
            className="price-marker price-marker-base"
            style={{ left: `${basePct}%` }}
            title={`Base: $${base.blended_per_share}`}
          />
          <div
            className="price-marker price-marker-bull"
            style={{ left: `${bullPct}%` }}
            title={`Bull: $${bull.blended_per_share}`}
          />
          <div
            className="price-marker price-marker-current"
            style={{ left: `${currentPct}%` }}
            title={`Current: $${current_price}`}
          />
        </div>
        <div className="price-bar-labels">
          <span style={{ left: `${bearPct}%` }} className="bar-label bar-label-bear">
            Bear ${bear.blended_per_share}
          </span>
          <span style={{ left: `${basePct}%` }} className="bar-label bar-label-base">
            Base ${base.blended_per_share}
          </span>
          <span style={{ left: `${bullPct}%` }} className="bar-label bar-label-bull">
            Bull ${bull.blended_per_share}
          </span>
          <span style={{ left: `${currentPct}%` }} className="bar-label bar-label-current">
            Now ${current_price}
          </span>
        </div>
      </div>

      <div className="valuation-verdict">
        Base target: <strong>${base.blended_per_share}</strong>
        {" — "}
        <span className={baseUpside >= 0 ? "upside" : "downside"}>
          {baseUpside >= 0 ? "+" : ""}{baseUpside.toFixed(1)}%
        </span>
        {" vs current $"}{current_price}
      </div>

      {/* Scenario cards */}
      <div className="scenario-cards">
        {[bear, base, bull].map((s) => (
          <div key={s.label} className={`scenario-card scenario-${s.label}`}>
            <div className="scenario-label">{s.label}</div>
            <div className="scenario-blended">${s.blended_per_share}</div>
            <div className="scenario-breakdown">
              <div className="breakdown-row">
                <span className="breakdown-label">DCF</span>
                <span className="breakdown-value">${s.dcf.per_share_value.toFixed(1)}</span>
              </div>
              <div className="breakdown-row">
                <span className="breakdown-label">Fwd P/E</span>
                <span className="breakdown-value">
                  {s.multiples.forward_pe_value
                    ? `$${s.multiples.forward_pe_value}`
                    : "N/A"}
                </span>
              </div>
              {s.multiples.pe_multiple && (
                <div className="breakdown-row">
                  <span className="breakdown-label">P/E mult</span>
                  <span className="breakdown-value">{s.multiples.pe_multiple.toFixed(1)}x</span>
                </div>
              )}
              {s.label === "base" && s.multiples.justified_pe && (
                <div className="breakdown-row">
                  <span className="breakdown-label">Justified P/E</span>
                  <span className="breakdown-value">{s.multiples.justified_pe.toFixed(1)}x</span>
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

      {/* Data quality notes */}
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

      {/* Signal adjustments */}
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
