"""Tests for the code that decides WHEN. No AWS, no model.
Run: .venv/bin/python -m pytest -q  (or: .venv/bin/python test_remind.py)
"""
import os
from datetime import datetime, timedelta, timezone

os.environ.setdefault("REMIND_TOPIC_ARN", "arn:aws:sns:us-east-1:000000000000:t")
os.environ.setdefault("REMIND_SCHEDULER_ROLE_ARN", "arn:aws:iam::000000000000:role/r")

from remind import book, schedule_name  # noqa: E402


class Conflict(Exception):
    pass


class FakeScheduler:
    class exceptions:
        ConflictException = Conflict

    def __init__(self):
        self.made = {}

    def create_schedule(self, **kw):
        if kw["Name"] in self.made:
            raise Conflict()
        self.made[kw["Name"]] = kw


NOW = datetime(2026, 10, 23, 9, 0, tzinfo=timezone.utc)
OPENS = NOW + timedelta(minutes=5)
CLOSES = NOW + timedelta(days=3)


def test_books_one_minute_after_opening():
    c = FakeScheduler()
    r = book(OPENS, CLOSES, "open", "Asia/Tokyo", now=NOW, client=c)
    assert r.startswith("BOOKED") and "18:06" in r
    s = c.made[schedule_name(OPENS)]
    assert s["ScheduleExpression"] == "at(2026-10-23T09:06:00)"
    assert s["ScheduleExpressionTimezone"] == "UTC"
    assert s["ActionAfterCompletion"] == "DELETE"


def test_second_request_does_not_book_twice():
    c = FakeScheduler()
    book(OPENS, CLOSES, "open", now=NOW, client=c)
    assert book(OPENS, CLOSES, "open", now=NOW, client=c).startswith("ALREADY BOOKED")
    assert len(c.made) == 1


def test_refuses_when_already_open_or_no_start():
    c = FakeScheduler()
    assert book(NOW - timedelta(minutes=1), CLOSES, "x", now=NOW, client=c).startswith("NOT BOOKED")
    assert book(None, CLOSES, "x", now=NOW, client=c).startswith("NOT BOOKED")
    assert book(OPENS, OPENS + timedelta(seconds=30), "x", now=NOW, client=c).startswith("NOT BOOKED")
    assert c.made == {}


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
