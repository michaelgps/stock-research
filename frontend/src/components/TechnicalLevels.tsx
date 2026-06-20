import type {
  TechnicalLevelsResponse,
  TechnicalReferenceLevel,
  TechnicalZone,
} from "../types/financial";

interface TechnicalLevelsProps {
  levels: TechnicalLevelsResponse;
}

function money(value: number | null | undefined): string {
  return value == null ? "N/A" : `$${value.toFixed(2)}`;
}

function pct(value: number | null | undefined): string {
  if (value == null) return "N/A";
  const pctValue = value * 100;
  return `${pctValue >= 0 ? "+" : ""}${pctValue.toFixed(1)}%`;
}

function labelText(value: string): string {
  return value.replace(/_/g, " ");
}

function scoreClass(score: number): string {
  if (score >= 80) return "technical-score-strong";
  if (score >= 65) return "technical-score-medium";
  return "technical-score-weak";
}

function zoneClassName(levelType: string): string {
  if (levelType === "support") return "support";
  if (levelType === "resistance") return "resistance";
  return "active";
}

function referenceLabel(reference: TechnicalReferenceLevel): string {
  if (reference.price_low != null && reference.price_high != null) {
    return `${money(reference.price_low)} - ${money(reference.price_high)}`;
  }
  return money(reference.price);
}

function TechnicalPriceMap({ levels }: { levels: TechnicalLevelsResponse }) {
  const zones = [
    ...levels.resistance_zones,
    ...levels.active_zones,
    ...levels.support_zones,
  ];
  const prices = [
    levels.current_price,
    ...zones.flatMap((zone) => [zone.price_low, zone.price_high, zone.center_price]),
  ];
  const minPrice = Math.min(...prices);
  const maxPrice = Math.max(...prices);
  const padding = Math.max(levels.atr20 * 1.2, (maxPrice - minPrice) * 0.12, levels.current_price * 0.015);
  const chartMin = minPrice - padding;
  const chartMax = maxPrice + padding;
  const height = 360;
  const width = 820;
  const plotTop = 28;
  const plotBottom = 324;
  const axisX = 96;
  const zoneX = 150;
  const zoneWidth = 420;
  const labelX = 560;
  const zoneLabelX = 610;
  const priceSpan = Math.max(chartMax - chartMin, 1);

  const yForPrice = (price: number) =>
    plotBottom - ((price - chartMin) / priceSpan) * (plotBottom - plotTop);

  const ticks = Array.from({ length: 5 }, (_, index) => chartMin + (priceSpan * index) / 4);

  if (!zones.length) {
    return (
      <div className="technical-map-empty">
        Not enough qualified zones to draw a support/resistance map.
      </div>
    );
  }

  return (
    <div className="technical-map-card">
      <div className="technical-map-title">
        <span>Price Map</span>
        <strong>{money(chartMin)} - {money(chartMax)}</strong>
      </div>
      <svg className="technical-price-map" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Support and resistance price map">
        <defs>
          <linearGradient id="technicalMapBg" x1="0" x2="1" y1="0" y2="1">
            <stop offset="0%" stopColor="#f8fafc" />
            <stop offset="100%" stopColor="#eef6ff" />
          </linearGradient>
        </defs>
        <rect x="0" y="0" width={width} height={height} rx="18" fill="url(#technicalMapBg)" />

        {ticks.map((tick) => {
          const y = yForPrice(tick);
          return (
            <g key={tick}>
              <line x1={axisX} x2={labelX - 20} y1={y} y2={y} className="technical-map-grid" />
              <text x={axisX - 14} y={y + 4} textAnchor="end" className="technical-map-axis-label">
                {money(tick)}
              </text>
            </g>
          );
        })}

        <line x1={axisX} x2={axisX} y1={plotTop} y2={plotBottom} className="technical-map-axis" />

        {zones.map((zone) => {
          const yTop = yForPrice(zone.price_high);
          const yBottom = yForPrice(zone.price_low);
          const rectHeight = Math.max(yBottom - yTop, 12);
          const centerY = yForPrice(zone.center_price);
          const className = zoneClassName(zone.level_type);
          const labelY = Math.min(Math.max(centerY, plotTop + 18), plotBottom - 18);
          return (
            <g key={`${zone.level_type}-${zone.price_low}-${zone.price_high}`}>
              <rect
                x={zoneX}
                y={centerY - rectHeight / 2}
                width={zoneWidth}
                height={rectHeight}
                rx="12"
                className={`technical-map-zone technical-map-zone-${className}`}
              />
              <line
                x1={zoneX}
                x2={zoneX + zoneWidth}
                y1={centerY}
                y2={centerY}
                className={`technical-map-center technical-map-center-${className}`}
              />
              <line
                x1={zoneX + zoneWidth + 8}
                x2={zoneLabelX - 10}
                y1={centerY}
                y2={labelY}
                className={`technical-map-label-connector technical-map-label-connector-${className}`}
              />
              <text x={zoneLabelX} y={labelY - 5} className="technical-map-zone-label">
                {labelText(zone.level_type)} {zone.strength_score.toFixed(0)}
              </text>
              <text x={zoneLabelX} y={labelY + 14} className="technical-map-zone-price">
                {money(zone.price_low)} - {money(zone.price_high)}
              </text>
            </g>
          );
        })}

        {(() => {
          const currentY = yForPrice(levels.current_price);
          return (
            <g>
              <line x1={axisX - 6} x2={labelX} y1={currentY} y2={currentY} className="technical-map-current-line" />
              <circle cx={zoneX - 24} cy={currentY} r="7" className="technical-map-current-dot" />
            </g>
          );
        })()}
      </svg>
      <div className="technical-map-legend">
        <span className="legend-support">Support</span>
        <span className="legend-active">Active</span>
        <span className="legend-resistance">Resistance</span>
      </div>
    </div>
  );
}

