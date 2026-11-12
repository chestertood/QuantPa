import { useEffect, useMemo, useState } from "react";
import { getWatchlists, usePolled } from "../api";
import { money, pct, cls } from "../format";
import StockLogo from "./StockLogo.jsx";
import TradingViewChart from "./TradingViewChart.jsx";
import StaleMark from "./StaleMark.jsx";
import Fundamentals from "./Fundamentals.jsx";

/** Symbols matching `query`. An empty query keeps the active list intact;
 *  a query searches every list, so you can find a symbol without first knowing
 *  which watchlist it lives in. Exported for testing. */
export function filterItems(watchlists, activeId, query) {
  const q = query.trim().toUpperCase();
  if (!q) {
    const list = watchlists.find((w) => w.id === activeId);
    return list ? list.items : [];
  }
  const seen = new Set();
  const hits = [];
  for (const wl of watchlists) {
    for (const it of wl.items) {
      if (it.symbol.toUpperCase().includes(q) && !seen.has(it.symbol)) {
        seen.add(it.symbol);
        hits.push(it);
      }
    }
  }
  return hits;
}

export default function Markets({ chartSym, onOpen, onBack }) {
  const { data, err } = usePolled(getWatchlists);
  const watchlists = data?.watchlists;

  if (chartSym) {
    return (
      <ChartScreen
        symbol={chartSym}
        item={findItem(watchlists, chartSym)}
        onBack={onBack}
      />
    );
  }
  return <Picker watchlists={watchlists} err={err} onOpen={onOpen} />;
}

function findItem(watchlists, symbol) {
  for (const wl of watchlists || []) {
    const hit = wl.items.find((i) => i.symbol === symbol);
    if (hit) return hit;
  }
  return null;
}

function Picker({ watchlists, err, onOpen }) {
  const [activeId, setActiveId] = useState(null);
  const [query, setQuery] = useState("");

  // Default to the first list once they arrive, without clobbering a tab the
  // user has already picked.
  useEffect(() => {
    if (activeId == null && watchlists?.length) setActiveId(watchlists[0].id);
  }, [watchlists, activeId]);

  const items = useMemo(
    () => (watchlists ? filterItems(watchlists, activeId, query) : []),
    [watchlists, activeId, query],
  );

  return (
    <>
      <header>
        <h1>Markets</h1>
        {watchlists && (
          <span className="asof">คลิกหุ้นเพื่อดูกราฟ</span>
        )}
      </header>

      {err && <div className="error">Watchlists: {err}</div>}
      {!watchlists && !err && <div className="loading">Loading watchlists…</div>}

      {watchlists && (
        <>
          <div className="picker-bar">
            <input
              className="search"
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="ค้นหา AAPL, NVDA, หุ้น…"
              aria-label="ค้นหาหุ้น"
            />
            <div className="tabs" role="tablist">
              {watchlists.map((wl) => (
                <button
                  key={wl.id}
                  role="tab"
                  aria-selected={activeId === wl.id}
                  className={`tab ${activeId === wl.id ? "active" : ""}`}
                  onClick={() => setActiveId(wl.id)}
                >
                  {wl.name} <span className="count">{wl.items.length}</span>
                </button>
              ))}
            </div>
          </div>

          {query && (
            <p className="muted-text">
              {items.length
                ? `พบ ${items.length} ตัว จากทุกลิสต์`
                : `ไม่พบหุ้นที่ตรงกับ "${query}"`}
            </p>
          )}

          <div className="stock-grid">
            {items.map((it) => (
              <StockCard key={it.symbol} item={it} onOpen={onOpen} />
            ))}
          </div>
        </>
      )}
    </>
  );
}

function StockCard({ item, onOpen }) {
  return (
    <button className="stock-card" onClick={() => onOpen(item.symbol)}>
      <StockLogo symbol={item.symbol} size={40} />
      <div className="stock-sym">
        {item.symbol}
        {item.stale && <StaleMark ageS={item.quote_age_s} />}
      </div>
      <div className="stock-price">
        {item.price == null ? "—" : money(item.price)}
      </div>
      <div className={`stock-chg ${cls(item.day_change_pct)}`}>
        {item.day_change_pct == null ? "—" : pct(item.day_change_pct)}
      </div>
    </button>
  );
}

function ChartScreen({ symbol, item, onBack }) {
  // Esc is the reflex for leaving a full-bleed view; the back button alone
  // makes you aim for a 60px target in the corner.
  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && onBack();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onBack]);

  return (
    <div className="chart-screen">
      <div className="chart-bar">
        <button className="back-btn" onClick={onBack} title="กลับ (Esc)">
          ‹ กลับ
        </button>
        <StockLogo symbol={symbol} size={32} />
        <span className="chart-sym">{symbol}</span>
        {item && (
          <>
            <span className="chart-price">
              {item.price == null ? "—" : money(item.price)}
            </span>
            <span className={`chart-chg ${cls(item.day_change_pct)}`}>
              {item.day_change_pct == null ? "—" : pct(item.day_change_pct)}
            </span>
            {item.stale && <StaleMark ageS={item.quote_age_s} />}
          </>
        )}
      </div>
      <TradingViewChart symbol={symbol} height="60vh" />
      <Fundamentals symbol={symbol} price={item?.price} />
    </div>
  );
}
