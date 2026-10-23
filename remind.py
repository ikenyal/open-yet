"""remind_me_when_open — a Strands tool that emails you one minute after an entry
window opens, using Amazon EventBridge Scheduler and Amazon SNS.

The agent decides WHETHER to remind. Code decides WHEN. The tool takes no time
argument: the window comes from invocation_state, which the caller fills in
with the times its own code computed. A model cannot mistype the time, so the
email cannot arrive after the deadline.

Use it in any Strands agent:

    from remind import remind_me_when_open
    agent = Agent(tools=[remind_me_when_open])
    state = {"opens": opens, "closes": closes,  # datetimes your code computed
             "message": "It is open now. ...", "user_tz": "Asia/Tokyo"}
    agent(prompt, invocation_state=state)
    state.get("reminder")  # what the tool did, if the agent called it

Environment: REMIND_TOPIC_ARN (SNS topic to publish to) and
REMIND_SCHEDULER_ROLE_ARN (role EventBridge Scheduler assumes to publish).
"""
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

import boto3
from strands import tool
from strands.types.tools import ToolContext

NOTIFY_AFTER = timedelta(minutes=1)
PREFIX = "open-yet-"
SUBJECT = "Open Yet? — it is open now"


def schedule_name(opens: datetime) -> str:
    """One schedule per opening time, so asking twice cannot book two emails."""
    return PREFIX + opens.astimezone(timezone.utc).strftime("%Y%m%dT%H%MZ")


def _client():
    return boto3.client("scheduler", region_name=os.environ.get("AWS_REGION", "us-east-1"))


def book(opens: Optional[datetime], closes: Optional[datetime], message: str,
         user_tz: str = "UTC", now: Optional[datetime] = None, client=None) -> str:
    """Plain function behind the tool, so it can be tested without a model."""
    now = now or datetime.now(timezone.utc)
    if opens is None:
        return "NOT BOOKED: the texts give no start time, so there is nothing to wait for."
    if now >= opens:
        return "NOT BOOKED: the window is already open. No reminder needed."
    fire = opens + NOTIFY_AFTER
    if closes is not None and fire >= closes:
        return "NOT BOOKED: the window closes within a minute of opening."
    name = schedule_name(opens)
    client = client or _client()
    try:
        client.create_schedule(
            Name=name,
            ScheduleExpression="at(" + fire.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S") + ")",
            ScheduleExpressionTimezone="UTC",
            FlexibleTimeWindow={"Mode": "OFF"},
            ActionAfterCompletion="DELETE",
            Target={
                # Universal target: calls SNS Publish directly, so the email can have a subject.
                "Arn": "arn:aws:scheduler:::aws-sdk:sns:publish",
                "RoleArn": os.environ["REMIND_SCHEDULER_ROLE_ARN"],
                "Input": json.dumps({"TopicArn": os.environ["REMIND_TOPIC_ARN"],
                                     "Subject": SUBJECT, "Message": message}),
                "RetryPolicy": {"MaximumRetryAttempts": 3, "MaximumEventAgeInSeconds": 600},
            },
            Description="Open Yet? reminder: the entry window has opened.",
        )
    except client.exceptions.ConflictException:
        return f"ALREADY BOOKED: a reminder for this opening time already exists ({name})."
    local = fire.astimezone(ZoneInfo(user_tz)).strftime("%a %b %d, %H:%M")
    return f"BOOKED: one email at {local} your time, one minute after it opens ({name})."


@tool(context=True)
def remind_me_when_open(tool_context: ToolContext) -> str:
    """Book one email for one minute after the entry window opens.

    Call this only when the verdict is NOT YET and the user asked to be told
    when it opens. It takes no arguments: the opening time was already computed
    by code and is passed in by the caller, not by you.
    """
    s = tool_context.invocation_state
    result = book(s.get("opens"), s.get("closes"), s.get("message", "The entry window is open now."),
                  s.get("user_tz", "UTC"))
    s["reminder"] = result  # the caller reads this back, so the reply is written by code
    return result
