import { useEffect, useState } from "react";
import { getFundamentals } from "../api";
import { money, compact, fracPct, ratio, cls } from "../format";

/** Fundamental metrics for the symbol on screen.
 *
 *  Every value is Yahoo's, rendered as sent. Yahoo's fundamentals have real
 *  gaps and occasional bad values, so a missing metric shows "—" rather than a
 *  zero or a derived stand-in, and the panel names its source.
 */
export default function Fundamentals({ symbol, price }) {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    let alive = true;
    setData(null);
    setErr(null);
    getFundamentals(symbol)
      .then((d) => alive && setData(d))
      .catch((e) => alive && setErr(e.message));
    return () => {
      alive = false;
    };
  }, [symbol]);

  if (err) {
    return (
      <div className="panel fundamentals">
        <p className="muted-text">ไม่มีข้อมูลพื้นฐานสำหรับ {symbol}</p>
      </div>
    );
  }
  if (!data) return <div className="panel fundamentals"><div className="loading">กำลังโหลดข้อมูลพื้นฐาน…</div></div>;

  const { valuation: v, profitability: p, health: h, trading: t } = data;

  return (
    <div className="fund-wrap">
      <Group title="มูลค่า">
        <Metric label="Market Cap" value={compact(v.market_cap)} />
        <Metric label="Enterprise Value" value={compact(v.enterprise_value)} />
        <Metric label="P/E (TTM)" value={ratio(v.pe_trailing)} />
        <Metric label="P/E (Forward)" value={ratio(v.pe_forward)} />
      </Group>

      <Group title="ความสามารถทำกำไร">
        <Metric label="ROE" value={fracPct(p.roe)} tone={cls(p.roe)} />
        <Metric label="Profit Margin" value={fracPct(p.profit_margin)} tone={cls(p.profit_margin)} />
        <Metric label="Gross Margin" value={fracPct(p.gross_margin)} />
        <Metric label="Operating Margin" value={fracPct(p.operating_margin)} tone={cls(p.operating_margin)} />
        <Metric label="Revenue Growth" value={fracPct(p.revenue_growth)} tone={cls(p.revenue_growth)} />
        <Metric label="Earnings Growth" value={fracPct(p.earnings_growth)} tone={cls(p.earnings_growth)} />
      </Group>

      <Group title="สุขภาพการเงิน">
        <Metric label="Debt / Equity" value={ratio(h.debt_to_equity)} />
        <Metric label="Current Ratio" value={ratio(h.current_ratio)} />
        <Metric label="Quick Ratio" value={ratio(h.quick_ratio)} />
        <Metric label="Total Cash" value={compact(h.total_cash)} />
        <Metric label="Free Cash Flow" value={compact(h.free_cashflow)} tone={cls(h.free_cashflow)} />
      </Group>

      <Group title="ราคา & นักวิเคราะห์">
        <Week52 low={t.week52_low} high={t.week52_high} price={price} />
        <Metric label="Beta" value={ratio(t.beta)} />
        <Metric label="Dividend Yield" value={fracPct(t.dividend_yield)} />
        <Metric label="ราคาเป้าหมายเฉลี่ย" value={t.target_mean == null ? "—" : money(t.target_mean)} />
        <Recommendation value={t.recommendation} count={t.analyst_count} />
      </Group>

      <p className="fund-source">ข้อมูล: {data.source}</p>
    </div>
  );
}

function Group({ title, children }) {
  return (
    <div className="panel fund-group">
      <h2>{title}</h2>
      <div className="fund-metrics">{children}</div>
    </div>
  );
}

function Metric({ label, value, tone }) {
  return (
    <div className="fund-metric">
      <span className="fund-label">{label}</span>
      <span className={`fund-value ${tone || ""}`}>{value}</span>
    </div>
  );
}

/** Two numbers don't show where the price actually sits in its year; the bar
 *  does it at a glance. */
function Week52({ low, high, price }) {
  if (low == null || high == null) {
    return <Metric label="52W Range" value="—" />;
  }
  const span = high - low;
  const pos = price == null || span <= 0
    ? null
    : Math.min(100, Math.max(0, ((price - low) / span) * 100));

  return (
    <div className="fund-metric fund-52w">
      <span className="fund-label">52W Range</span>
      <div className="w52">
        <div className="w52-track">
          {pos != null && <div className="w52-dot" style={{ left: `${pos}%` }} />}
        </div>
        <div className="w52-ends">
          <span>{money(low)}</span>
          <span>{money(high)}</span>
        </div>
      </div>
    </div>
  );
}

const REC_LABEL = {
  strong_buy: "ซื้ออย่างยิ่ง",
  buy: "ซื้อ",
  hold: "ถือ",
  sell: "ขาย",
  strong_sell: "ขายอย่างยิ่ง",
  underperform: "ต่ำกว่าตลาด",
  outperform: "เหนือตลาด",
};
const REC_TONE = {
  strong_buy: "up", buy: "up", outperform: "up",
  hold: "flat",
  sell: "down", strong_sell: "down", underperform: "down",
};

function Recommendation({ value, count }) {
  if (!value) return <Metric label="คำแนะนำ" value="—" />;
  return (
    <div className="fund-metric">
      <span className="fund-label">
        คำแนะนำ{count ? ` (${count} ราย)` : ""}
      </span>
      <span className={`rec-badge ${REC_TONE[value] || "flat"}`}>
        {REC_LABEL[value] || value}
      </span>
    </div>
  );
}
