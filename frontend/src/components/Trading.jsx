import { useState } from "react";
import { getEconCalendar, usePolled } from "../api";
import TradingViewChart from "./TradingViewChart.jsx";

export default function Trading() {
  const [symbol, setSymbol] = useState("AAPL");
  const { data, err } = usePolled(getEconCalendar, 60000);
  const today = new Date().toISOString().slice(0, 10);

  return (
    <>
      <header>
        <h1>Trading</h1>
      </header>
      {/* calc, not a fixed px height, so the row fits one screen instead of
          pushing the whole page into a scroll (header ~150px above it). */}
      <div style={{ display: "flex", gap: 16, alignItems: "stretch", height: "calc(100vh - 150px)" }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <TradingViewChart symbol={symbol} height="100%" />
        </div>
        <div className="panel trading-econ" style={{ width: 380, flexShrink: 0 }}>
          <h2>Econ calendar — high impact</h2>
          {err && <div className="error">{err}</div>}
          {!data && !err && <div className="loading">Loading…</div>}
          <div className="econ-cal">
            {data?.events?.map((e, i) => {
              const isToday = e.Date === today;
              return (
                <div key={i} className={`econ-event${isToday ? " today" : ""}`}>
                  <div className="econ-event-top">
                    <span>
                      {isToday ? "Today" : e.Date} · {e.Time}
                    </span>
                  </div>
                  <div className="econ-event-title">
                    <span className="econ-ccy">{e.Currency}</span>
                    {e.Detail}
                  </div>
                  <div className="econ-event-fp">
                    Actual <b>{e.Actual || "—"}</b> · Forecast{" "}
                    <b>{e.Forecast || "—"}</b> · Previous{" "}
                    <b>{e.Previous || "—"}</b>
                  </div>
                </div>
              );
            })}
          </div>
          {data && !data.events?.length && (
            <p className="muted-text">No high-impact events this week.</p>
          )}
        </div>
      </div>
    </>
  );
}
