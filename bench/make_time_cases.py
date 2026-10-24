"""Write bench/time_cases.json: pasted challenge texts and the correct opening time.

    python bench/make_time_cases.py

The expected opening is computed here from the local time and its IANA zone, not
typed by hand, so the answer key does not depend on anyone's clock arithmetic.
Every opening is in the future (Oct 28, 2026 or later). PT switches from PDT
(UTC-7) to PST (UTC-8) on Nov 1, 2026; several cases sit on either side of it.
"""
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

PT, ET, UTC = "America/Los_Angeles", "America/New_York", "UTC"

# id, user's time zone, pasted text, opening (local, zone) of the strictest window
CASES = [
    ("t01", "Asia/Tokyo",
     "Weekend Challenge: Build a Tool. Entries open November 6, 2026 at 12:00 AM PT and close November 9, 2026 at 1:00 PM PT.",
     ("2026-11-06 00:00", PT)),
    ("t02", "Asia/Tokyo",
     "Submissions open October 30, 2026 at 9:00 AM PT. The deadline is November 2, 2026 at 11:59 PM PT.",
     ("2026-10-30 09:00", PT)),
    ("t03", "America/New_York",
     "Challenge window: opens 2026-11-13 00:00 UTC, closes 2026-11-16 23:59 UTC.",
     ("2026-11-13 00:00", UTC)),
    ("t04", "Europe/London",
     "October 31, 2026 · 12:00 AM PDT – November 2, 2026 · 11:59 PM PST",
     ("2026-10-31 00:00", PT)),
    ("t05", "Asia/Tokyo",
     "受付期間: 2026年11月20日 10:00 JST 〜 2026年11月23日 23:59 JST",
     ("2026-11-20 10:00", "Asia/Tokyo")),
    ("t06", "Asia/Tokyo",
     "The challenge opens at noon Pacific on December 4, 2026 and runs for one week, closing December 11, 2026 at noon Pacific.",
     ("2026-12-04 12:00", PT)),
    ("t07", "Asia/Tokyo",
     "Entries open November 27, 2026 at 11:30 PM PT and close November 30, 2026 at 11:59 PM PT.",
     ("2026-11-27 23:30", PT)),
    ("t08", "Asia/Tokyo",
     "The Weekend Challenge runs from Friday, November 13, 2026 at 00:00 PT to Monday, November 16, 2026 at 13:00 PT.",
     ("2026-11-13 00:00", PT)),
    ("t09", "America/Los_Angeles",
     "Opens 5 December 2026, 09:00 CET. Closes 7 December 2026, 18:00 CET.",
     ("2026-12-05 09:00", "Europe/Paris")),
    ("t10", "Asia/Tokyo",
     "Challenge page: Entries open November 10, 2026 at 12:00 AM PT and close November 12, 2026 at 11:59 PM PT.\n\n"
     "Terms and Conditions: The Submission Period begins November 10, 2026 at 9:00 AM PT and ends November 12, 2026 at 11:59 PM PT.",
     ("2026-11-10 09:00", PT)),
    ("t11", "Asia/Tokyo",
     "Opens Nov 18, 2026 at 3:00 PM ET. Closes Nov 20, 2026 at 3:00 PM ET.",
     ("2026-11-18 15:00", ET)),
    ("t12", "Asia/Kolkata",
     "The challenge starts January 8, 2027 at 10:00 AM PST and ends January 11, 2027 at 10:00 AM PST.",
     ("2027-01-08 10:00", PT)),
    ("t13", "Asia/Tokyo",
     "Entries open October 28, 2026 at 5:00 PM PDT and close October 31, 2026 at 5:00 PM PDT.",
     ("2026-10-28 17:00", PT)),
    ("t14", "Asia/Tokyo",
     "Opens 21 Nov 2026, 18:00 IST. Closes 24 Nov 2026, 18:00 IST.",
     ("2026-11-21 18:00", "Asia/Kolkata")),
    ("t15", "Australia/Sydney",
     "The entry window opens December 1, 2026 at 12:00 AM UTC and closes December 3, 2026 at 11:59 PM UTC.",
     ("2026-12-01 00:00", UTC)),
    ("t16", "Asia/Tokyo",
     "Kicks off November 3, 2026 at 8 AM Pacific. Last day to post is November 5, 2026 (11:59 PM Pacific).",
     ("2026-11-03 08:00", PT)),
]


def utc(local: str, zone: str) -> str:
    d = datetime.strptime(local, "%Y-%m-%d %H:%M").replace(tzinfo=ZoneInfo(zone))
    return d.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ")


out = [{"id": i, "user_tz": tz, "text": text, "opens_utc": utc(*o)} for i, tz, text, o in CASES]
Path(__file__).with_name("time_cases.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n")
for c in out:
    print(c["id"], c["opens_utc"])
