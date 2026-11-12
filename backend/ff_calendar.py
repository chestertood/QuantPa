"""ForexFactory economic calendar, high-impact ("red") events.

forexfactory.com/calendar itself 403s plain HTTP clients (Cloudflare). FF also
publishes the same calendar as JSON for its own widgets, unauthenticated, no
bot-block — that's the feed used here instead of scraping HTML.
Run: python ff_calendar.py [thisweek|nextweek|today]
"""
import sys
from datetime import datetime, timedelta, timezone

_TZ7 = timezone(timedelta(hours=7))  # ICT/WIB — no zoneinfo lookup needed

from curl_cffi import requests

_FEED = "https://nfs.faireconomy.media/ff_calendar_{period}.json"


def fetch_calendar(period: str = "thisweek") -> list[dict]:
    """Raw events for the period: today | thisweek | nextweek."""
    r = requests.get(_FEED.format(period=period), impersonate="chrome", timeout=15)
    r.raise_for_status()
    return r.json()


def high_impact(events: list[dict]) -> list[dict]:
    """"Red folder" events only."""
    return [e for e in events if e.get("impact") == "High"]


def as_row(e: dict) -> dict:
    """Map a raw feed event to the Date/Time/Currency/Impact/... columns FF
    shows on the calendar page."""
    dt = datetime.fromisoformat(e["date"]).astimezone(_TZ7)
    return {
        "Date": dt.strftime("%Y-%m-%d"),
        "Time": dt.strftime("%I:%M %p").lstrip("0"),
        "Currency": e.get("country", ""),
        "Impact": e.get("impact", ""),
        "Detail": e.get("title", ""),
        "Actual": e.get("actual", "") or "",
        "Forecast": e.get("forecast", "") or "",
        "Previous": e.get("previous", "") or "",
    }


def _print_table(rows: list[dict]) -> None:
    if not rows:
        print("no events")
        return
    cols = list(rows[0].keys())
    widths = {c: max(len(c), *(len(str(r[c])) for r in rows)) for c in cols}
    print("  ".join(c.ljust(widths[c]) for c in cols))
    for r in rows:
        print("  ".join(str(r[c]).ljust(widths[c]) for c in cols))


if __name__ == "__main__":
    period = sys.argv[1] if len(sys.argv) > 1 else "thisweek"
    events = fetch_calendar(period)
    rows = [as_row(e) for e in high_impact(events)]
    _print_table(rows)
