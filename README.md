# Open Yet?

Can I post my AWS Builder Center challenge entry right now? Paste the challenge page (and the terms or a Space rule, if you have them). Open Yet? answers in your own time zone, flags any disagreement between the texts that could get an entry disqualified, and, if you ask, emails you one minute after the entry window opens. Never before it does.

A Strands agent on AWS Lambda, reading with Amazon Nova Pro on Amazon Bedrock, with one tool, `remind_me_when_open`, that books the email with Amazon EventBridge Scheduler and Amazon SNS.

- Article for the Weekend Challenge "Give your Agent a Tool": [ARTICLE LINK]
- The first version and its article (October 9, 2026): [`ARTICLE.md`](ARTICLE.md)

## The design in one rule

**The agent decides whether to remind; code decides when.**

The tool takes no arguments. Code computes the reminder time when it reads the entry window and passes it through Strands' invocation state; the tool reads it from there. The model only decides whether the user asked to be told. The tool also refuses on its own if the window is already open, has no start time, or closes within the minute, and asking twice books one email. The model's own words never reach the reply: code writes what the tool actually did.

Time zones are converted in code, too. The model copies each time and zone as written (`"2026-11-06 00:00"`, `"America/Los_Angeles"`), and `zoneinfo` does the conversion, including daylight saving.

## What was measured

Sixteen dummy challenge texts in other wording and time zones, written and committed before the time zone fix, scored once after it, three runs each:

| Design | Booked for the right minute | "It is open" email sent before the window opened |
|---|---|---|
| Before the fix: the model converts time zones | 36/48 | 11 |
| **After the fix: code converts time zones** | **48/48** | **0** |
| Reference only, not in the agent: a tool that takes the time as an argument | 31/48 | 13 |

Whether the agent uses the tool when, and only when, it should: 16 requests × 4 situations × 3 runs. Should book: 27/27 booked. Should not book: 0/165 booked (the agent called the tool once for a closed window; the tool refused).

How late the email leaves AWS: 10 real schedules, SNS published 15.2 to 49.1 seconds after the scheduled time (median 19.5), none early.

## Check the numbers yourself

Every answer the model gave is saved in `bench/`. This recounts them and prints every number above, with no AWS account and no model call:

```bash
python bench/score.py
```

To run the measurements again (needs Bedrock access to Nova Pro in us-east-1):

```bash
python -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
python bench/run.py decide                  # when does the agent call the tool?
python bench/run.py time --set time_cases2  # are the booked times right?
python bench/latency.py setup && python bench/latency.py run -n 10 && python bench/latency.py teardown
```

`bench/make_time_cases.py` writes the test texts and computes the correct times from the time zone database.

## Run and deploy

```bash
pip install -r requirements.txt
python test_remind.py                            # the booking logic, no AWS
./deploy_remind.sh you@example.com               # topic, two roles, the function (confirm the SNS email)
./demo.sh after                                  # a made-up challenge opening in 4 minutes, asking to be told
```

Permissions are narrow: the function may call Nova Pro, create schedules named `open-yet-*`, pass the one scheduler role, and write its logs; the scheduler role may only publish to one topic.

## Files

| File | What it is |
|---|---|
| `agent.py` | Reading, the verdict, and the step where the agent decides whether to call the tool |
| `remind.py` | The tool, `remind_me_when_open`, and the booking it wraps |
| `test_remind.py` | Tests for the booking logic |
| `deploy_remind.sh` | Creates the AWS resources and deploys the function |
| `demo.sh` | The before/after demo used in the video |
| `bench/` | Test cases, saved answers, and the scripts that run and count them |

## License

Apache-2.0
