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

function multiple(value: number | null | undefined): string {
  return value == null ? "N/A" : `${value.toFixed(1)}x`;
}

function qualityText(value: unknown): string {
  if (value == null) return "N/A";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return JSON.stringify(value);
}

function verdictClass(verdict: string | null): string {
  if (verdict === "undervalued") return "upside";
  if (verdict === "overvalued") return "downside";
  return "";
}

function caseTitle(label: string): string {
  const titles: Record<string, string> = {
    auto_base: "Base case",
    high_growth: "High growth case",
    deceleration: "Deceleration case",
    base_visibility: "Base visibility case",
    high_visibility: "High visibility case",
  };
  return titles[label] ?? label.replace(/_/g, " ");
}

interface ValuationWindowCard {
  title: string;
  fyWindow: FiscalYearValuationWindow | undefined;
  badgeClass: string;
}

function ValuationWindow({ title, fyWindow, badgeClass, currentPrice }: ValuationWindowCard & { currentPrice: number }) {
  const primaryCase = fyWindow?.pe_cases?.[0];
  const peCases = fyWindow?.pe_cases ?? [];
  const overallLow = peCases.length ? Math.min(...peCases.map((peCase) => peCase.value_low)) : null;
  const overallHigh = peCases.length ? Math.max(...peCases.map((peCase) => peCase.value_high)) : null;

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
        <div className={`valuation-view-verdict ${verdictClass(primaryCase?.verdict ?? null)}`}>
          {primaryCase?.verdict ? primaryCase.verdict.replace(/_/g, " ") : "N/A"}
        </div>
      </div>

      {peCases.length > 1 && (
        <div className="valuation-all-case-range">
          All-case P/E valuation range: {money(overallLow)} - {money(overallHigh)}
        </div>
      )}

      <p className="dcf-reference-note">
        DCF reference only: rolled-forward value {money(fyWindow?.dcf_rolled_forward_value)}
        {" "}from present DCF {money(fyWindow?.dcf_present_value)}
        {" "}compounded at {fyWindow?.discount_rate_used != null ? pct(fyWindow.discount_rate_used) : "N/A"}.
      </p>

      <div className="scenario-cards scenario-cards-inline">
        {peCases.map((peCase) => (
          <div key={peCase.label} className={`scenario-card scenario-${peCase.label}`}>
            <div className="scenario-label">{caseTitle(peCase.label)}</div>
            <div className="scenario-median-price">
              <span>Median price</span>
              <strong>{money(peCase.value_mid)}</strong>
              <em className={verdictClass(peCase.verdict ?? null)}>
                {upside(peCase.upside_mid_pct ?? null)} vs ${currentPrice.toFixed(2)}
              </em>
            </div>
            <div className="scenario-formula">
              EPS {money(fyWindow?.forward_eps)} x {peCase.pe_low.toFixed(1)}-{peCase.pe_high.toFixed(1)}x P/E =
              {" "}{money(peCase.value_low)} - {money(peCase.value_high)}
            </div>
            <div className="scenario-breakdown">
              <div className="breakdown-row">
                <span className="breakdown-label">Weighted EPS growth</span>
                <span className="breakdown-value">
                  {peCase.weighted_eps_growth != null ? pct(peCase.weighted_eps_growth) : "N/A"}
                </span>
              </div>
              <div className="breakdown-row">
                <span className="breakdown-label">Growth curve</span>
                <span className="breakdown-value">{peCase.growth_curve ?? "N/A"}</span>
              </div>
              <div className="breakdown-row">
                <span className="breakdown-label">P/E range</span>
                <span className="breakdown-value">{peCase.pe_low.toFixed(1)}-{peCase.pe_high.toFixed(1)}x</span>
              </div>
              <div className="breakdown-row">
                <span className="breakdown-label">Midpoint P/E</span>
                <span className="breakdown-value">{multiple(peCase.pe_mid)}</span>
              </div>
              <div className="breakdown-row">
                <span className="breakdown-label">Adjustments</span>
                <span className="breakdown-value">
                  Q {peCase.quality_adjustment >= 0 ? "+" : ""}{peCase.quality_adjustment.toFixed(1)} /
                  D {peCase.deceleration_adjustment.toFixed(1)} /
                  U {peCase.uncertainty_adjustment.toFixed(1)}
                </span>
              </div>
              {peCase.uncertainty_reasons.length > 0 && (
                <div className="breakdown-row breakdown-row-stack">
                  <span className="breakdown-label">Uncertainty triggers</span>
                  <span className="breakdown-value">{peCase.uncertainty_reasons.join(", ")}</span>
                </div>
              )}
              <div className="breakdown-row">
                <span className="breakdown-label">Value range</span>
                <span className="breakdown-value">{money(peCase.value_low)} - {money(peCase.value_high)}</span>
              </div>
              <div className="breakdown-row">
                <span className="breakdown-label">Midpoint value</span>
                <span className="breakdown-value">{money(peCase.value_mid)}</span>
              </div>
            </div>
          </div>
        ))}
      </div>

      <ul className="valuation-view-notes">
        <li>Forward P/E uses an automatic P/E range based on EPS growth, quality, deceleration, uncertainty, and historical guardrails.</li>
        <li>DCF rolled-forward uses the base DCF WACC; it is not blended with P/E.</li>
      </ul>
    </div>
  );
}

export function ValuationSummary({ valuation }: ValuationSummaryProps) {
  const { current_price, fiscal_year_valuation_windows, data_quality } = valuation;
  const valuationWindowCards: ValuationWindowCard[] = [
    {
      title: "Forward P/E Market Multiple",
      fyWindow: fiscal_year_valuation_windows[0],
      badgeClass: "",
    },
    {
      title: "Following FY P/E Market Multiple",
      fyWindow: fiscal_year_valuation_windows[1],
      badgeClass: "secondary-time-badge",
    },
  ];
  const hasValuationWindows = fiscal_year_valuation_windows.length > 0;
  const forwardEpsReason =
    data_quality.forward_eps_fallback_warning ??
    data_quality.forward_eps_unavailable_reason ??
    data_quality.forward_eps;

  return (
    <div className="valuation-summary">
      <h3>Valuation Summary</h3>

      <div className="valuation-framework-note">
        Forward P/E is shown by fiscal-year valuation period. The model now generates automatic P/E ranges instead of one hard-coded multiple.
      </div>

      {hasValuationWindows ? (
        <div className="valuation-window-stack">
          {valuationWindowCards
            .filter((card) => card.fyWindow)
            .map((card) => (
              <ValuationWindow key={card.title} {...card} currentPrice={current_price} />
            ))}
        </div>
      ) : (
        <div className="valuation-empty-state">
          <h4>Forward P/E valuation unavailable</h4>
          <p>
            The model could not build a fiscal-year P/E valuation window because no usable forward EPS estimate was available.
          </p>
          {forwardEpsReason != null && (
            <div className="valuation-empty-reason">
              {qualityText(forwardEpsReason)}
            </div>
          )}
          <p className="dcf-reference-note">
            DCF still runs as a reference, but for cyclical or negative-FCF companies it may be less useful than a clean forward EPS data source.
          </p>
        </div>
      )}

      {Object.keys(valuation.data_quality).length > 0 && (
        <details className="data-quality">
          <summary>Data Quality Notes</summary>
          <div className="quality-grid">
            {Object.entries(valuation.data_quality).map(([key, value]) => (
              <div key={key} className="quality-item">
                <span className="quality-key">{key.replace(/_/g, " ")}</span>
                <span className="quality-value">{qualityText(value)}</span>
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
