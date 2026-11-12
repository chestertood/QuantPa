import { useRef, useState } from "react";
import {
  LineChart,
  Line,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  ResponsiveContainer,
  CartesianGrid,
} from "recharts";
import { runBacktest } from "../api";
import { fracPct, ratio } from "../format";

const DEFAULT_BASKET = "CRM, NOW, ADBE, SNOW, DDOG, TEAM, WDAY, ZS, HUBS, MDB";
let nextId = 1;

// The strategy is the subject, the benchmarks are context — so the strategy is
// the only bright series. Dash patterns carry the distinction too, because the
// app's red/green is not colorblind-safe on its own.
const SERIES = [
  {
    key: "strategy",
    name: "Strategy",
    stroke: "#4ea1ff",
    dash: null,
    width: 2.5,
  },
  {
    key: "bh_basket",
    name: "Basket B&H",
    stroke: "#9aa4b2",
    dash: "6 3",
    width: 1.5,
  },
  {
    key: "bh_spy",
    name: "SPY B&H",
    stroke: "#6b7280",
    dash: "2 3",
    width: 1.5,
  },
];

function labelFor(rule, params) {
  return rule === "sma"
    ? `SMA filter — window ${params.window}`
    : `Momentum top-${params.n} — ${params.lookback}mo lookback`;
}

/** A saved signal test: config + its own run state, independent of the others. */
export default function Backtest() {
  const [symbols, setSymbols] = useState(DEFAULT_BASKET);
  const [rule, setRule] = useState("sma");
  const [window, setWindow] = useState(200);
  const [topN, setTopN] = useState(3);
  const [lookback, setLookback] = useState(12);
  const [years, setYears] = useState(5);
  const [costBps, setCostBps] = useState(5);
  const [signals, setSignals] = useState([]);
  const controllers = useRef(new Map()); // signal id -> AbortController for in-flight runs

  function updateSignal(id, patch) {
    setSignals((prev) =>
      prev.map((s) => (s.id === id ? { ...s, ...patch } : s)),
    );
  }

  function addSignal() {
    const params =
      rule === "sma" ? { window: +window } : { n: +topN, lookback: +lookback };
    const symbolList = symbols
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    if (!symbolList.length) return;
    setSignals((prev) => [
      ...prev,
      {
        id: nextId++,
        label: labelFor(rule, params),
        symbols: symbolList,
        rule,
        params,
        years: +years,
        costBps: +costBps,
        status: "idle", // idle | running | done | error
        data: null,
        err: null,
        expanded: false,
      },
    ]);
  }

  async function runSignal(sig) {
    const controller = new AbortController();
    controllers.current.set(sig.id, controller);
    updateSignal(sig.id, { status: "running", err: null });
    try {
      const data = await runBacktest(
        {
          symbols: sig.symbols,
          benchmark: "SPY",
          rule: sig.rule,
          params: sig.params,
          years: sig.years,
          cost_bps: sig.costBps,
        },
        { signal: controller.signal },
      );
      updateSignal(sig.id, { status: "done", data, expanded: true });
    } catch (e) {
      if (e.name === "AbortError") {
        updateSignal(sig.id, { status: "idle" });
      } else {
        updateSignal(sig.id, { status: "error", err: e.message });
      }
    } finally {
      controllers.current.delete(sig.id);
    }
  }

  function stopSignal(id) {
    controllers.current.get(id)?.abort();
  }

  function toggleExpand(id) {
    setSignals((prev) =>
      prev.map((s) => (s.id === id ? { ...s, expanded: !s.expanded } : s)),
    );
  }

  function removeSignal(id) {
    controllers.current.get(id)?.abort();
    setSignals((prev) => prev.filter((s) => s.id !== id));
  }

  return (
    <>
      <header>
        <h1>Backtest Lab</h1>
      </header>

      <section>
        <div className="panel">
          <h2>Add signal test</h2>
          <div className="bt-controls">
            <label>
              Basket
              <input
                value={symbols}
                onChange={(e) => setSymbols(e.target.value)}
              />
            </label>
            <label>
              Rule
              <select value={rule} onChange={(e) => setRule(e.target.value)}>
                <option value="sma">SMA filter</option>
                <option value="momentum">Momentum top-N</option>
              </select>
            </label>
            {rule === "sma" ? (
              <label>
                SMA window
                <input
                  type="number"
                  value={window}
                  onChange={(e) => setWindow(e.target.value)}
                />
              </label>
            ) : (
              <>
                <label>
                  Top N
                  <input
                    type="number"
                    value={topN}
                    onChange={(e) => setTopN(e.target.value)}
                  />
                </label>
                <label>
                  Lookback (mo)
                  <input
                    type="number"
                    value={lookback}
                    onChange={(e) => setLookback(e.target.value)}
                  />
                </label>
              </>
            )}
            <label>
              Years
              <input
                type="number"
                value={years}
                onChange={(e) => setYears(e.target.value)}
              />
            </label>
            <label>
              Cost (bps)
              <input
                type="number"
                value={costBps}
                onChange={(e) => setCostBps(e.target.value)}
              />
            </label>
            <button onClick={addSignal}>+ Add signal</button>
          </div>
          <p className="muted-text">
            Adds a card below. Each signal runs and stops on its own; run
            several to compare.
          </p>
        </div>
      </section>

      {signals.length === 0 && (
        <section style={{ marginTop: 16 }}>
          <div className="panel">
            <p className="muted-text">No signals yet — add one above.</p>
          </div>
        </section>
      )}

      {signals.map((sig) => (
        <SignalCard
          key={sig.id}
          sig={sig}
          onRun={() => runSignal(sig)}
          onStop={() => stopSignal(sig.id)}
          onToggle={() => toggleExpand(sig.id)}
          onRemove={() => removeSignal(sig.id)}
        />
      ))}
    </>
  );
}

