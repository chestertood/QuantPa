import { useState } from "react";

// Ticker-keyed logo CDN — no domain mapping or API key needed. Coverage is
// good but not total (a Shanghai listing like 688825 has none), so every logo
// falls back to a monogram rather than a broken-image icon.
const CDN = "https://financialmodelingprep.com/image-stock";

// "BRK B" is Webull's spelling; the CDN (and TradingView) use "BRK.B".
const cdnTicker = (symbol) => symbol.replace(/\s+/g, ".");

/** Stable hue per ticker, so a symbol keeps the same fallback colour across
 *  renders and reloads instead of flickering to a new one. */
function hueOf(symbol) {
  let h = 0;
  for (const ch of symbol) h = (h * 31 + ch.charCodeAt(0)) % 360;
  return h;
}

export default function StockLogo({ symbol, size = 40 }) {
  const [failed, setFailed] = useState(false);

  if (failed) {
    const h = hueOf(symbol);
    return (
      <div
        className="logo logo-fallback"
        style={{
          width: size,
          height: size,
          background: `hsl(${h} 42% 22%)`,
          color: `hsl(${h} 70% 72%)`,
          fontSize: size * 0.36,
        }}
        aria-hidden="true"
      >
        {symbol.slice(0, 2)}
      </div>
    );
  }

  return (
    <img
      className="logo"
      src={`${CDN}/${cdnTicker(symbol)}.png`}
      alt=""
      width={size}
      height={size}
      // 190 cards would otherwise fire 190 image requests on mount.
      loading="lazy"
      onError={() => setFailed(true)}
    />
  );
}
