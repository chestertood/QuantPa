import { useEffect, useState } from "react";
import { getPortfolio, getSource, usePolled, POLL_MS } from "./api";
import { fromUsd, pct, cls } from "./format";
import Sidebar from "./components/Sidebar.jsx";
import CashflowPanel from "./components/CashflowPanel.jsx";
import TaxSummaryPanel from "./components/TaxSummaryPanel.jsx";
import Trading from "./components/Trading.jsx";
import Markets from "./components/Markets.jsx";
import News from "./components/News.jsx";
import Backtest from "./components/Backtest.jsx";
import StaleMark from "./components/StaleMark.jsx";
import ChatWidget from "./components/ChatWidget.jsx";
import StockLogo from "./components/StockLogo.jsx";

export default function App() {
  const [view, setView] = useState("dashboard");
  // null = Markets shows the stock picker; a symbol = it shows that chart.
  const [chartSym, setChartSym] = useState(null);
  const { data, err } = usePolled(getPortfolio);

  /** Jump straight to a symbol's chart, from anywhere. */
  function openChart(symbol) {
    setChartSym(symbol);
    setView("markets");
  }

  function navigate(next) {
    // Reaching Markets from the sidebar always lands on the picker — otherwise
    // it would reopen whatever chart you last had, which reads as a stuck page.
    if (next === "markets") setChartSym(null);
    setView(next);
  }

  return (
    <div className="shell">
      <Sidebar view={view} onSelect={navigate} />
      <main className="main">
        {view === "dashboard" && (
          <Dashboard data={data} err={err} onOpenChart={openChart} />
        )}
        {view === "trading" && <Trading />}
        {view === "markets" && (
          <Markets
            chartSym={chartSym}
            onOpen={setChartSym}
            onBack={() => setChartSym(null)}
          />
        )}
        {view === "news" && <News />}
        {view === "backtest" && <Backtest />}
        {view === "quant" && <QuantTeam />}
        {view === "settings" && <Settings data={data} />}
      </main>
      <ChatWidget />
    </div>
  );
}

