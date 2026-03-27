import type { YearlyPERange } from "../types/financial";

interface HistoricalPEProps {
  ranges: YearlyPERange[];
}

export function HistoricalPE({ ranges }: HistoricalPEProps) {
  if (ranges.length === 0) return null;

  const sorted = [...ranges].sort((a, b) => b.fy - a.fy);

  // Find global min/max for visual bar scaling
  const globalMin = Math.min(...sorted.map((r) => r.pe_low));
  const globalMax = Math.max(...sorted.map((r) => r.pe_high));
  const span = globalMax - globalMin;
  const padMin = globalMin - span * 0.1;
  const padMax = globalMax + span * 0.1;
  const fullRange = padMax - padMin;

  const toPercent = (val: number) => ((val - padMin) / fullRange) * 100;

  return (
    <div className="historical-pe">
      <h3>Historical P/E Ranges</h3>
      <div className="pe-chart">
        {sorted.map((r) => {
          const lowPct = toPercent(r.pe_low);
          const highPct = toPercent(r.pe_high);
          const avgPct = toPercent(r.pe_avg);
          return (
            <div key={r.fy} className="pe-row">
              <span className="pe-fy">FY{r.fy}</span>
              <div className="pe-bar-wrapper">
                <div
                  className="pe-bar-range"
                  style={{ left: `${lowPct}%`, width: `${highPct - lowPct}%` }}
                >
                  <div
                    className="pe-bar-avg"
                    style={{ left: `${((avgPct - lowPct) / (highPct - lowPct)) * 100}%` }}
                  />
                </div>
              </div>
              <span className="pe-values">
                {r.pe_low.toFixed(1)}x — {r.pe_avg.toFixed(1)}x — {r.pe_high.toFixed(1)}x
              </span>
            </div>
          );
        })}
      </div>
      <div className="pe-legend">
        <span>Low</span>
        <span className="pe-legend-bar" />
        <span>Avg</span>
        <span className="pe-legend-bar" />
        <span>High</span>
      </div>

      {/* Detailed table */}
      <details className="pe-details">
        <summary>Detailed P/E Data</summary>
        <div className="table-wrapper">
          <table>
            <thead>
              <tr>
                <th>FY</th>
                <th>EPS</th>
                <th>P/E Low</th>
                <th>P/E Avg</th>
                <th>P/E High</th>
                <th>Price Low</th>
                <th>Price High</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((r) => (
                <tr key={r.fy}>
                  <td>{r.fy}</td>
                  <td>${r.eps.toFixed(2)}</td>
                  <td>{r.pe_low.toFixed(1)}x</td>
                  <td>{r.pe_avg.toFixed(1)}x</td>
                  <td>{r.pe_high.toFixed(1)}x</td>
                  <td>${r.price_low.toFixed(2)}</td>
                  <td>${r.price_high.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </div>
  );
}
