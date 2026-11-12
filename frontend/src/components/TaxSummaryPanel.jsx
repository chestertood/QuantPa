import { useEffect, useState } from "react";
import { getTaxSummary } from "../api";
import { fromUsd, fromThb, cls } from "../format";

/** Raw figures pulled from the statement PDFs, for handing to an accountant —
 *  not a tax calculation. Thai personal income tax on foreign-sourced income
 *  depends on total income, deductions, and residency rules that live nowhere
 *  in a brokerage statement, so this deliberately stops short of a "you owe
 *  ฿X" number. See the disclaimer banner, which is not decoration.
 */
export default function TaxSummaryPanel({ currency, rate }) {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  const [expanded, setExpanded] = useState(false);
  const usd = (n) => fromUsd(n, currency, rate);
  const thb = (n) => fromThb(n, currency, rate);

  useEffect(() => {
    let alive = true;
    getTaxSummary()
      .then((d) => alive && setData(d))
      .catch((e) => alive && setErr(e.message));
    return () => {
      alive = false;
    };
  }, []);

  if (err) return <div className="panel taxsum"><h2>ข้อมูลสำหรับยื่นภาษี</h2><div className="error">{err}</div></div>;
  if (!data) return <div className="panel taxsum"><h2>ข้อมูลสำหรับยื่นภาษี</h2><div className="loading">กำลังอ่าน statement…</div></div>;

  const y = data.yearly[data.yearly.length - 1]; // most recent year
  const trades = expanded ? data.realized_trades : data.realized_trades.slice(0, 8);

  if (!y) {
    return (
      <div className="panel taxsum">
        <h2>ข้อมูลสำหรับยื่นภาษี</h2>
        <p className="muted-text">ยังไม่มีข้อมูลจาก statement PDF</p>
      </div>
    );
  }

  return (
    <div className="panel taxsum">
      <h2>ข้อมูลสำหรับยื่นภาษี — {y.year}</h2>

      <div className="tax-disclaimer">
        ⚠ {data.note}
      </div>

      <div className="tax-grid">
        <TaxStat
          label="กำไรขาดทุนจากการขาย (Realized)"
          value={usd(y.realized_pl_usd)}
          sub="จับคู่ FIFO จากรายการซื้อขายจริง"
          tone={cls(y.realized_pl_usd)}
        />
        <TaxStat
          label="เงินปันผลรับ"
          value={thb(y.dividend_thb)}
        />
        <TaxStat
          label="ดอกเบี้ยรับสุทธิ"
          value={thb(y.interest_thb + y.interest_wht_thb)}
          sub={`ก่อนหัก ${thb(y.interest_thb)} · WHT ${thb(y.interest_wht_thb)}`}
        />
        <TaxStat
          label="ค่าธรรมเนียม/VAT รวม"
          value={thb(y.fee_thb)}
          sub="Comm/Fee/Tax + VAT ทุกรายการ"
        />
        <TaxStat
          label="เงินโอนเข้าไทย"
          value={thb(y.withdrawn_to_thailand_thb)}
          sub="ยอด withdrawal ทั้งปี"
        />
      </div>

      {data.realized_trades.length > 0 && (
        <>
          <h3 className="tax-subhead">รายการที่ขายจริง (matched FIFO)</h3>
          <div className="scroll">
            <table>
              <thead>
                <tr>
                  <th>วันที่ขาย</th>
                  <th className="cf-type-col">สัญลักษณ์</th>
                  <th>จำนวนหุ้น</th>
                  <th>กำไร/ขาดทุน</th>
                </tr>
              </thead>
              <tbody>
                {trades.map((t, i) => (
                  <tr key={`${t.symbol}-${t.date}-${i}`} className="cf-row">
                    <td className="sym">{t.date}</td>
                    <td className="cf-type-col sym">{t.symbol}</td>
                    <td>{t.quantity}</td>
                    <td className={cls(t.pl)}>{usd(t.pl)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {data.realized_trades.length > 8 && (
            <button className="back-btn tax-more" onClick={() => setExpanded((v) => !v)}>
              {expanded ? "แสดงน้อยลง" : `ดูทั้งหมด (${data.realized_trades.length})`}
            </button>
          )}
        </>
      )}
    </div>
  );
}

function TaxStat({ label, value, sub, tone }) {
  return (
    <div className="cf-stat">
      <div className="card-label">{label}</div>
      <div className={`cf-stat-value ${tone || ""}`}>{value}</div>
      {sub && <div className="tax-stat-sub">{sub}</div>}
    </div>
  );
}