function ScoreBreakdown({ zone }: { zone: TechnicalZone }) {
  const scoreParts = zone.raw_details?.score_parts ?? {};
  const entries = Object.entries(scoreParts).filter(([, value]) => Number.isFinite(value));

  if (!entries.length) return null;

  return (
    <details className="technical-score-details">
      <summary>Score breakdown</summary>
      <div className="technical-score-grid">
        {entries.map(([key, value]) => (
          <div key={key} className="technical-score-row">
            <span>{labelText(key)}</span>
            <strong>{value.toFixed(1)}</strong>
          </div>
        ))}
      </div>
    </details>
  );
}

function ZoneCard({ zone }: { zone: TechnicalZone }) {
  return (
    <article className={`technical-zone-card technical-zone-${zone.level_type}`}>
      <div className="technical-zone-topline">
        <div>
          <div className="technical-zone-type">{labelText(zone.level_type)} zone</div>
          <div className="technical-zone-price">
            {money(zone.price_low)} - {money(zone.price_high)}
          </div>
        </div>
        <div className={`technical-score-pill ${scoreClass(zone.strength_score)}`}>
          {zone.strength_score.toFixed(0)}
          <span>{zone.strength_label}</span>
        </div>
      </div>

      <div className="technical-zone-meta">
        <span>Center {money(zone.center_price)}</span>
        <span>Distance {pct(zone.distance_to_current_pct)}</span>
        <span>Relevance {zone.relevance_score.toFixed(0)}/100</span>
      </div>

      <div className="technical-evidence-list">
        {zone.evidence.map((item) => (
          <span key={item}>{labelText(item)}</span>
        ))}
      </div>

      {zone.invalid_if && (
        <p className="technical-rule">
          <strong>Invalid if:</strong> {zone.invalid_if}
        </p>
      )}

      {zone.breakout_confirmation && (
        <p className="technical-rule">
          <strong>Confirmation:</strong> {zone.breakout_confirmation}
        </p>
      )}

      {zone.raw_details?.latest_evidence_date && (
        <p className="technical-date">
          Latest evidence date: {zone.raw_details.latest_evidence_date}
        </p>
      )}

      <ScoreBreakdown zone={zone} />
    </article>
  );
}

function ZoneGroup({
  title,
  zones,
  emptyText,
}: {
  title: string;
  zones: TechnicalZone[];
  emptyText: string;
}) {
  return (
    <section className="technical-zone-group">
      <h4>{title}</h4>
      {zones.length ? (
        <div className="technical-zone-grid">
          {zones.map((zone) => (
            <ZoneCard key={`${zone.level_type}-${zone.price_low}-${zone.price_high}`} zone={zone} />
          ))}
        </div>
      ) : (
        <div className="technical-empty">{emptyText}</div>
      )}
    </section>
  );
}

function ReferenceLevelCard({ reference }: { reference: TechnicalReferenceLevel }) {
  return (
    <article className={`technical-reference-card reference-${reference.level_type}`}>
      <div>
        <div className="technical-reference-type">{labelText(reference.reference_type)}</div>
        <strong>{reference.label}</strong>
        <span>{referenceLabel(reference)}</span>
      </div>
      <div className="technical-reference-meta">
        <span>{labelText(reference.level_type)}</span>
        <span>{pct(reference.distance_to_current_pct)}</span>
      </div>
      <div className="technical-evidence-list">
        {reference.evidence.map((item) => (
          <span key={item}>{labelText(item)}</span>
        ))}
      </div>
    </article>
  );
}

function ReferenceLevels({ references }: { references: TechnicalReferenceLevel[] }) {
  return (
    <section className="technical-reference-group">
      <h4>Reference Levels</h4>
      {references.length ? (
        <div className="technical-reference-grid">
          {references.map((reference) => (
            <ReferenceLevelCard
              key={`${reference.reference_type}-${reference.label}-${referenceLabel(reference)}`}
              reference={reference}
            />
          ))}
        </div>
      ) : (
        <div className="technical-empty">No nearby moving average, gap, or prior high/low references.</div>
      )}
    </section>
  );
}

export function TechnicalLevels({ levels }: TechnicalLevelsProps) {
  return (
    <div className="technical-levels">
      <div className="technical-header">
        <div>
          <div className="technical-kicker">daily OHLCV support / resistance</div>
          <h3>Technical Levels</h3>
          <p>
            Volume-confirmed zones use 1Y daily OHLCV. Moving averages, gaps,
            and prior highs/lows are shown separately as references.
          </p>
        </div>
        <div className="technical-current-price">
          <span>Current price</span>
          <strong>{money(levels.current_price)}</strong>
        </div>
      </div>

      <div className="technical-stat-row">
        <span>Analysis date {levels.analysis_date}</span>
        <span>Lookback {levels.lookback_days} trading days</span>
        <span>ATR20 {money(levels.atr20)} ({(levels.atr20_pct * 100).toFixed(1)}%)</span>
      </div>

      <TechnicalPriceMap levels={levels} />

      <ZoneGroup
        title="Active Price Zone"
        zones={levels.active_zones}
        emptyText="Current price is not inside a qualified liquidity zone."
      />
      <ZoneGroup
        title="Support Zones"
        zones={levels.support_zones}
        emptyText="No qualified support zone below current price."
      />
      <ZoneGroup
        title="Resistance Zones"
        zones={levels.resistance_zones}
        emptyText="No qualified resistance zone above current price."
      />
      <ReferenceLevels references={levels.reference_levels ?? []} />

      {levels.notes.length > 0 && (
        <ul className="technical-notes">
          {levels.notes.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
