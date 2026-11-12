import { useEffect, useState } from "react";
import { getNews } from "../api";

// News doesn't move by the second like quotes — a slow poll is enough and
// avoids re-fetching RSS well inside the backend's 5-minute cache.
const NEWS_POLL_MS = 60_000;

export default function News() {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    let alive = true;
    function tick() {
      if (document.hidden) return;
      getNews()
        .then((d) => alive && (setData(d), setErr(null)))
        .catch((e) => alive && setErr(e.message));
    }
    tick();
    const id = setInterval(tick, NEWS_POLL_MS);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  if (err) return <div className="panel"><h2>News</h2><div className="error">{err}</div></div>;
  if (!data) return <div className="panel"><h2>News</h2><div className="loading">Loading news…</div></div>;

  const items = data.items;
  const yours = items.filter((it) => it.holdings.length > 0);
  const macro = items.filter((it) => it.holdings.length === 0);

  return (
    <>
      <header>
        <h1>News</h1>
        <span className="asof">as of {new Date(data.as_of).toLocaleString()}</span>
      </header>

      {yours.length > 0 && (
        <section className="panel news-panel">
          <h2>
            Impacts your book <span className="count">{yours.length}</span>
          </h2>
          <div className="news-list">
            {yours.map((it) => (
              <NewsCard key={it.link || it.title} item={it} />
            ))}
          </div>
        </section>
      )}

      <section className="panel news-panel" style={{ marginTop: 16 }}>
        <h2>
          Macro <span className="count">{macro.length}</span>
        </h2>
        {macro.length === 0 ? (
          <p className="muted-text">No matching headlines in the last 48h.</p>
        ) : (
          <div className="news-list">
            {macro.map((it) => (
              <NewsCard key={it.link || it.title} item={it} />
            ))}
          </div>
        )}
      </section>
    </>
  );
}

function ageStr(ageS) {
  if (ageS < 3600) return `${Math.round(ageS / 60)}m ago`;
  if (ageS < 86400) return `${Math.round(ageS / 3600)}h ago`;
  return `${Math.round(ageS / 86400)}d ago`;
}

function NewsCard({ item }) {
  return (
    <a className="news-card" href={item.link} target="_blank" rel="noreferrer">
      <div className="news-title">{item.title}</div>
      <div className="news-meta">
        {item.source} · {ageStr(item.age_s)} · {item.why}
      </div>
      {(item.sectors.length > 0 || item.holdings.length > 0) && (
        <div className="news-chips">
          {item.sectors.map((s) => (
            <span key={s.name} className={`chip ${s.dir > 0 ? "up" : s.dir < 0 ? "down" : ""}`}>
              {s.name} {s.dir > 0 ? "▲" : s.dir < 0 ? "▼" : ""}
            </span>
          ))}
          {item.holdings.map((h) => (
            <span key={h.symbol} className="chip chip-holding">
              {h.symbol} · {h.weight_pct.toFixed(1)}%
            </span>
          ))}
        </div>
      )}
    </a>
  );
}