function Dashboard({ data, err, onOpenChart }) {
  if (err) return <div className="error">Error: {err}</div>;
  if (!data) return <div className="loading">Loading portfolio…</div>;

  const s = data.summary;
  const rate = data.usd_thb_rate;
  const [currency, setCurrency] = useState("THB");
  // THB falls back to USD if the rate fetch failed, rather than showing ฿0.
  const fmt = (n) => fromUsd(n, currency, rate);

  return (
    <>
      <header>
        <h1>Dashboard</h1>
        <span className="asof">
          as of {new Date(data.as_of).toLocaleString()}
        </span>
        {data.source && (
          <span className="badge">{data.source.toUpperCase()}</span>
        )}
        <select
          className="currency-select"
          value={currency}
          onChange={(e) => setCurrency(e.target.value)}
        >
          <option value="THB">฿ THB</option>
          <option value="USD">$ USD</option>
        </select>
      </header>

      <section>
        <div className="panel">
          <h2>
            Positions <span className="count">{data.positions.length}</span>
          </h2>
          <div className="scroll">
            <table>
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th>Qty</th>
                  <th>Price</th>
                  <th>Value</th>
                  <th>Day</th>
                  <th>P/L</th>
                  <th>Wt</th>
                </tr>
              </thead>
              <tbody>
                {data.positions.map((p) => (
                  <tr
                    key={p.symbol}
                    onClick={() => onOpenChart(p.symbol)}
                    title={`ดูกราฟ ${p.symbol}`}
                  >
                    <td className="sym">
                      <span className="sym-cell">
                        <StockLogo symbol={p.symbol} size={20} />
                        {p.symbol}
                        {p._stale && <StaleMark ageS={p.quote_age_s} />}
                      </span>
                    </td>
                    <td>{p.quantity}</td>
                    <td>{fmt(p.current_price)}</td>
                    <td>{fmt(p.market_value)}</td>
                    <td className={cls(p.day_change)}>
                      {pct(p.day_change_pct)}
                    </td>
                    <td className={cls(p.unrealized_pl)}>
                      {pct(p.unrealized_pl_pct)}
                    </td>
                    <td>{p.weight}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </section>

      <section className="cards">
        <Card label="Market Value" value={fmt(s.total_market_value)} />
        <Card
          label="Unrealized P/L"
          value={fmt(s.total_unrealized_pl)}
          sub={pct(s.total_unrealized_pl_pct)}
          tone={cls(s.total_unrealized_pl)}
        />
        <Card
          label="Day Change"
          value={fmt(s.total_day_change)}
          sub={pct(s.total_day_change_pct)}
          tone={cls(s.total_day_change)}
        />
        <Card
          label="Cost Basis"
          value={fmt(s.total_cost_basis)}
          sub={`${s.position_count} positions`}
        />
      </section>

      <section style={{ marginTop: 16 }}>
        <CashflowPanel currency={currency} rate={rate} />
      </section>

      <section style={{ marginTop: 16 }}>
        <TaxSummaryPanel currency={currency} rate={rate} />
      </section>
    </>
  );
}

function QuantTeam() {
  const agents = [
    { name: "Technical Agent", desc: "Chart patterns, indicators, momentum." },
    { name: "Risk Agent", desc: "Exposure, drawdown, position sizing." },
    { name: "Fundamental Agent", desc: "Valuation, earnings, macro." },
  ];
  return (
    <>
      <header>
        <h1>Quant Team</h1>
      </header>
      <section className="cards">
        {agents.map((a) => (
          <div className="panel" key={a.name}>
            <h2>{a.name}</h2>
            <p className="muted-text">{a.desc}</p>
            <span className="badge">Phase 3 — coming soon</span>
          </div>
        ))}
      </section>
    </>
  );
}

function Settings({ data }) {
  const [src, setSrc] = useState(null);

  useEffect(() => {
    getSource()
      .then(setSrc)
      .catch(() => setSrc(null));
  }, []);

  const source = src?.source || "csv";
  const webull = source === "webull";

  return (
    <>
      <header>
        <h1>Settings</h1>
      </header>
      <section>
        <div className="panel">
          <h2>Data source</h2>
          <p className="muted-text">
            Active source: <strong>{source.toUpperCase()}</strong>
          </p>
          {webull ? (
            <p className="muted-text">
              Webull auth:{" "}
              {src?.webull_authed ? (
                <span className="up">connected ✓</span>
              ) : (
                <span className="down">
                  not logged in — run <code>python webull_login.py</code>
                </span>
              )}
            </p>
          ) : (
            <p className="muted-text">
              Portfolio CSV: <code>{src?.csv || "sample_portfolio.csv"}</code>
            </p>
          )}
          <p className="muted-text">
            Refresh interval: {POLL_MS / 1000}s (auto, pauses in a background
            tab).
          </p>
          {data && (
            <p className="muted-text">
              Loaded {data.summary.position_count} positions.
            </p>
          )}
        </div>

        <div className="panel" style={{ marginTop: 16 }}>
          <h2>Webull sync (Phase 2)</h2>
          <p className="muted-text">
            Switch source in backend <code>.env</code>:
          </p>
          <ol className="muted-text">
            <li>
              Set <code>WEBULL_EMAIL</code> / <code>WEBULL_PASSWORD</code>.
            </li>
            <li>
              Run <code>python webull_login.py</code> (handles MFA email code).
            </li>
            <li>
              Set <code>PORTFOLIO_SOURCE=webull</code>, restart backend.
            </li>
          </ol>
          <p className="muted-text">
            Credentials stay server-side. Positions read-only.
          </p>
        </div>
      </section>
    </>
  );
}

function Card({ label, value, sub, tone }) {
  return (
    <div className="card">
      <div className="card-label">{label}</div>
      <div className={`card-value ${tone || ""}`}>{value}</div>
      {sub && <div className={`card-sub ${tone || ""}`}>{sub}</div>}
    </div>
  );
}
