import { useState } from "react";
import { TickerInput } from "./components/TickerInput";
import { CompanyHeader } from "./components/CompanyHeader";
import { FinancialTable } from "./components/FinancialTable";
import { AnalystEstimates } from "./components/AnalystEstimates";
import { TextMaterialInput } from "./components/TextMaterialInput";
import { ValuationSummary } from "./components/ValuationSummary";
import { ForwardTrend } from "./components/ForwardTrend";
import { HistoricalPE } from "./components/HistoricalPE";
import { PeerComparison } from "./components/PeerComparison";
import { TechnicalLevels } from "./components/TechnicalLevels";
import {
  fetchTechnicalLevels,
  fetchFinancialData,
  submitTextMaterial,
  runSignalExtraction,
  runValuation,
} from "./services/api";
import type {
  FinancialDataResponse,
  TechnicalLevelsResponse,
  ValuationResponse,
} from "./types/financial";
import "./App.css";

function App() {
  const [ticker, setTicker] = useState("");
  const [data, setData] = useState<FinancialDataResponse | null>(null);
  const [valuation, setValuation] = useState<ValuationResponse | null>(null);
  const [technicalLevels, setTechnicalLevels] = useState<TechnicalLevelsResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [valuationLoading, setValuationLoading] = useState(false);
  const [technicalLoading, setTechnicalLoading] = useState(false);
  const [textLoading, setTextLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [valuationError, setValuationError] = useState<string | null>(null);
  const [technicalError, setTechnicalError] = useState<string | null>(null);
  const [activeAnalysis, setActiveAnalysis] = useState<"valuation" | "technical" | null>(null);

  const handleSubmit = async (t: string) => {
    setLoading(true);
    setError(null);
    setData(null);
    setValuation(null);
    setTechnicalLevels(null);
    setValuationError(null);
    setTechnicalError(null);
    setTicker(t);

    try {
      const result = await fetchFinancialData(t);
      setData(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : "An error occurred");
    } finally {
      setLoading(false);
    }
  };

  const handleRunValuation = async () => {
    if (!ticker) return;
    setValuationLoading(true);
    setValuationError(null);
    setValuation(null);
    setActiveAnalysis("valuation");

    try {
      const result = await runValuation(ticker);
      setValuation(result);
    } catch (err) {
      setValuationError(
        err instanceof Error ? err.message : "Valuation failed"
      );
    } finally {
      setValuationLoading(false);
    }
  };

  const handleRunTechnicalLevels = async () => {
    if (!ticker) return;
    setTechnicalLoading(true);
    setTechnicalError(null);
    setTechnicalLevels(null);
    setActiveAnalysis("technical");

    try {
      const result = await fetchTechnicalLevels(ticker);
      setTechnicalLevels(result);
    } catch (err) {
      setTechnicalError(
        err instanceof Error ? err.message : "Technical levels failed"
      );
    } finally {
      setTechnicalLoading(false);
    }
  };

  const valuationPanel = (
    <>
      {valuationLoading && (
        <div className="analysis-loading">Running valuation model...</div>
      )}
      {valuation && (
        <div className="valuation-results">
          <ValuationSummary valuation={valuation} />
          <ForwardTrend
            trend={valuation.forward_trend}
            currentPrice={valuation.current_price}
            peMultiple={valuation.base.multiples.pe_multiple}
          />
          <HistoricalPE ranges={valuation.historical_pe_ranges} />
          {valuation.peer_comparison && (
            <PeerComparison
              peers={valuation.peer_comparison}
              tickerPe={valuation.base.multiples.pe_multiple}
            />
          )}
        </div>
      )}
    </>
  );

  const technicalPanel = (
    <>
      {technicalLoading && (
        <div className="analysis-loading">Finding support and resistance zones...</div>
      )}
      {technicalLevels && <TechnicalLevels levels={technicalLevels} />}
    </>
  );

  const handleTextSubmit = async (content: string, sourceType: string) => {
    setTextLoading(true);
    try {
      await submitTextMaterial(ticker, content, sourceType);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to submit text");
    } finally {
      setTextLoading(false);
    }
  };

  const handleExtractSignals = async () => {
    setTextLoading(true);
    try {
      await runSignalExtraction(ticker);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Signal extraction failed"
      );
    } finally {
      setTextLoading(false);
    }
  };

  return (
    <div className="app">
      <header className="app-header">
        <h1>Stock Research Engine</h1>
        <p>Enter a ticker to analyze</p>
      </header>

      <main>
        <TickerInput onSubmit={handleSubmit} loading={loading} />

        {error && <div className="error-message">{error}</div>}

        {data && (
          <div className="results">
            <CompanyHeader company={data.company} />

            {/* Phase 2: Optional text material + signal extraction */}
            <TextMaterialInput
              ticker={ticker}
              onSubmit={handleTextSubmit}
              onExtract={handleExtractSignals}
              loading={textLoading}
            />

            {/* Phase 3/4: Valuation and technical triggers */}
            <div className="analysis-actions">
              <button
                onClick={handleRunValuation}
                disabled={valuationLoading}
                className="btn-primary"
              >
                {valuationLoading ? "Running Valuation..." : "Run Valuation"}
              </button>
              <button
                onClick={handleRunTechnicalLevels}
                disabled={technicalLoading}
                className="btn-secondary"
              >
                {technicalLoading ? "Finding Levels..." : "Find Support / Resistance"}
              </button>
            </div>
            <div className="analysis-errors">
              {valuationError && (
                <div className="error-message">{valuationError}</div>
              )}
              {technicalError && (
                <div className="error-message">{technicalError}</div>
              )}
            </div>

            <div className="analysis-output">
              {activeAnalysis === "technical" ? (
                <>
                  {technicalPanel}
                  {valuationPanel}
                </>
              ) : (
                <>
                  {valuationPanel}
                  {technicalPanel}
                </>
              )}
            </div>

            {/* Financial data tables */}
            <FinancialTable
              statements={data.annual_statements}
              title="Annual Financial Statements"
            />
            {data.quarterly_statements.length > 0 && (
              <FinancialTable
                statements={data.quarterly_statements}
                title="Quarterly Financial Statements"
              />
            )}
            <AnalystEstimates estimates={data.analyst_estimates} />
          </div>
        )}
      </main>
    </div>
  );
}

export default App;
