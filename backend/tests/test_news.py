"""Self-check for news.get_news: RSS date parsing (both feed formats), the
rule-match/age filter, and portfolio-holdings scoring. Stubs the feed fetch,
so it makes no network calls. Run: python test_news.py
"""
import time

import news


def _item(title, age_s, source="Test Feed"):
    return {"title": title, "link": f"http://x/{title[:6]}", "source": source, "ts": time.time() - age_s}


def test_date_parsing_handles_both_feed_formats():
    cnbc = news._parse_date("Fri, 31 Jul 2026 16:51:30 GMT")
    yahoo = news._parse_date("2026-08-01T06:03:00Z")
    assert cnbc is not None and yahoo is not None
    assert yahoo > cnbc, "Aug 1 must parse later than Jul 31"


def test_unmatched_headline_is_dropped():
    news._cache = (time.time(), [_item("10 best free checking accounts", 3600)])
    out = news.get_news()
    assert out == [], f"no rule matches this headline, expected empty: {out}"


def test_old_headline_is_dropped_even_if_matched():
    news._cache = (time.time(), [_item("Fed cuts rates by 25bps", 49 * 3600)])
    out = news.get_news()
    assert out == [], f"49h old must be dropped by the 48h cutoff: {out}"


def test_matched_recent_headline_scores_sectors():
    news._cache = (time.time(), [_item("Fed cuts rates in surprise move", 600)])
    out = news.get_news()
    assert len(out) == 1, out
    item = out[0]
    assert item["why"] == "lower rates", item
    names = {s["name"] for s in item["sectors"]}
    assert "Financial Services" in names and "Technology" in names, item["sectors"]
    assert item["holdings"] == [], "no portfolio passed in, must not fabricate holdings"


def test_holding_in_hit_sector_is_attached_and_ranked_first():
    news._cache = (
        time.time(),
        [
            _item("Fed cuts rates in surprise move", 600),  # touches Financial Services
            _item("China factory activity contracts", 300),  # matches no rule -> dropped
            _item("GDP growth slows to 1.5%", 300),  # matches, no sector
        ],
    )
    holdings = {"Financial Services": [{"symbol": "GS", "weight_pct": 12.5}]}
    out = news.get_news(holdings)
    assert [i["title"][:8] for i in out] == ["Fed cuts", "GDP grow"], out
    assert out[0]["holdings"] == [{"symbol": "GS", "weight_pct": 12.5, "dir": -1}], out[0]


if __name__ == "__main__":
    test_date_parsing_handles_both_feed_formats()
    test_unmatched_headline_is_dropped()
    test_old_headline_is_dropped_even_if_matched()
    test_matched_recent_headline_scores_sectors()
    test_holding_in_hit_sector_is_attached_and_ranked_first()
    print("ok")
