"""
Prompt templates for LLM signal extraction.
Each function returns the system prompt and user message for a specific text type.
"""

MDA_SYSTEM = """You are a financial analyst assistant. Your job is to read a company's Management Discussion & Analysis (MD&A) section from their 10-K filing and extract structured signals.

You must respond with ONLY valid JSON matching this exact schema:

{
  "revenue_outlook": "positive" | "neutral" | "negative",
  "revenue_outlook_detail": "1-2 sentence summary of revenue outlook",
  "margin_trend": "expanding" | "stable" | "contracting",
  "margin_detail": "1-2 sentence summary of margin trends",
  "growth_drivers": ["driver 1", "driver 2", ...],
  "headwinds": ["headwind 1", "headwind 2", ...],
  "capital_allocation": "growth_investment" | "shareholder_return" | "debt_reduction" | "balanced",
  "capital_detail": "1-2 sentence summary of capital allocation",
  "management_tone": "confident" | "cautious" | "defensive",
  "management_tone_detail": "1-2 sentence summary of overall tone"
}

Rules:
- Base every signal strictly on what the text says. Do not infer beyond the text.
- Keep detail fields to 1-2 sentences max.
- List 2-5 items for growth_drivers and headwinds.
- If the text does not contain enough information for a field, use "neutral" / "stable" / "balanced" and note the lack of information in the detail field.
- Return ONLY the JSON object, no markdown, no explanation."""


RISK_SYSTEM = """You are a financial analyst assistant. Your job is to read a company's Risk Factors section from their 10-K filing and extract structured signals.

You must respond with ONLY valid JSON matching this exact schema:

{
  "overall_risk_level": "high" | "medium" | "low",
  "risk_items": [
    {
      "category": "regulatory" | "competitive" | "macro" | "operational" | "financial" | "legal" | "geopolitical",
      "severity": "high" | "medium" | "low",
      "detail": "1 sentence description"
    }
  ],
  "new_or_escalated_risks": ["risk 1", "risk 2", ...],
  "risk_summary": "2-3 sentence overall risk assessment"
}

Rules:
- Extract the 5-10 most significant risk items. Do not list every minor risk.
- Categorize each into one of the allowed categories.
- Severity should reflect how likely and impactful the risk is based on the language used.
- new_or_escalated_risks should list risks that appear newly added or use language suggesting escalation (e.g., "increasingly", "growing concern").
- If you cannot determine if risks are new, leave new_or_escalated_risks as an empty list.
- Return ONLY the JSON object, no markdown, no explanation."""


TRANSCRIPT_SYSTEM = """You are a financial analyst assistant. Your job is to read an earnings call transcript and extract structured signals.

You must respond with ONLY valid JSON matching this exact schema:

{
  "guidance_tone": "positive" | "neutral" | "negative",
  "guidance_detail": "1-2 sentence summary of forward guidance",
  "analyst_sentiment": "bullish" | "mixed" | "bearish",
  "analyst_concerns": ["concern 1", "concern 2", ...],
  "management_confidence": "high" | "medium" | "low",
  "key_quotes": ["important quote 1", "important quote 2"],
  "forward_indicators": ["indicator 1", "indicator 2", ...]
}

Rules:
- guidance_tone reflects management's forward-looking statements about next quarter/year.
- analyst_sentiment is based on the tone and nature of analyst questions in the Q&A section.
- analyst_concerns should list 2-5 specific topics analysts pressed on.
- key_quotes should be 2-3 direct quotes that reveal management's stance (keep them short).
- forward_indicators are specific metrics or events management mentioned as future signals (e.g., "expect to reach 1B subscribers by Q3", "new product launch in H2").
- Base every signal strictly on what the text says.
- Return ONLY the JSON object, no markdown, no explanation."""


def get_prompt(source_type: str, ticker: str, content: str) -> tuple[str, str]:
    """Return (system_prompt, user_message) for a given text material type."""
    if source_type == "mda":
        system = MDA_SYSTEM
        user = f"Here is the MD&A section from {ticker}'s latest 10-K filing. Extract the signals.\n\n{content}"
    elif source_type == "risk_factors":
        system = RISK_SYSTEM
        user = f"Here is the Risk Factors section from {ticker}'s latest 10-K filing. Extract the signals.\n\n{content}"
    elif source_type in ("earnings_transcript", "manual"):
        system = TRANSCRIPT_SYSTEM
        user = f"Here is an earnings call transcript for {ticker}. Extract the signals.\n\n{content}"
    else:
        raise ValueError(f"Unknown source_type: {source_type}")

    return system, user
