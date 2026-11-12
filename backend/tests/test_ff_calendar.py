"""Self-check for ff_calendar: filtering + row mapping, no network. Run:
python test_ff_calendar.py
"""
import ff_calendar as fc

_RAW = [
    {"title": "Non-Farm Employment Change", "country": "USD", "date": "2026-08-07T12:30:00+00:00",
     "impact": "High", "actual": "", "forecast": "180K", "previous": "206K"},
    {"title": "Sentix Investor Confidence", "country": "EUR", "date": "2026-08-10T08:30:00+00:00",
     "impact": "Low", "actual": None, "forecast": None, "previous": "5.0"},
    {"title": "FOMC Statement", "country": "USD", "date": "2026-08-12T18:00:00+00:00",
     "impact": "High", "actual": None, "forecast": None, "previous": None},
]


def test_high_impact_filters_by_folder_color():
    out = fc.high_impact(_RAW)
    assert [e["title"] for e in out] == ["Non-Farm Employment Change", "FOMC Statement"]


def test_as_row_maps_columns_and_blanks_missing():
    row = fc.as_row(_RAW[0])
    assert row["Currency"] == "USD"
    assert row["Impact"] == "High"
    assert row["Detail"] == "Non-Farm Employment Change"
    assert row["Forecast"] == "180K"
    assert row["Time"] == "7:30 PM"  # 12:30 UTC + 7

    row2 = fc.as_row(_RAW[2])
    assert row2["Actual"] == "" and row2["Forecast"] == "" and row2["Previous"] == ""


if __name__ == "__main__":
    test_high_impact_filters_by_folder_color()
    test_as_row_maps_columns_and_blanks_missing()
    print("ok")
