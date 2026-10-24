"""How late is the email? Book real schedules and timestamp what SNS publishes.

    AWS_PROFILE=... python bench/latency.py setup      # test topic + SQS queue (once)
    AWS_PROFILE=... python bench/latency.py run -n 10  # book n schedules, one per minute, and wait
    AWS_PROFILE=... python bench/latency.py teardown

Uses the real book() and the real scheduler role, but a separate SNS topic whose only
subscriber is an SQS queue, so no email is sent. Measured: SNS's own publish timestamp
minus the time the schedule was set for. Delivery from SNS to an inbox is not measured;
it depends on the mail provider.
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median

import boto3

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent))
REGION = "us-east-1"
NAME = "open-yet-remind-latency"
SCHED_ROLE = "open-yet-remind-scheduler-role"

sns = boto3.client("sns", region_name=REGION)
sqs = boto3.client("sqs", region_name=REGION)
iam = boto3.client("iam")
account = boto3.client("sts").get_caller_identity()["Account"]
TOPIC = f"arn:aws:sns:{REGION}:{account}:{NAME}"


def queue_url():
    return sqs.get_queue_url(QueueName=NAME)["QueueUrl"]


def setup():
    sns.create_topic(Name=NAME)
    url = sqs.create_queue(QueueName=NAME)["QueueUrl"]
    qarn = sqs.get_queue_attributes(QueueUrl=url, AttributeNames=["QueueArn"])["Attributes"]["QueueArn"]
    sqs.set_queue_attributes(QueueUrl=url, Attributes={"Policy": json.dumps({
        "Version": "2012-10-17", "Statement": [{
            "Effect": "Allow", "Principal": {"Service": "sns.amazonaws.com"},
            "Action": "sqs:SendMessage", "Resource": qarn,
            "Condition": {"ArnEquals": {"aws:SourceArn": TOPIC}}}]})})
    sns.subscribe(TopicArn=TOPIC, Protocol="sqs", Endpoint=qarn)
    iam.put_role_policy(RoleName=SCHED_ROLE, PolicyName="publish-latency-test", PolicyDocument=json.dumps({
        "Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": "sns:Publish", "Resource": TOPIC}]}))
    print("ready:", TOPIC, url)


def teardown():
    iam.delete_role_policy(RoleName=SCHED_ROLE, PolicyName="publish-latency-test")
    sqs.delete_queue(QueueUrl=queue_url())
    sns.delete_topic(TopicArn=TOPIC)
    print("removed")


def run(n):
    os.environ["REMIND_TOPIC_ARN"] = TOPIC
    os.environ.setdefault("REMIND_SCHEDULER_ROLE_ARN", f"arn:aws:iam::{account}:role/{SCHED_ROLE}")
    import remind
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    booked = {}
    for i in range(n):
        opens = now + timedelta(minutes=3 + i)
        fire = opens + remind.NOTIFY_AFTER
        print(remind.book(opens, opens + timedelta(days=1), f"latency-test {fire.isoformat()}"), flush=True)
        booked[fire.isoformat()] = fire
    url, rows = queue_url(), []
    deadline = max(booked.values()) + timedelta(minutes=5)
    while len(rows) < n and datetime.now(timezone.utc) < deadline:
        for m in sqs.receive_message(QueueUrl=url, WaitTimeSeconds=20, MaxNumberOfMessages=10).get("Messages", []):
            body = json.loads(m["Body"])
            key = body["Message"].split(" ", 1)[1]
            published = datetime.fromisoformat(body["Timestamp"].replace("Z", "+00:00"))
            rows.append({"scheduled": key, "published": body["Timestamp"],
                         "late_s": round((published - booked[key]).total_seconds(), 3)})
            print(rows[-1], flush=True)
            sqs.delete_message(QueueUrl=url, ReceiptHandle=m["ReceiptHandle"])
    (HERE / "raw-latency.json").write_text(json.dumps(rows, indent=1) + "\n")
    late = sorted(r["late_s"] for r in rows)
    print(f"received {len(rows)}/{n}; seconds after the scheduled time: "
          f"min {late[0]}, median {median(late)}, max {late[-1]}" if late else "nothing received")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("what", choices=["setup", "run", "teardown"])
    p.add_argument("-n", type=int, default=10)
    a = p.parse_args()
    {"setup": setup, "teardown": teardown, "run": lambda: run(a.n)}[a.what]()
