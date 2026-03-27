import { useState } from "react";

interface TextMaterialInputProps {
  ticker: string;
  onSubmit: (content: string, sourceType: string) => Promise<void>;
  onExtract: () => Promise<void>;
  loading: boolean;
}

export function TextMaterialInput({
  ticker,
  onSubmit,
  onExtract,
  loading,
}: TextMaterialInputProps) {
  const [content, setContent] = useState("");
  const [sourceType, setSourceType] = useState("earnings_transcript");
  const [submitted, setSubmitted] = useState(false);
  const [extracted, setExtracted] = useState(false);

  const handleSubmit = async () => {
    if (!content.trim()) return;
    await onSubmit(content, sourceType);
    setSubmitted(true);
  };

  const handleExtract = async () => {
    await onExtract();
    setExtracted(true);
  };

  return (
    <div className="text-material-input">
      <h3>Text Materials (Optional)</h3>
      <p className="text-material-hint">
        Paste an earnings call transcript or other text to extract signals that
        refine the valuation assumptions.
      </p>
      <div className="text-material-controls">
        <select
          value={sourceType}
          onChange={(e) => setSourceType(e.target.value)}
          disabled={loading || submitted}
        >
          <option value="earnings_transcript">Earnings Transcript</option>
          <option value="manual">Manual Notes</option>
        </select>
      </div>
      <textarea
        value={content}
        onChange={(e) => setContent(e.target.value)}
        placeholder={`Paste ${sourceType === "earnings_transcript" ? "earnings call transcript" : "notes"} for ${ticker}...`}
        rows={6}
        disabled={loading || submitted}
      />
      <div className="text-material-actions">
        {!submitted ? (
          <button
            onClick={handleSubmit}
            disabled={loading || !content.trim()}
            className="btn-secondary"
          >
            {loading ? "Submitting..." : "Submit Text"}
          </button>
        ) : !extracted ? (
          <>
            <span className="text-material-status">Text submitted</span>
            <button
              onClick={handleExtract}
              disabled={loading}
              className="btn-secondary"
            >
              {loading ? "Extracting..." : "Extract Signals"}
            </button>
          </>
        ) : (
          <span className="text-material-status">Signals extracted</span>
        )}
      </div>
    </div>
  );
}
