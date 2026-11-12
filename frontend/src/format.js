export const money = (n) =>
  n?.toLocaleString("en-US", { style: "currency", currency: "USD" }) ?? "-";

/** Cash movements are in THB, not the USD the positions are priced in. */
export const baht = (n) =>
  n == null ? "-" : `฿${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

/** Axis labels: ฿150,000.00 is too wide to repeat down a Y axis. */
export const bahtShort = (n) =>
  n == null ? "" : Math.abs(n) >= 1000 ? `฿${Math.round(n / 1000)}k` : `฿${n}`;

/** Positions/trades are booked in USD. Converts to THB only when the
 *  dashboard currency switch is set to THB and a live rate is available. */
export const fromUsd = (n, currency, rate) =>
  currency === "THB" && rate ? baht(n * rate) : money(n);

/** Cash movements are booked in THB. Converts to USD only when the dashboard
 *  currency switch is set to USD and a live rate is available; otherwise
 *  shows the native THB the statement actually recorded. */
export const fromThb = (n, currency, rate) =>
  currency === "USD" && rate ? money(n / rate) : baht(n);

export const fromThbShort = (n, currency, rate) =>
  currency === "USD" && rate ? compact(n / rate) : bahtShort(n);

export const pct = (n) => (n == null ? "-" : `${n >= 0 ? "+" : ""}${n.toFixed(2)}%`);

export const signed = (n) =>
  n == null ? "-" : `${n >= 0 ? "+" : ""}${money(Math.abs(n)).replace("$", "$")}`;

export const cls = (n) => (n > 0 ? "up" : n < 0 ? "down" : "flat");

/** $4.54T / $62.4B / $18.2M — market caps and cash piles are unreadable in full. */
export const compact = (n) => {
  if (n == null) return "—";
  const neg = n < 0 ? "-" : "";
  const a = Math.abs(n);
  for (const [size, suffix] of [[1e12, "T"], [1e9, "B"], [1e6, "M"], [1e3, "K"]]) {
    if (a >= size) return `${neg}$${(a / size).toFixed(2)}${suffix}`;
  }
  return `${neg}$${a.toFixed(2)}`;
};

/** Yahoo reports margins, growth and yield as fractions (0.276 -> "27.6%").
 *  The ×100 lives here alone so no caller can double-apply it. */
export const fracPct = (n) =>
  n == null ? "—" : `${n >= 0 ? "" : "-"}${(Math.abs(n) * 100).toFixed(1)}%`;

/** A plain ratio (P/E, beta, current ratio). Never invents a value for null. */
export const ratio = (n) => (n == null ? "—" : n.toFixed(2));
