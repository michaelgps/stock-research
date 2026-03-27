import type { PeerComparison as PeerComparisonType } from "../types/financial";

interface PeerComparisonProps {
  peers: PeerComparisonType;
  tickerPe: number | null;
}

function formatCap(value: number | null): string {
  if (value === null) return "—";
  if (Math.abs(value) >= 1e12) return `$${(value / 1e12).toFixed(1)}T`;
  if (Math.abs(value) >= 1e9) return `$${(value / 1e9).toFixed(0)}B`;
  return `$${(value / 1e6).toFixed(0)}M`;
}

export function PeerComparison({ peers, tickerPe }: PeerComparisonProps) {
  if (!peers.peers.length) return null;

  const premium =
    tickerPe && peers.median_pe
      ? ((tickerPe - peers.median_pe) / peers.median_pe) * 100
      : null;

  return (
    <div className="peer-comparison">
      <h3>Peer Forward P/E Comparison</h3>
      {peers.median_pe && (
        <div className="peer-summary">
          <div className="peer-stat">
            <span className="peer-stat-label">Peer Median</span>
            <span className="peer-stat-value">{peers.median_pe.toFixed(1)}x</span>
          </div>
          <div className="peer-stat">
            <span className="peer-stat-label">Cap-Weighted</span>
            <span className="peer-stat-value">
              {peers.cap_weighted_pe?.toFixed(1) ?? "—"}x
            </span>
          </div>
          {tickerPe && (
            <div className="peer-stat">
              <span className="peer-stat-label">Your P/E</span>
              <span className="peer-stat-value">{tickerPe.toFixed(1)}x</span>
            </div>
          )}
          {premium !== null && (
            <div className="peer-stat">
              <span className="peer-stat-label">vs Peers</span>
              <span
                className={`peer-stat-value ${premium > 0 ? "premium-high" : "premium-low"}`}
              >
                {premium > 0 ? "+" : ""}{premium.toFixed(0)}%
              </span>
            </div>
          )}
        </div>
      )}
      {peers.growth_adjusted_pe && (
        <div className="peer-summary" style={{ marginTop: "0.5rem" }}>
          <div className="peer-stat">
            <span className="peer-stat-label">Median PEG</span>
            <span className="peer-stat-value">{peers.median_peg?.toFixed(2) ?? "—"}</span>
          </div>
          <div className="peer-stat">
            <span className="peer-stat-label">Growth-Adj P/E</span>
            <span className="peer-stat-value">{peers.growth_adjusted_pe.toFixed(1)}x</span>
          </div>
        </div>
      )}
      <div className="table-wrapper">
        <table>
          <thead>
            <tr>
              <th>Peer</th>
              <th>Price</th>
              <th>Fwd EPS</th>
              <th>Fwd P/E</th>
              <th>EPS Growth</th>
              <th>Mkt Cap</th>
            </tr>
          </thead>
          <tbody>
            {peers.peers.map((p) => (
              <tr key={p.ticker}>
                <td>{p.ticker}</td>
                <td>${p.price.toFixed(2)}</td>
                <td>${p.forward_eps.toFixed(2)}</td>
                <td>{p.forward_pe.toFixed(1)}x</td>
                <td>{p.eps_growth !== null ? `${(p.eps_growth * 100).toFixed(1)}%` : "—"}</td>
                <td>{formatCap(p.market_cap)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
