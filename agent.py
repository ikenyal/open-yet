"""Open Yet? — paste a Builder Center challenge page (and its terms, if you have
them). The agent answers "can I post right now?" on the first line, then lists
only the discrepancies between the texts that could get an entry disqualified.

The model only reads and extracts. Choosing the strictest window, the clock
arithmetic, and the shape of the reply all happen in code, so the answer is
the same every time.
"""
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field
from strands import Agent
from strands.models import BedrockModel

from remind import remind_me_when_open

MODEL_ID = "amazon.nova-pro-v1:0"


class Window(BaseModel):
    source: str = Field(description="Which text this came from, e.g. 'challenge page' or 'terms'")
    opens_local: Optional[str] = Field(
        default=None,
        description="Opening date and time exactly as the text states it, in the text's own "
                    "time zone, as 'YYYY-MM-DD HH:MM' (24-hour). Do not convert it. "
                    "Null if this text gives no explicit opening date and time.")
    opens_zone: Optional[str] = Field(
        default=None,
        description="The time zone the opening time is written in, as an IANA name "
                    "(e.g. 'America/Los_Angeles' for PT, PDT or PST) or as a UTC offset "
                    "written in the text (e.g. '-08:00'). Null if opens_local is null.")
    closes_local: str = Field(description="Closing date and time as stated, 'YYYY-MM-DD HH:MM', not converted.")
    closes_zone: str = Field(description="The time zone the closing time is written in, as for opens_zone.")
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
- Copy each date and time as written, in the zone it is written in. Never convert
  between time zones and never apply daylight saving yourself: code does that.
  "12:00 AM PT on Oct 9, 2026" is opens_local "2026-10-09 00:00", opens_zone
  "America/Los_Angeles". A date with no time, used as a closing day, means 23:59
  in the zone the text uses (PT if it names none).
- opens_local is null ONLY when the text gives no explicit opening date
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


_OFFSET = re.compile(r"^(?:UTC|GMT)?\s*([+-])(\d{1,2}):?(\d{2})$")


def _zone(name: str):
    """IANA name, or a UTC offset as written ('-08:00', 'UTC+9:00'). Daylight saving is
    the time zone database's job, not the model's."""
    name = name.strip()
    if name.upper() in ("UTC", "GMT", "Z"):
        return timezone.utc
    m = _OFFSET.match(name.upper())
    if m:
        sign = 1 if m.group(1) == "+" else -1
        return timezone(sign * timedelta(hours=int(m.group(2)), minutes=int(m.group(3))))
    return ZoneInfo(name)  # raises for an unknown name: a window we cannot place is not guessed


def _at(local: str, zone: str) -> datetime:
    d = datetime.strptime(local.strip()[:16].replace("T", " "), "%Y-%m-%d %H:%M")
    return d.replace(tzinfo=_zone(zone)).astimezone(timezone.utc)


def opens_of(w: "Window") -> Optional[datetime]:
    return _at(w.opens_local, w.opens_zone) if _has(w.opens_local) and _has(w.opens_zone) else None


def closes_of(w: "Window") -> datetime:
    return _at(w.closes_local, w.closes_zone)


def _span(seconds: float) -> str:
    m = int(seconds // 60)
    d, rem = divmod(m, 1440)
    h, mm = divmod(rem, 60)
    return " ".join(([f"{d}d"] if d else []) + ([f"{h}h"] if h else []) + [f"{mm}m"])


def strictest(reading: Reading) -> tuple[Optional[datetime], datetime]:
    """Strictest window: latest stated opening, earliest closing."""
    opens_list = [o for o in map(opens_of, reading.windows) if o]
    opens = max(opens_list) if opens_list else None
    closes = min(closes_of(w) for w in reading.windows)
    return opens, closes


def verdict(reading: Reading, user_tz: str, now: Optional[datetime] = None) -> str:
    now = now or datetime.now(timezone.utc)
    tz = ZoneInfo(user_tz)
    local = lambda d: d.astimezone(tz).strftime("%a %b %d, %H:%M") + " your time"

    if not reading.windows:
        return "I could not find an entry window in what you pasted. Paste the part with the dates."

    opens, closes = strictest(reading)

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
        closes_by.setdefault(closes_of(w), []).append(w.source)
    if len(closes_by) > 1:
        parts = "; ".join(f"{', '.join(src)} says {local(t)}" for t, src in sorted(closes_by.items()))
        notes.append(f"The texts give different deadlines ({parts}). "
                     f"Safe choice: treat {local(closes)} as the deadline.")
    opens_by = {}
    for w in reading.windows:
        if opens_of(w):
            opens_by.setdefault(opens_of(w), []).append(w.source)
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


DECIDE = """You decide one thing: whether to book a reminder email for when an
AWS Builder Center challenge opens. Code has already worked out whether the
entry window is open, and when. You are given that verdict and what the user said.

- Call remind_me_when_open only if the verdict starts with NOT YET and the user
  is asking to be told, notified, emailed or reminded when it opens.
- Otherwise do not call any tool.
- Never write a date or time yourself. After deciding, reply with one short
  sentence and nothing else."""


def answer(text: str, user_tz: str = "Asia/Tokyo", request: str = "") -> str:
    reading = read(text)
    reply = verdict(reading, user_tz)
    if not request.strip():
        return reply
    opens, closes = strictest(reading)
    return reply + remind_step(reply, opens, closes, user_tz, request)


def remind_step(reply: str, opens, closes, user_tz: str, request: str) -> str:
    """The agent decides whether to call the tool; code reports what happened."""
    state = {"opens": opens, "closes": closes, "user_tz": user_tz,
             "message": "It is open now. You can post your entry.\n\n" + reply.split("\n")[1]
                        + "\n\n- Open Yet?"}
    agent = Agent(
        model=BedrockModel(model_id=MODEL_ID, region_name="us-east-1", temperature=0),
        system_prompt=DECIDE,
        tools=[remind_me_when_open],
        callback_handler=None,
    )
    agent(f"Verdict: {reply.splitlines()[0]}\n\nThe user said: {request.strip()[:2000]}",
          invocation_state=state)
    # The model's own words never reach the user: if it chose to call the tool,
    # code reports what the tool did; if not, the verdict stands alone, as before.
    if "reminder" in state:
        return "\n\nReminder: " + state["reminder"]
    return ""


def handler(event, context):
    """Lambda entry point.
    Body: {"text": "...", "timezone": "Asia/Tokyo", "request": "Tell me when it opens"}.
    Without "request" it behaves exactly as before: a verdict and nothing else."""
    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return _resp(400, 'Send JSON like {"text": "paste the challenge page here"}.')
    text = (body.get("text") or "").strip()
    if not text:
        return _resp(400, 'Paste the challenge page (and its terms, if you have them) into "text".')
    tz = body.get("timezone") or "Asia/Tokyo"
    request = str(body.get("request") or "")
    try:
        ZoneInfo(tz)
    except Exception:
        return _resp(400, f'I do not recognise the time zone {tz!r}. Try something like "Asia/Tokyo".')
    return _resp(200, answer(text[:30000], tz, request))


def _resp(code: int, text: str) -> dict:
    return {"statusCode": code, "headers": {"content-type": "text/plain; charset=utf-8"},
            "body": text + "\n"}


if __name__ == "__main__":
    import sys
    print(answer(sys.stdin.read()))