function SignalCard({ sig, onRun, onStop, onToggle, onRemove }) {
  const running = sig.status === "running";
  return (
    <section style={{ marginTop: 16 }}>
      <div className="panel">
        <div className="bt-signal-header" onClick={onToggle}>
          <span className="bt-signal-chevron">{sig.expanded ? "▾" : "▸"}</span>
          <span className="bt-signal-title">{sig.label}</span>
          <span className="bt-signal-symbols muted-text">
            {sig.symbols.join(", ")}
          </span>
          <span className="bt-signal-summary">
            <SignalSummary sig={sig} />
          </span>
          <span
            onClick={(e) => e.stopPropagation()}
            className="bt-signal-actions"
          >
            {running ? (
              <button className="bt-stop" onClick={onStop}>
                Stop
              </button>
            ) : (
              <button onClick={onRun}>Run test</button>
            )}
            <button className="bt-remove" onClick={onRemove} title="Remove">
              ✕
            </button>
          </span>
        </div>

        {sig.expanded && (
          <div style={{ marginTop: 12 }}>
            {sig.status === "error" && (
              <div className="error">backtest: {sig.err}</div>
            )}
            {sig.status === "done" && sig.data && <Report data={sig.data} />}
            {sig.status !== "done" && sig.status !== "error" && (
              <p className="muted-text">
                {running ? "Running…" : "Not run yet — press Run test."}
              </p>
            )}
          </div>
        )}
      </div>
    </section>
  );
}

function SignalSummary({ sig }) {
  if (sig.status === "running")
    return <span className="muted-text">running…</span>;
  if (sig.status === "error") return <span className="down">error</span>;
  if (sig.status !== "done" || !sig.data)
    return <span className="muted-text">not run</span>;
  const m = sig.data.metrics.strategy;
  return (
    <>
      CAGR {fracPct(m.cagr)} · Sharpe {ratio(m.sharpe)} · Hit rate{" "}
      {fracPct(m.hit_rate)}
    </>
  );
}

