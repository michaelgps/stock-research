import type { FinancialStatement } from "../types/financial";

interface FinancialTableProps {
  statements: FinancialStatement[];
  title: string;
}

function formatVal(value: number | null): string {
  if (value === null) return "—";
  if (Math.abs(value) >= 1e9) return `${(value / 1e9).toFixed(2)}B`;
  if (Math.abs(value) >= 1e6) return `${(value / 1e6).toFixed(1)}M`;
  if (Math.abs(value) >= 1e3) return `${(value / 1e3).toFixed(1)}K`;
  return value.toLocaleString();
}

const ROWS: { label: string; key: keyof FinancialStatement }[] = [
  { label: "Revenue", key: "revenue" },
  { label: "Gross Profit", key: "gross_profit" },
  { label: "Operating Income", key: "operating_income" },
  { label: "Net Income", key: "net_income" },
  { label: "EBITDA", key: "ebitda" },
  { label: "Cash from Ops", key: "cash_from_operations" },
  { label: "CapEx", key: "capital_expenditures" },
  { label: "Free Cash Flow", key: "free_cash_flow" },
  { label: "Total Cash", key: "total_cash" },
  { label: "Total Debt", key: "total_debt" },
  { label: "Total Assets", key: "total_assets" },
  { label: "Total Equity", key: "total_equity" },
  { label: "Diluted Shares", key: "diluted_shares" },
];

export function FinancialTable({ statements, title }: FinancialTableProps) {
  if (statements.length === 0) {
    return null;
  }

  // Show most recent 5 years, sorted newest first
  const sorted = [...statements].sort((a, b) => b.fiscal_year - a.fiscal_year).slice(0, 5);

  return (
    <div className="financial-table">
      <h3>{title}</h3>
      <div className="table-wrapper">
        <table>
          <thead>
            <tr>
              <th>Metric</th>
              {sorted.map((s) => (
                <th key={s.date}>{s.fiscal_year}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {ROWS.map((row) => (
              <tr key={row.key}>
                <td className="metric-label">{row.label}</td>
                {sorted.map((s) => (
                  <td key={s.date} className="metric-value">
                    {formatVal(s[row.key] as number | null)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="data-source">
        Source: {sorted[0]?.source ?? "unknown"}
      </div>
    </div>
  );
}
