import type { AnalystEstimate } from "../types/financial";

interface AnalystEstimatesProps {
  estimates: AnalystEstimate[];
}

export function AnalystEstimates({ estimates }: AnalystEstimatesProps) {
  if (estimates.length === 0) {
    return null;
  }

  return (
    <div className="analyst-estimates">
      <h3>Analyst Estimates</h3>
      <div className="table-wrapper">
        <table>
          <thead>
            <tr>
              <th>Period</th>
              <th>Rev Estimate</th>
              <th>EPS Estimate</th>
              <th>Buy</th>
              <th>Hold</th>
              <th>Sell</th>
              <th>Target Price</th>
              <th>Source</th>
            </tr>
          </thead>
          <tbody>
            {estimates.map((est, i) => (
              <tr key={i}>
                <td>{est.period}</td>
                <td>{est.revenue_estimate ? `${(est.revenue_estimate / 1e9).toFixed(1)}B` : "—"}</td>
                <td>{est.eps_estimate?.toFixed(2) ?? "—"}</td>
                <td>{est.buy_count ?? "—"}</td>
                <td>{est.hold_count ?? "—"}</td>
                <td>{est.sell_count ?? "—"}</td>
                <td>{est.target_price ? `$${est.target_price.toFixed(2)}` : "—"}</td>
                <td>{est.source ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
