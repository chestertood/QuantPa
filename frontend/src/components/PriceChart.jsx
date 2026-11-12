import { useEffect, useState } from "react";
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
} from "recharts";
import { getHistory } from "../api";

export default function PriceChart({ symbol }) {
  const [points, setPoints] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    let alive = true;
    setPoints(null);
    setErr(null);
    getHistory(symbol)
      .then((d) => alive && setPoints(d.points))
      .catch((e) => alive && setErr(e.message));
    return () => {
      alive = false;
    };
  }, [symbol]);

  if (err) return <div className="error">chart: {err}</div>;
  if (!points) return <div className="loading">loading chart…</div>;

  return (
    <ResponsiveContainer width="100%" height={320}>
      <LineChart data={points} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#2a2f3a" />
        <XAxis dataKey="date" tick={{ fontSize: 11 }} minTickGap={40} />
        <YAxis domain={["auto", "auto"]} tick={{ fontSize: 11 }} width={56} />
        <Tooltip
          contentStyle={{ background: "#1a1d24", border: "1px solid #2a2f3a" }}
          labelStyle={{ color: "#aaa" }}
        />
        <Line type="monotone" dataKey="close" stroke="#4ea1ff" dot={false} strokeWidth={2} />
      </LineChart>
    </ResponsiveContainer>
  );
}
