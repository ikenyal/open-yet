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
from agent import MODEL_ID, SYSTEM, Reading, Window, read, remind_step, strictest, verdict  # noqa: E402
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
            reading = Reading(windows=[Window(source="challenge page", opens_utc=iso(opens),
                                              closes_utc=iso(closes))], discrepancies=[])
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

How to read times (the same rules the extraction step is given):
""" + SYSTEM.split("Entry windows:")[1].split("Discrepancies")[0]


def run_time(repeat):
    cases = json.loads((HERE / "time_cases.json").read_text())
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
    (HERE / "raw-time.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1) + "\n")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("what", choices=["decide", "time"])
    p.add_argument("--repeat", type=int, default=3)
    a = p.parse_args()
    (run_decide if a.what == "decide" else run_time)(a.repeat)
