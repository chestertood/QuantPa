/** Marks a price you shouldn't trust: no quote at all, or a feed that froze
 *  while the market was open (Yahoo does this, without flagging it). Naming the
 *  age matters — "-6.70%" looks like a real number until you know it's 2h old. */
export default function StaleMark({ ageS }) {
  const how =
    ageS == null
      ? "no live quote"
      : ageS < 120
        ? `quote ${ageS}s old`
        : `quote frozen ${Math.round(ageS / 60)} min — market open, feed not updating`;
  return (
    <span className="stale" title={how}>
      {" "}
      ⚠
    </span>
  );
}
