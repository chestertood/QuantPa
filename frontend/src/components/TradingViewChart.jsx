import { useEffect, useRef } from "react";

// TradingView Advanced Chart widget. Loads tv.js once, re-inits on symbol change.
let tvScriptPromise = null;

function loadTv() {
  if (tvScriptPromise) return tvScriptPromise;
  tvScriptPromise = new Promise((resolve) => {
    if (window.TradingView) return resolve();
    const s = document.createElement("script");
    s.src = "https://s3.tradingview.com/tv.js";
    s.async = true;
    s.onload = () => resolve();
    document.head.appendChild(s);
  });
  return tvScriptPromise;
}

export default function TradingViewChart({ symbol, height = 480 }) {
  const ref = useRef(null);
  const containerId = "tv_chart_container";

  useEffect(() => {
    let cancelled = false;
    loadTv().then(() => {
      if (cancelled || !ref.current || !window.TradingView) return;
      ref.current.innerHTML = "";
      // eslint-disable-next-line no-new
      new window.TradingView.widget({
        container_id: containerId,
        // bare ticker (no EXCHANGE: prefix) resolves to a delayed/generic feed, not realtime
        symbol: symbol.includes(":") ? symbol : `NASDAQ:${symbol}`,
        interval: "D",
        theme: "dark",
        style: "1",
        locale: "en",
        autosize: true,
        hide_side_toolbar: false,
        allow_symbol_change: true,
      });
    });
    return () => {
      cancelled = true;
    };
  }, [symbol]);

  return <div id={containerId} ref={ref} style={{ height, width: "100%" }} />;
}
