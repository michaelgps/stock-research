import { useState } from "react";

interface TickerInputProps {
  onSubmit: (ticker: string) => void;
  loading: boolean;
}

export function TickerInput({ onSubmit, loading }: TickerInputProps) {
  const [ticker, setTicker] = useState("");

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = ticker.trim().toUpperCase();
    if (trimmed) {
      onSubmit(trimmed);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="ticker-input">
      <input
        type="text"
        value={ticker}
        onChange={(e) => setTicker(e.target.value.toUpperCase())}
        placeholder="Enter ticker (e.g. AAPL)"
        maxLength={10}
        disabled={loading}
      />
      <button type="submit" disabled={loading || !ticker.trim()}>
        {loading ? "Loading..." : "Analyze"}
      </button>
    </form>
  );
}
