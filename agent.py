"""Open Yet? — paste a Builder Center challenge page (and its terms, if you have
them). The agent answers "can I post right now?" on the first line, then lists
only the discrepancies between the texts that could get an entry disqualified.

The model only reads and extracts. Choosing the strictest window, the clock
arithmetic, and the shape of the reply all happen in code, so the answer is
the same every time.
"""
import json
import re
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field
from strands import Agent
from strands.models import BedrockModel

MODEL_ID = "amazon.nova-pro-v1:0"


class Window(BaseModel):
    source: str = Field(description="Which text this came from, e.g. 'challenge page' or 'terms'")
    opens_utc: Optional[str] = Field(
        default=None,
        description="Opening time as ISO-8601 UTC (e.g. 2026-10-09T07:00:00Z). "
                    "Null if this text gives no explicit opening date and time.")
    closes_utc: str = Field(description="Closing time as ISO-8601 UTC.")
    required_tags: list[str] = Field(
        default_factory=list,
        description="Every article tag this text says is required, exactly as written (e.g. '#agents', 'agent').")


class Discrepancy(BaseModel):
    what: str = Field(description="What differs between the texts, in one short sentence.")
    safe_choice: str = Field(description="What to do so that every text is satisfied at once.")


class Reading(BaseModel):
    windows: list[Window]
    discrepancies: list[Discrepancy]


SYSTEM = """You read texts about an AWS Builder Center challenge: the challenge page,
and sometimes its terms, a Space rule, or an email. Extract facts. Do not chat.

Entry windows:
- Record one window per text that states one.
- Use UTC if the text gives it. If only PT is given, convert: PDT = UTC-7 until the
  first Sunday of November 2026, PST = UTC-8 after. "12:00 AM PT on Oct 9" is
  2026-10-09T07:00:00Z. A date with no time, used as a closing day, means 23:59 PT.
- opens_utc is null ONLY when the text gives no explicit opening date
  (for example "between today and ..."). A rule like "content published on or
  after October 2" is an eligibility rule, not the entry window.

Discrepancies — list only differences that could get an entry disqualified,
such as a different rule about when content must have been published, different
required sections, or different eligibility. Do NOT list differences in the entry
window or in required tags; those are compared separately.
Write "what" as a sentence naming both versions, and "safe_choice" in plain words.
- Ignore wording that means the same thing ("votes" and "responses").
- safe_choice must satisfy every text at once. Only if that is impossible, pick the stricter."""


def _has(s: Optional[str]) -> bool:
    return bool(s) and s.strip().lower() not in ("null", "none", "n/a")


def _parse(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


def _span(seconds: float) -> str:
    m = int(seconds // 60)
    d, rem = divmod(m, 1440)
    h, mm = divmod(rem, 60)
    return " ".join(([f"{d}d"] if d else []) + ([f"{h}h"] if h else []) + [f"{mm}m"])


def verdict(reading: Reading, user_tz: str, now: Optional[datetime] = None) -> str:
    now = now or datetime.now(timezone.utc)
    tz = ZoneInfo(user_tz)
    local = lambda d: d.astimezone(tz).strftime("%a %b %d, %H:%M") + " your time"

    if not reading.windows:
        return "I could not find an entry window in what you pasted. Paste the part with the dates."

    # Strictest window: latest stated opening, earliest closing.
    opens_list = [_parse(w.opens_utc) for w in reading.windows if _has(w.opens_utc)]
    opens = max(opens_list) if opens_list else None
    closes = min(_parse(w.closes_utc) for w in reading.windows)

    if opens and now < opens:
        line = f"NOT YET. Opens {local(opens)} — in {_span((opens - now).total_seconds())}."
    elif now <= closes:
        line = f"YES, it is open. Closes {local(closes)} — {_span((closes - now).total_seconds())} left."
    else:
        line = f"CLOSED. It closed {local(closes)}, {_span((now - closes).total_seconds())} ago."

    out = [line]
    out.append(f"Window: {local(opens) if opens else 'no start time stated'} to {local(closes)}.")

    notes: list[str] = []
    closes_by = {}
    for w in reading.windows:
        closes_by.setdefault(_parse(w.closes_utc), []).append(w.source)
    if len(closes_by) > 1:
        parts = "; ".join(f"{', '.join(src)} says {local(t)}" for t, src in sorted(closes_by.items()))
        notes.append(f"The texts give different deadlines ({parts}). "
                     f"Safe choice: treat {local(closes)} as the deadline.")
    opens_by = {}
    for w in reading.windows:
        if _has(w.opens_utc):
            opens_by.setdefault(_parse(w.opens_utc), []).append(w.source)
    if len(opens_by) > 1:
        parts = "; ".join(f"{', '.join(src)} says {local(t)}" for t, src in sorted(opens_by.items()))
        notes.append(f"The texts give different start times ({parts}). "
                     f"Safe choice: wait until {local(opens)}.")
    tags = {}
    for w in reading.windows:
        for t in w.required_tags:
            tags.setdefault(t.strip(), []).append(w.source)
    if len({t.lstrip('#').lower() for t in tags}) > 1:
        parts = "; ".join(f"{', '.join(src)} asks for {t}" for t, src in tags.items())
        notes.append(f"The texts ask for different tags ({parts}). "
                     f"Safe choice: add all of them: {', '.join(t.lstrip('#') for t in tags)}.")
    handled = ("tag", "deadline", "closing", "closes", "end date", "runs from",
               "start time", "opening", "entry window", "proof", "runs until", "until october")
    for d in reading.discrepancies:
        if any(k in d.what.lower() for k in handled):
            continue  # compared deterministically above, or not a real conflict
        notes.append(f"{d.what} Safe choice: {d.safe_choice}")

    if notes:
        out.append("")
        out.append("Watch out:")
        out.extend(f"- {n}" for n in notes)
    else:
        out.append("No conflicts between the texts.")
    return "\n".join(out)


def read(text: str) -> Reading:
    agent = Agent(
        model=BedrockModel(model_id=MODEL_ID, region_name="us-east-1", temperature=0),
        system_prompt=SYSTEM,
        callback_handler=None,
    )
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    prompt = (f"The current time is {now}. If a text says 'today', it means this moment.\n\n"
              f"{text}")
    return agent(prompt, structured_output_model=Reading).structured_output


def answer(text: str, user_tz: str = "Asia/Tokyo") -> str:
    return verdict(read(text), user_tz)


def handler(event, context):
    """Lambda entry point. Body: {"text": "...", "timezone": "Asia/Tokyo"}."""
    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return _resp(400, 'Send JSON like {"text": "paste the challenge page here"}.')
    text = (body.get("text") or "").strip()
    if not text:
        return _resp(400, 'Paste the challenge page (and its terms, if you have them) into "text".')
    tz = body.get("timezone") or "Asia/Tokyo"
    try:
        ZoneInfo(tz)
    except Exception:
        return _resp(400, f'I do not recognise the time zone {tz!r}. Try something like "Asia/Tokyo".')
    return _resp(200, answer(text[:30000], tz))


def _resp(code: int, text: str) -> dict:
    return {"statusCode": code, "headers": {"content-type": "text/plain; charset=utf-8"},
            "body": text + "\n"}


if __name__ == "__main__":
    import sys
    print(answer(sys.stdin.read()))
