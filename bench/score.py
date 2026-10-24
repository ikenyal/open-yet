"""Count the saved results. No model call, no AWS.

    python bench/score.py
"""
import json
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).parent


def decide():
    rows = json.loads((HERE / "raw-decide.json").read_text())
    pos = [r for r in rows if r["expect_book"]]
    neg = [r for r in rows if not r["expect_book"]]
    print(f"decide: {len(rows)} runs ({len({r['repeat'] for r in rows})} repeats)")
    print(f"  should book:     booked {sum(r['booked'] for r in pos)}/{len(pos)}"
          f"  (missed: {sorted({(r['situation'], r['request']) for r in pos if not r['booked']})})")
    print(f"  should not book: booked {sum(r['booked'] for r in neg)}/{len(neg)}"
          f"  (wrong: {sorted({(r['situation'], r['request']) for r in neg if r['booked']})})")
    called = [r for r in neg if r["called_tool"]]
    print(f"  should not book, but the agent called the tool anyway: {len(called)}/{len(neg)}"
          f" -> refused by code: {sum(not r['booked'] for r in called)}")
    print("    by situation:", dict(Counter(r["situation"] for r in called)))


def time(name="raw-time.json"):
    rows = json.loads((HERE / name).read_text())
    print(f"{name}: {len(rows)} runs ({len({r['repeat'] for r in rows})} repeats)")
    for k, name in (("ours", "Open Yet?"), ("baseline", "reference: model writes the time")):
        ok = sum(r[k] == r["want"] for r in rows)
        wrong = sorted({(r["id"], r[k]) for r in rows if r[k] != r["want"]})
        opened = lambda r: (datetime.fromisoformat(r["want"][:-1]) - timedelta(minutes=1)).isoformat() + "Z"  # noqa: E731
        before = sum(1 for r in rows if r[k] and r[k] < opened(r))
        other = len(rows) - ok - before
        print(f"  {name}: right {ok}/{len(rows)}; email before the window opens {before}; other wrong times {other}")
        for i, got in wrong:
            want = next(r["want"] for r in rows if r["id"] == i)
            print(f"    {i}: want {want}, got {got}")


def latency():
    rows = json.loads((HERE / "raw-latency.json").read_text())
    late = sorted(r["late_s"] for r in rows)
    print(f"latency: {len(rows)} real schedules; SNS published this many seconds after the scheduled time: "
          f"min {late[0]:.1f}, median {(late[len(late)//2 - 1] + late[len(late)//2]) / 2:.1f}, max {late[-1]:.1f}; "
          f"early: {sum(x < 0 for x in late)}")


if __name__ == "__main__":
    steps = [
        ("Does the agent book when, and only when, it should?", decide),
        ("Times, first set (where the error was found), before the fix", lambda: time("raw-time.json")),
        ("Times, first set, after the fix", lambda: time("raw-time-tune-v2.json")),
        ("Times, second set (written before the fix), before the fix", lambda: time("raw-time_cases2-before-fix.json")),
        ("Times, second set, after the fix: the article's table", lambda: time("raw-time_cases2.json")),
        ("How late the email is", latency),
    ]
    for title, f in steps:
        print(f"\n== {title}")
        try:
            f()
        except FileNotFoundError as e:
            print("  (no data:", e.filename, ")")
