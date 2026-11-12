"""Econ/market news, scored for relevance to the portfolio.

Headlines come from CNBC + Yahoo RSS (stdlib XML parse, over market.py's
curl_cffi session — plain requests get 429'd same as quotes). Impact is
decided by a fixed keyword -> sector rule table, not an LLM: free,
deterministic, and every rule is one line to read or tune.
# ponytail: keyword rules, not an LLM classifier. Misses novel phrasing and
# doesn't catch a bare company name ("Nvidia rallies") without a rule for it.
# Swap _match() for an LLM call later if that ceiling matters.
"""
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime

import market

_TTL = 300.0  # seconds
_cache: tuple[float, list[dict]] | None = None

_FEEDS = {
    "CNBC Economy": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=20910258",
    "CNBC Finance": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000664",
    "CNBC Top News": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114",
    "Yahoo Finance": "https://finance.yahoo.com/news/rssindex",
}

# Older than this drops out — kills Yahoo's evergreen filler ("10 best
# checking accounts") which carries no pubDate discipline.
_MAX_AGE_S = 48 * 3600

# (title regex, {Yahoo sector name: +1 tailwind / -1 headwind}, why)
_RULES = [
    (r"\brate cut|fed cuts|fomc.*cut", {"Financial Services": -1, "Real Estate": 1, "Technology": 1}, "lower rates"),
    (r"\brate hike|fed hikes|raises rates", {"Financial Services": 1, "Real Estate": -1, "Technology": -1}, "higher rates"),
    (r"\bfed (holds|pauses|keeps)|fomc.*(hold|pause)", {}, "Fed on hold"),
    (r"\binflation (cools|eases|slows)|cpi.*(cooler|below|miss)", {"Technology": 1, "Consumer Cyclical": 1}, "inflation cooling"),
    (r"\binflation (rises|hot|accelerat)|cpi.*(hot|above|surprise)", {"Technology": -1, "Consumer Cyclical": -1}, "inflation hot"),
    (r"\bjobs report|nonfarm payroll|unemployment", {}, "labor data"),
    (r"\boil (surge|jump|rise|climb)|opec.*(cut|hike)", {"Energy": 1, "Industrials": -1, "Consumer Cyclical": -1}, "oil move"),
    (r"\boil (fall|drop|plunge|slump)", {"Energy": -1}, "oil down"),
    (r"\btariff|trade war|trade deal", {"Industrials": -1, "Technology": -1}, "trade policy"),
    (r"\bgdp\b|economic growth|economy (grew|slowed|contracted)", {}, "growth data"),
    (r"\bbank (earnings|profit)s?\b|goldman|jpmorgan|morgan stanley", {"Financial Services": 1}, "bank earnings"),
    (r"\bchip|semiconductor|nvidia|amd\b", {"Technology": 1}, "chip sector news"),
    (r"\brecession", {}, "recession risk"),
    (r"\bdollar (strength|weak|surge|slump)", {}, "dollar move"),
    (r"\bhousing (start|market|price)|mortgage rate", {"Real Estate": 1}, "housing data"),
    (r"\bearnings (beat|miss|season)", {}, "earnings"),
    (r"\bipo\b", {}, "IPO news"),
    (r"\bcrypto|bitcoin", {}, "crypto move"),
    (r"\bopec", {"Energy": 1}, "OPEC decision"),
    (r"\bconsumer (spending|confidence)", {"Consumer Cyclical": 1}, "consumer data"),
]
_COMPILED = [(re.compile(p, re.I), sectors, why) for p, sectors, why in _RULES]


def _parse_date(raw: str) -> float | None:
    """CNBC uses RFC822 ("Fri, 31 Jul 2026 ..."), Yahoo uses ISO 8601."""
    if not raw:
        return None
    try:
        return parsedate_to_datetime(raw).timestamp()
    except (TypeError, ValueError):
        pass
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _fetch_feed(source: str, url: str) -> list[dict]:
    r = market._session().get(url, timeout=15)
    r.raise_for_status()
    root = ET.fromstring(r.content)
    items = []
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        ts = _parse_date(item.findtext("pubDate") or "")
        if not title or ts is None:
            continue
        items.append({
            "title": title,
            "link": (item.findtext("link") or "").strip(),
            "source": source,
            "ts": ts,
        })
    return items


def _match(title: str):
    """First rule whose pattern hits the title, or None."""
    low = title.lower()
    for pattern, sectors, why in _COMPILED:
        if pattern.search(low):
            return sectors, why
    return None


def get_news(holdings_by_sector: dict[str, list[dict]] | None = None) -> list[dict]:
    """Ranked headlines: rule-matched, under 48h old, most relevant first.

    `holdings_by_sector` maps a Yahoo sector name (e.g. "Technology") to the
    portfolio symbols in it, each {"symbol", "weight_pct"} — so a headline
    can be flagged against your actual book. Pass None for sector-only impact.
    """
    global _cache
    now = time.time()
    if _cache and now - _cache[0] < _TTL:
        raw = _cache[1]
    else:
        raw = []
        for source, url in _FEEDS.items():
            try:
                raw.extend(_fetch_feed(source, url))
            except Exception:
                continue  # one feed down doesn't blank the page
        _cache = (now, raw)

    holdings_by_sector = holdings_by_sector or {}
    out = []
    for item in raw:
        age_s = now - item["ts"]
        if age_s > _MAX_AGE_S:
            continue
        matched = _match(item["title"])
        if matched is None:
            continue
        sectors, why = matched

        holdings = []
        for sector, direction in sectors.items():
            for h in holdings_by_sector.get(sector, []):
                holdings.append({"symbol": h["symbol"], "weight_pct": h["weight_pct"], "dir": direction})
        holdings.sort(key=lambda h: -h["weight_pct"])

        score = len(holdings) * 2 + (1 if sectors else 0) - age_s / (6 * 3600)
        out.append({
            "title": item["title"],
            "link": item["link"],
            "source": item["source"],
            "age_s": max(0, round(age_s)),
            "why": why,
            "sectors": [{"name": s, "dir": d} for s, d in sectors.items()],
            "holdings": holdings,
            "score": round(score, 2),
        })

    out.sort(key=lambda x: -x["score"])
    return out
