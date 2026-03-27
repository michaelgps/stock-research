import type { ForwardYearEstimate } from "../types/financial";

interface ForwardTrendProps {
  trend: ForwardYearEstimate[];
  currentPrice: number;
  peMultiple: number | null;
}

export function ForwardTrend({ trend, currentPrice, peMultiple }: ForwardTrendProps) {
  if (trend.length === 0) return null;

  // Find max implied price for bar chart scaling
  const maxPrice = Math.max(...trend.map((t) => t.implied_price), currentPrice);

  return (
    <div className="forward-trend">
      <h3>5-Year Forward Valuation</h3>
      {peMultiple && (
        <p className="trend-subtitle">
          Based on {peMultiple.toFixed(1)}x base P/E applied to analyst EPS estimates
        </p>
      )}
      <div className="trend-chart">
        {/* Current price reference bar */}
        <div className="trend-row">
          <span className="trend-year">Now</span>
          <div className="trend-bar-wrapper">
            <div
              className="trend-bar trend-bar-current"
              style={{ width: `${(currentPrice / maxPrice) * 100}%` }}
            />
          </div>
          <span className="trend-price">${currentPrice.toFixed(0)}</span>
          <span className="trend-eps">—</span>
        </div>
        {trend.map((t) => {
          const upside = ((t.implied_price - currentPrice) / currentPrice) * 100;
          return (
            <div key={t.year} className="trend-row">
              <span className="trend-year">{t.year}</span>
              <div className="trend-bar-wrapper">
                <div
                  className="trend-bar trend-bar-future"
                  style={{ width: `${(t.implied_price / maxPrice) * 100}%` }}
                />
              </div>
              <span className="trend-price">${t.implied_price.toFixed(0)}</span>
              <span className="trend-eps">
                EPS ${t.eps.toFixed(2)}
                <span className={upside >= 0 ? "upside" : "downside"}>
                  {" "}{upside >= 0 ? "+" : ""}{upside.toFixed(0)}%
                </span>
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
