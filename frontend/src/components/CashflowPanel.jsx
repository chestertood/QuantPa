import { useEffect, useState } from "react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  ResponsiveContainer,
  CartesianGrid,
} from "recharts";
import { getCashflow } from "../api";
import { fromThb, fromThbShort } from "../format";

const DEPOSIT = "#2fbf71";
const WITHDRAWAL = "#f0616d";

/** Deposits and withdrawals from the Webull statement PDFs: monthly totals as
 *  paired bars, then every individual movement underneath.
 *
 *  Unlike the rest of the dashboard this doesn't poll — the source is a folder
 *  of monthly PDFs, which cannot change while you're looking at the page.
 */
export default function CashflowPanel({ currency, rate }) {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  const baht = (n) => fromThb(n, currency, rate);
  const bahtShort = (n) => fromThbShort(n, currency, rate);

  useEffect(() => {
    let alive = true;
    getCashflow()
      .then((d) => alive && setData(d))
      .catch((e) => alive && setErr(e.message));
    return () => {
      alive = false;
    };
  }, []);

  if (err)
    return (
      <div className="panel cashflow">
        <h2>เงินฝาก / ถอน</h2>
        <div className="error">{err}</div>
      </div>
    );
  if (!data)
    return (
      <div className="panel cashflow">
        <h2>เงินฝาก / ถอน</h2>
        <div className="loading">กำลังอ่าน statement…</div>
      </div>
    );

  const { records, monthly, summary } = data;

  if (!records.length) {
    return (
      <div className="panel cashflow">
        <h2>เงินฝาก / ถอน</h2>
        <p className="muted-text">
          ยังไม่มี statement PDF — วางไฟล์ไว้ใน{" "}
          <code>backend/deposit_history/</code> แล้วรีเฟรช
        </p>
      </div>
    );
  }

  return (
    <div className="panel cashflow">
      <h2>
        เงินฝาก / ถอน <span className="count">{summary.record_count}</span>
      </h2>

      <div className="cf-summary">
        <Stat label="ฝากรวม" value={baht(summary.total_deposit)} tone="up" />
        <Stat
          label="ถอนรวม"
          value={baht(summary.total_withdrawal)}
          tone="down"
        />
        <Stat
          label="คงเหลือสุทธิ"
          value={baht(summary.net)}
          tone={summary.net >= 0 ? "up" : "down"}
        />
      </div>

      <ResponsiveContainer width="100%" height={260}>
        <BarChart
          data={monthly}
          margin={{ top: 8, right: 8, bottom: 0, left: 0 }}
        >
          <CartesianGrid
            strokeDasharray="3 3"
            stroke="#202636"
            vertical={false}
          />
          <XAxis
            dataKey="month"
            tick={{ fontSize: 11, fill: "#8892a6" }}
            tickLine={false}
          />
          <YAxis
            tickFormatter={bahtShort}
            tick={{ fontSize: 11, fill: "#8892a6" }}
            width={56}
            tickLine={false}
            axisLine={false}
          />
          <Tooltip
            cursor={{ fill: "#ffffff08" }}
            formatter={(v, name) => [baht(v), name]}
            contentStyle={{
              background: "#161b28",
              border: "1px solid #2c3448",
              borderRadius: 8,
            }}
            labelStyle={{ color: "#8892a6", marginBottom: 4 }}
          />
          <Legend
            wrapperStyle={{ fontSize: 12, paddingTop: 8 }}
            iconType="circle"
            iconSize={8}
          />
          <Bar
            dataKey="deposit"
            name="ฝาก"
            fill={DEPOSIT}
            radius={[3, 3, 0, 0]}
            maxBarSize={38}
          />
          <Bar
            dataKey="withdrawal"
            name="ถอน"
            fill={WITHDRAWAL}
            radius={[3, 3, 0, 0]}
            maxBarSize={38}
          />
        </BarChart>
      </ResponsiveContainer>

      <div className="scroll cf-scroll">
        <table>
          <thead>
            <tr>
              <th>วันที่</th>
              <th className="cf-type-col">ประเภท</th>
              <th>หมายเหตุ</th>
              <th>จำนวน</th>
            </tr>
          </thead>
          <tbody>
            {records.map((r, i) => {
              const dep = r.type === "deposit";
              return (
                <tr key={`${r.date}-${i}`} className="cf-row">
                  <td className="sym">{r.date}</td>
                  <td className="cf-type-col">
                    <span className={dep ? "up" : "down"}>
                      {dep ? "● ฝาก" : "○ ถอน"}
                    </span>
                  </td>
                  <td className="cf-remarks">{r.remarks || "—"}</td>
                  <td className={dep ? "up" : "down"}>
                    {dep ? "+" : "−"}
                    {baht(r.amount)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Stat({ label, value, tone }) {
  return (
    <div className="cf-stat">
      <div className="card-label">{label}</div>
      <div className={`cf-stat-value ${tone}`}>{value}</div>
    </div>
  );
}
