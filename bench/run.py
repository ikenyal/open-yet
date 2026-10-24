"""Measure the two things the tool depends on. Results are saved raw, then counted.

    python bench/run.py decide [--repeat 3]   # does the agent call the tool when, and only when, it should?
    python bench/run.py time   [--repeat 3]   # is the booked time right? code-held time vs. model-written time

No schedule is created: the scheduler client is replaced by a recorder.
Needs Bedrock access to Nova Pro in us-east-1.
"""
import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent))
os.environ.setdefault("REMIND_TOPIC_ARN", "arn:aws:sns:us-east-1:000000000000:bench")
os.environ.setdefault("REMIND_SCHEDULER_ROLE_ARN", "arn:aws:iam::000000000000:role/bench")

import remind  # noqa: E402
from agent import MODEL_ID, Reading, Window, read, remind_step, strictest, verdict  # noqa: E402
from strands import Agent, tool  # noqa: E402
from strands.models import BedrockModel  # noqa: E402


class Recorder:
    """Stands in for the EventBridge Scheduler client."""
    class exceptions:
        class ConflictException(Exception):
            pass

    def __init__(self):
        self.made = []

    def create_schedule(self, **kw):
        self.made.append(kw)


def iso(d):
    return d.strftime("%Y-%m-%dT%H:%M:%SZ") if d else None


def run_decide(repeat):
    spec = json.loads((HERE / "decide_cases.json").read_text())
    rows = []
    real_book = remind.book
    for r in range(repeat):
        for sit, w in spec["situations"].items():
            now = datetime.now(timezone.utc)
            opens = now + timedelta(minutes=w["opens_in_min"]) if w["opens_in_min"] is not None else None
            closes = now + timedelta(minutes=w["closes_in_min"])
            hm = lambda d: d.strftime("%Y-%m-%d %H:%M") if d else None  # noqa: E731
            reading = Reading(windows=[Window(source="challenge page", opens_local=hm(opens),
                                              opens_zone="UTC" if opens else None,
                                              closes_local=hm(closes), closes_zone="UTC")],
                              discrepancies=[])
            reply = verdict(reading, "Asia/Tokyo", now)
            o, c = strictest(reading)
            for q in spec["requests"]:
                rec, calls = Recorder(), []

                def spy(*a, **k):
                    calls.append(1)
                    return real_book(*a, **{**k, "client": rec})
                remind.book = spy
                try:
                    out = remind_step(reply, o, c, "Asia/Tokyo", q["text"])
                finally:
                    remind.book = real_book
                expect = sit == "not_yet" and q["notify"]
                rows.append({"repeat": r, "situation": sit, "request": q["id"], "expect_book": expect,
                             "called_tool": bool(calls), "booked": bool(rec.made), "reply_tail": out.strip()})
                print(r, sit, q["id"], "expect", expect, "called", bool(calls), "booked", bool(rec.made), flush=True)
    (HERE / "raw-decide.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1) + "\n")


BASELINE = """You decide whether to book a reminder email for when an AWS Builder Center
challenge opens, and you book it. Call remind_at only if the entry window has not
opened yet and the user asks to be told when it opens. Pass fire_time_utc as
ISO-8601 UTC (e.g. 2026-10-09T07:01:00Z): one minute after the window opens.
If several texts give different opening times, use the latest one.

How to read times (the rules the extraction step was given in the first run, frozen here
so the baseline does not change when the extraction step does):
""" + '\n- Record one window per text that states one.\n- Use UTC if the text gives it. If only PT is given, convert: PDT = UTC-7 until the\n  first Sunday of November 2026, PST = UTC-8 after. "12:00 AM PT on Oct 9" is\n  2026-10-09T07:00:00Z. A date with no time, used as a closing day, means 23:59 PT.\n- opens_utc is null ONLY when the text gives no explicit opening date\n  (for example "between today and ..."). A rule like "content published on or\n  after October 2" is an eligibility rule, not the entry window.\n\n'


def run_time(repeat, set_name="time_cases", out=None):
    cases = json.loads((HERE / f"{set_name}.json").read_text())
    rows = []
    for r in range(repeat):
        for c in cases:
            want = datetime.fromisoformat(c["opens_utc"].replace("Z", "+00:00")) + timedelta(minutes=1)
            # Open Yet?: the model reads the page into fields; code picks the window and the time.
            try:
                opens, _ = strictest(read(c["text"]))
                ours = opens + timedelta(minutes=1) if opens else None
            except Exception as e:  # noqa: BLE001
                ours = None
                print("read failed", c["id"], e, flush=True)
            # Baseline: the same model writes the reminder time into the tool call.
            got = []

            @tool
            def remind_at(fire_time_utc: str) -> str:
                """Book one email at fire_time_utc (ISO-8601 UTC)."""
                got.append(fire_time_utc)
                return "BOOKED"
            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            Agent(model=BedrockModel(model_id=MODEL_ID, region_name="us-east-1", temperature=0),
                  system_prompt=BASELINE, tools=[remind_at], callback_handler=None)(
                f"The current time is {now}. The user's time zone is {c['user_tz']}.\n\n"
                f"Pasted text:\n{c['text']}\n\nThe user said: Can you let me know when it opens?")
            try:
                base = datetime.fromisoformat(got[0].replace("Z", "+00:00")).astimezone(timezone.utc) if got else None
            except ValueError:
                base = None
            row = {"repeat": r, "id": c["id"], "want": iso(want), "ours": iso(ours),
                   "baseline_raw": got[0] if got else None, "baseline": iso(base)}
            rows.append(row)
            print(row, flush=True)
    (HERE / (out or ("raw-time.json" if set_name == "time_cases" else f"raw-{set_name}.json"))).write_text(json.dumps(rows, ensure_ascii=False, indent=1) + "\n")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("what", choices=["decide", "time"])
    p.add_argument("--repeat", type=int, default=3)
    p.add_argument("--set", default="time_cases", help="time: time_cases (tuning) or time_cases2 (held out)")
    p.add_argument("--out", help="file name for the raw results (default by set)")
    a = p.parse_args()
    run_decide(a.repeat) if a.what == "decide" else run_time(a.repeat, a.set, a.out)
