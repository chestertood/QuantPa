import { useEffect, useRef, useState } from "react";

const BASE = "/api";

// Error bodies are JSON {detail} from FastAPI, but an unhandled server error is
// plain text ("Internal Server Error") — r.json() on that threw a useless
// "Unexpected token 'I'" and hid the real failure.
async function fail(r, fallback) {
  let detail;
  try { detail = (await r.json()).detail; } catch { /* non-JSON body */ }
  throw new Error(detail || `${fallback} (HTTP ${r.status})`);
}

// How often live views re-fetch. Matches the backend quote TTL (QUOTE_TTL,
// default 5s) — polling faster than the cache just serves the same numbers.
export const POLL_MS = 5000;

export async function getPortfolio() {
  const r = await fetch(`${BASE}/portfolio`);
  if (!r.ok) await fail(r, "portfolio fetch failed");
  return r.json();
}

export async function getSource() {
  const r = await fetch(`${BASE}/source`);
  if (!r.ok) await fail(r, "source fetch failed");
  return r.json();
}

export async function getWatchlists() {
  const r = await fetch(`${BASE}/watchlists`);
  if (!r.ok) await fail(r, "watchlists fetch failed");
  return r.json();
}

export async function getCashflow() {
  const r = await fetch(`${BASE}/cashflow`);
  if (!r.ok) await fail(r, "cashflow fetch failed");
  return r.json();
}

export async function getTaxSummary() {
  const r = await fetch(`${BASE}/tax-summary`);
  if (!r.ok) await fail(r, "tax summary fetch failed");
  return r.json();
}

export async function getEconCalendar() {
  const r = await fetch(`${BASE}/econ-calendar`);
  if (!r.ok) await fail(r, "econ calendar fetch failed");
  return r.json();
}

export async function getNews() {
  const r = await fetch(`${BASE}/news`);
  if (!r.ok) await fail(r, "news fetch failed");
  return r.json();
}

export async function getFundamentals(symbol) {
  const r = await fetch(`${BASE}/fundamentals/${encodeURIComponent(symbol)}`);
  if (!r.ok) await fail(r, "fundamentals fetch failed");
  return r.json();
}

export async function getHistory(symbol, period = "6mo") {
  const r = await fetch(`${BASE}/positions/${symbol}/history?period=${period}`);
  if (!r.ok) await fail(r, "history fetch failed");
  return r.json();
}

/** Fetch on mount, then every `ms`, and again the moment a hidden tab is
 *  re-shown. A background tab doesn't poll — nobody is reading it, and the
 *  quotes cost one Yahoo request per symbol. Returns { data, err }. */
export function usePolled(fetcher, ms = POLL_MS) {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  // Keep the latest fetcher without making it an effect dep — an inline arrow
  // as `fetcher` would otherwise restart the interval on every render.
  const fn = useRef(fetcher);
  fn.current = fetcher;

  useEffect(() => {
    let alive = true;
    async function tick() {
      if (document.hidden) return;
      try {
        const d = await fn.current();
        if (alive) {
          setData(d);
          setErr(null);
        }
      } catch (e) {
        if (alive) setErr(e.message);
      }
    }
    tick();
    const id = setInterval(tick, ms);
    document.addEventListener("visibilitychange", tick);
    return () => {
      alive = false;
      clearInterval(id);
      document.removeEventListener("visibilitychange", tick);
    };
  }, [ms]);

  return { data, err };
}

export async function runBacktest(body, { signal } = {}) {
  const r = await fetch(`${BASE}/backtest`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!r.ok) await fail(r, "backtest failed");
  return r.json();
}

/** One chat turn. Backend: POST /api/chat {message, session_id} -> {reply, session_id}. */
export async function sendChat(message, sessionId) {
  const r = await fetch(`${BASE}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, session_id: sessionId }),
  });
  if (!r.ok) await fail(r, "chat failed");
  return r.json();
}