function Report({ data }) {
  const rows = data.curves.dates.map((d, i) => ({
    date: d,
    strategy: data.curves.strategy[i],
    bh_basket: data.curves.bh_basket[i],
    bh_spy: data.curves.bh_spy[i],
    strategy_dd: data.curves.strategy_dd[i],
  }));

  return (
    <>
      <span className="asof">
        {data.start_date} → {data.end_date} · {data.n_days} days
      </span>

      <div className="panel" style={{ marginTop: 12 }}>
        <h2>Growth of $1 (log scale)</h2>
        <ResponsiveContainer width="100%" height={340}>
          <LineChart
            data={rows}
            margin={{ top: 8, right: 16, bottom: 8, left: 0 }}
          >
            <CartesianGrid strokeDasharray="3 3" stroke="#2a2f3a" />
            <XAxis dataKey="date" tick={{ fontSize: 11 }} minTickGap={60} />
            {/* Log scale: on a 5-year compounding chart a linear axis squashes
                the early years into an unreadable flat line. */}
            <YAxis
              scale="log"
              domain={["auto", "auto"]}
              tick={{ fontSize: 11 }}
              width={56}
            />
            <Tooltip
              contentStyle={{
                background: "#1a1d24",
                border: "1px solid #2a2f3a",
              }}
              labelStyle={{ color: "#aaa" }}
              formatter={(v) => v.toFixed(3)}
            />
            <Legend />
            {SERIES.map((s) => (
              <Line
                key={s.key}
                type="monotone"
                dataKey={s.key}
                name={s.name}
                stroke={s.stroke}
                strokeDasharray={s.dash}
                strokeWidth={s.width}
                dot={false}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>

      <div className="panel" style={{ marginTop: 16 }}>
        <h2>Strategy drawdown</h2>
        <ResponsiveContainer width="100%" height={180}>
          <AreaChart
            data={rows}
            margin={{ top: 8, right: 16, bottom: 8, left: 0 }}
          >
            <CartesianGrid strokeDasharray="3 3" stroke="#2a2f3a" />
            <XAxis dataKey="date" tick={{ fontSize: 11 }} minTickGap={60} />
            <YAxis tick={{ fontSize: 11 }} width={56} tickFormatter={fracPct} />
            <Tooltip
              contentStyle={{
                background: "#1a1d24",
                border: "1px solid #2a2f3a",
              }}
              labelStyle={{ color: "#aaa" }}
              formatter={(v) => fracPct(v)}
            />
            <Area
              type="monotone"
              dataKey="strategy_dd"
              stroke="#ef4444"
              fill="#ef444433"
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>

      <MetricsTable
        m={data.metrics}
        turnover={data.turnover}
        trades={data.trades}
      />
      <Heatmap monthly={data.monthly.strategy} />
      <SweepTable sweep={data.sweep} active={data.params} />
      <OosBlock oos={data.oos} />
      <Caveats items={data.caveats} />
    </>
  );
}

const ROWS = [
  ["CAGR", "cagr", fracPct],
  ["Volatility", "vol", fracPct],
  ["Sharpe", "sharpe", ratio],
  ["Sortino", "sortino", ratio],
  ["Max drawdown", "max_dd", fracPct],
  ["Calmar", "calmar", ratio],
  ["Hit rate", "hit_rate", fracPct],
  ["Best month", "best_month", fracPct],
  ["Worst month", "worst_month", fracPct],
];

function MetricsTable({ m, turnover, trades }) {
  return (
    <div className="panel" style={{ marginTop: 16 }}>
      <h2>Performance</h2>
      <table>
        <thead>
          <tr>
            <th>Metric</th>
            <th>Strategy</th>
            <th>Basket B&amp;H</th>
            <th>SPY B&amp;H</th>
          </tr>
        </thead>
        <tbody>
          {ROWS.map(([label, key, fmt]) => (
            <tr key={key}>
              <td>{label}</td>
              <td>{fmt(m.strategy[key])}</td>
              <td>{fmt(m.bh_basket[key])}</td>
              <td>{fmt(m.bh_spy[key])}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <h2 style={{ marginTop: 16 }}>Strategy vs benchmark</h2>
      <table>
        <thead>
          <tr>
            <th>Metric</th>
            <th>vs Basket B&amp;H</th>
            <th>vs SPY B&amp;H</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>Alpha (ann.)</td>
            <td>{fracPct(m.vs_basket.alpha)}</td>
            <td>{fracPct(m.vs_spy.alpha)}</td>
          </tr>
          <tr>
            <td>Beta</td>
            <td>{ratio(m.vs_basket.beta)}</td>
            <td>{ratio(m.vs_spy.beta)}</td>
          </tr>
          <tr>
            <td>Tracking error</td>
            <td>{fracPct(m.vs_basket.tracking_error)}</td>
            <td>{fracPct(m.vs_spy.tracking_error)}</td>
          </tr>
          <tr>
            <td>Information ratio</td>
            <td>{ratio(m.vs_basket.information_ratio)}</td>
            <td>{ratio(m.vs_spy.information_ratio)}</td>
          </tr>
        </tbody>
      </table>
      <p className="muted-text">
        Annual turnover: {ratio(turnover.annual)}× · Entries: {trades.entries} ·
        Sharpe and Sortino assume a 0% risk-free rate.
      </p>
    </div>
  );
}

const MONTHS = [
  "01",
  "02",
  "03",
  "04",
  "05",
  "06",
  "07",
  "08",
  "09",
  "10",
  "11",
  "12",
];

function Heatmap({ monthly }) {
  const years = [
    ...new Set(Object.keys(monthly).map((k) => k.slice(0, 4))),
  ].sort();
  const scale = Math.max(
    ...Object.values(monthly).map((v) => Math.abs(v)),
    0.01,
  );

  return (
    <div className="panel" style={{ marginTop: 16 }}>
      <h2>Monthly returns — strategy</h2>
      <div
        className="bt-heatmap"
        style={{ gridTemplateColumns: `48px repeat(12, 1fr)` }}
      >
        <div />
        {MONTHS.map((mo) => (
          <div key={mo} className="bt-hm-head">
            {mo}
          </div>
        ))}
        {years.map((y) => (
          <Row key={y} year={y} monthly={monthly} scale={scale} />
        ))}
      </div>
    </div>
  );
}

function Row({ year, monthly, scale }) {
  return (
    <>
      <div className="bt-hm-head">{year}</div>
      {MONTHS.map((mo) => {
        const v = monthly[`${year}-${mo}`];
        const alpha = v == null ? 0 : Math.min(Math.abs(v) / scale, 1) * 0.75;
        const bg =
          v == null
            ? "transparent"
            : v >= 0
              ? `rgba(34,197,94,${alpha})`
              : `rgba(239,68,68,${alpha})`;
        return (
          <div
            key={mo}
            className="bt-hm-cell"
            style={{ background: bg }}
            title={v == null ? "" : `${year}-${mo}: ${fracPct(v)}`}
          >
            {v == null ? "" : (v * 100).toFixed(1)}
          </div>
        );
      })}
    </>
  );
}

function SweepTable({ sweep, active }) {
  const isActive = (p) => JSON.stringify(p) === JSON.stringify(active);
  return (
    <div className="panel" style={{ marginTop: 16 }}>
      <h2>Parameter sweep</h2>
      <p className="muted-text">
        Not a search for the best setting. A rule that only works at one
        parameter value is a curve fit — this table is how you see that.
      </p>
      <table>
        <thead>
          <tr>
            <th>Params</th>
            <th>CAGR</th>
            <th>Sharpe</th>
            <th>Max DD</th>
          </tr>
        </thead>
        <tbody>
          {sweep.map((row, i) => (
            <tr key={i} className={isActive(row.params) ? "bt-active" : ""}>
              <td>
                {Object.entries(row.params)
                  .map(([k, v]) => `${k}=${v}`)
                  .join(" ")}
              </td>
              <td>{fracPct(row.cagr)}</td>
              <td>{ratio(row.sharpe)}</td>
              <td>{fracPct(row.max_dd)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function OosBlock({ oos }) {
  if (!oos.in_sample) {
    return (
      <div className="panel" style={{ marginTop: 16 }}>
        <h2>In / out of sample</h2>
        <p className="muted-text">Window too short to split.</p>
      </div>
    );
  }
  return (
    <div className="panel" style={{ marginTop: 16 }}>
      <h2>In / out of sample</h2>
      <p className="muted-text">
        Split at {oos.split_date}. An edge that appears only in-sample has not
        been validated out-of-sample.
      </p>
      <table>
        <thead>
          <tr>
            <th>Metric</th>
            <th>In-sample (60%)</th>
            <th>Out-of-sample (40%)</th>
          </tr>
        </thead>
        <tbody>
          {ROWS.map(([label, key, fmt]) => (
            <tr key={key}>
              <td>{label}</td>
              <td>{fmt(oos.in_sample[key])}</td>
              <td>{fmt(oos.out_sample[key])}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Caveats({ items }) {
  return (
    <div className="panel" style={{ marginTop: 16 }}>
      <h2>What this study does not prove</h2>
      <ul className="muted-text">
        {items.map((c, i) => (
          <li key={i} style={{ marginBottom: 8 }}>
            {c}
          </li>
        ))}
      </ul>
    </div>
  );
}
