import type { CompanyInfo } from "../types/financial";

interface CompanyHeaderProps {
  company: CompanyInfo;
}

function formatNumber(value: number | null): string {
  if (value === null) return "N/A";
  if (Math.abs(value) >= 1e12) return `$${(value / 1e12).toFixed(2)}T`;
  if (Math.abs(value) >= 1e9) return `$${(value / 1e9).toFixed(2)}B`;
  if (Math.abs(value) >= 1e6) return `$${(value / 1e6).toFixed(2)}M`;
  return `$${value.toLocaleString()}`;
}

export function CompanyHeader({ company }: CompanyHeaderProps) {
  return (
    <div className="company-header">
      <h2>
        {company.ticker}
        {company.name && ` — ${company.name}`}
      </h2>
      <div className="company-meta">
        {company.sector && <span className="tag">{company.sector}</span>}
        {company.industry && <span className="tag">{company.industry}</span>}
      </div>
      <div className="company-stats">
        {company.current_price !== null && (
          <div className="stat">
            <span className="stat-label">Price</span>
            <span className="stat-value">${company.current_price.toFixed(2)}</span>
          </div>
        )}
        {company.market_cap !== null && (
          <div className="stat">
            <span className="stat-label">Market Cap</span>
            <span className="stat-value">{formatNumber(company.market_cap)}</span>
          </div>
        )}
      </div>
    </div>
  );
}
