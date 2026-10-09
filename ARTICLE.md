# Open Yet? An agent that tells you whether you can post your challenge entry right now

## What the agent does

Open Yet? answers one question for people entering AWS Builder Center challenges: can I post my entry right now?

You paste the challenge page, and the terms or a Space rule if you have them. The first line of the reply is the answer, in your own time zone. After that, and only if there are any, it lists the places where those texts disagree with each other in a way that could get an entry disqualified.

It is for anyone who takes part in these challenges from outside the US Pacific time zone. Every challenge states its window in PT, and every one of us converts it by hand, every time.

## Why it exists

In September I published a challenge entry three hours and fifty-three minutes before the entry window opened. The challenge page was already readable on my side of the date line, so it felt open. It was not. I had to archive the article and publish it again once the window had actually started.

Getting the conversion wrong is only half the problem. The other half is that the texts about a single challenge do not always agree. Over the past month I ran into a challenge page that asks for the tag #agents while its terms ask for "agent", a hackathon page whose header ends on October 30 while its body says the event runs to October 23, and an email that accepts articles published on October 1 while the Space rules say October 2. A time zone converter catches none of those.

## How it was built

Open Yet? is a Strands agent running on AWS Lambda, using Amazon Nova Pro on Amazon Bedrock. It was built with a coding agent over a single evening.

AWS services used:

- Amazon Bedrock (Amazon Nova Pro) reads the pasted texts
- AWS Lambda runs the agent
- AWS IAM gives the function permission to call Bedrock and nothing else
- AWS Budgets caps what it can cost

The key decision was splitting the work between the model and plain code.

The first version let the model do everything: find the window, call a tool for the clock arithmetic, and write the reply. It worked about half the time. The same input produced different verdicts on different runs. It invented an opening date when a text only said "between today and Friday". It told me to use the tag #agents to satisfy both texts, which satisfies only one of them. And it sometimes leaked its own reasoning into the reply.

So the model now does only what it is good at: reading. Through structured output it returns, for each text, the entry window in UTC and the tags that text requires, plus any other rule conflicts it notices, such as a content date rule. Everything else is code. Code picks the strictest window, the latest opening and the earliest close. Code does the clock arithmetic. Code compares the deadlines and the tags across texts and writes those warnings itself, so the advice for tags is always to add every one of them. The model's own list of conflicts is filtered so it cannot repeat, or contradict, what the code has already said.

Two smaller decisions. The page is pasted rather than fetched: Builder Center has no public API for this, and I did not want to build on an internal one. And the current time is passed to the model with every request, so that "between today and Friday" resolves to now instead of a guess.

## The experience: the answer comes first

The one thing I did to make it pleasant to use is put the verdict on the first line, with nothing in front of it.

```
YES, it is open. Closes Tue Oct 13, 05:00 your time — 3d 12h 24m left.
```

When you are about to post an entry, you want a yes or a no and a countdown. Everything else is detail you may or may not need. If the texts agree, the reply ends with one line saying so. If they do not, you get a short list, and each item names what differs and what to do about it.

How I know it worked: I ran the deployed function against the three real discrepancies I had run into, twice each.

- In all six runs, the first line gave the right answer to "can I post right now?": open for this weekend's challenge and for the Speed Run, not yet for the hackathon.
- It caught this weekend's #agents versus "agent" tag mismatch both times, and both times the advice was to add both tags.
- It caught the hackathon's two different end dates both times and chose the earlier one as the deadline.
- It caught the October 1 versus October 2 content rule both times.

The runs also showed where it is still soft, and those are all places where the model is reading rather than code is checking. It read the hackathon's bare "October 23" as the start of that day in one run and the end of it in the other. In one Speed Run answer it applied winter time to an October date and put the deadline an hour late. And once it flagged "10 votes" against "10 responses" as a conflict, which it is not.

The parts handled by code are now stable. The next step is to move more of the reading into fields the code can check, starting with returning the deadline as the text wrote it and doing the time zone conversion in code.

## Proof it works

[screenshot: the deployed function answering for this challenge's page and terms]

#agents #agent
