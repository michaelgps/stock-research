import type { FinancialDataResponse, ValuationResponse } from "../types/financial";

const API_BASE = "http://localhost:8000";

async function apiGet<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`);
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Unknown error" }));
    throw new Error(error.detail || `HTTP ${response.status}`);
  }
  return response.json();
}

async function apiPost<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Unknown error" }));
    throw new Error(error.detail || `HTTP ${response.status}`);
  }
  return response.json();
}

export async function fetchFinancialData(
  ticker: string
): Promise<FinancialDataResponse> {
  return apiGet(`/api/financial-data/${ticker}`);
}

export async function submitTextMaterial(
  ticker: string,
  content: string,
  sourceType: string = "earnings_transcript"
): Promise<{ status: string; ticker: string; chars: number }> {
  return apiPost("/api/text-materials", {
    ticker,
    content,
    source_type: sourceType,
  });
}

export async function runSignalExtraction(
  ticker: string
): Promise<unknown> {
  return apiPost(`/api/extract-signals/${ticker}`);
}

export async function runValuation(
  ticker: string
): Promise<ValuationResponse> {
  return apiPost(`/api/valuation/${ticker}`);
}
