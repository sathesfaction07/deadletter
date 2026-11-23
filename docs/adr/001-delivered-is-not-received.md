# ADR 001: "Delivered" is not "received", and the difference is not observable

**Status:** accepted
**Date:** 2026-09-17

## Context

The brief asks *"did every recipient actually receive the notification?"* and answers:

> **Verdict:** SES for delivery confidence. Bounce/complaint tracking tells you who didn't
> receive it.

The first half is sound engineering. The second half is false, and the way it is false
matters for a safety notice.

## The problem

Write out the map from what actually happened to what the sender observes:

```
signal     outcomes   failures   which
rejected   1          1          never_accepted
deferred   1          0          in_flight
bounced    1          1          never_accepted
nothing    4          2          read, in_inbox, in_spam, discarded   <- THE COLLAPSE
```

Four distinct outcomes emit **nothing**:

- `READ` — a human read it. The only outcome that discharges a recall duty.
- `IN_INBOX` — delivered, unread.
- `IN_SPAM` — delivered somewhere nobody looks.
- `DISCARDED` — accepted with a 2xx, then dropped on the floor.

**Two of those four are failures.** Silence is consistent with all four, so "no bounce" is
not evidence of delivery — it is the absence of evidence in either direction.

### Waiting does not fix it

```
signal     window open     window closed   settled?
rejected   1               1               yes
deferred   1               4               NO
bounced    1               1               yes
nothing    5               4               NO
```

Closing the retry window removes **exactly one** candidate — `IN_FLIGHT` — taking silence
from five to four. **Never to one.** A report generated a year later says the same thing.

### And the only trustworthy answers are the negative ones

The signals that ever settle an outcome are `rejected` and `bounced`, and **both mean the
message was not accepted**. So:

> You can learn that you failed. You cannot learn that you succeeded.

## Decision

`Signal` and `TrueState` are separate types, and the report publishes a **range** rather
than a number:

```
between 5 and 26 of 26 recipients were not informed. Of the 21 in between, 18 will never
produce a signal at all and 3 will resolve, but only after the deadline.
```

`FailureBounds` carries `floor`, `ceiling`, `silent` and `pending`. The count of people
informed is named `informed_ceiling` so nobody reads it as a count of people reached.

`check` does **not** fail on undecidability. It is a property of SMTP, not a defect anyone
can fix, and a gate that fires on every accepted message gets switched off inside a week.

## Consequences

**Good.** The report cannot be misread as a delivery guarantee. The gap between floor and
ceiling is the honest measure of how much a bounce-based scheme does not know, and splitting
it into `silent` and `pending` distinguishes "unknowable" from "merely late".

**Bad.** The ceiling is weak — on the shipped corpus it is the entire recipient list, because
it is genuinely possible that every accepted message was discarded. A reader wanting one
number will find that unsatisfying. It is the correct answer to the question they asked.

**Also.** Whether `IN_SPAM` counts as a failure is a judgement, not a fact. `IN_INBOX` is
deliberately **not** a failure — a notice sitting unread was delivered, and delivery is what
a sender can be responsible for. `doctor` lists both as judgements.

## What was rejected

**A `delivered: bool`.** It would have to be true for `DISCARDED`, which is the failure the
whole project is about.

**Read receipts.** Client-optional, widely disabled, and trivially spoofed. They would move
the ambiguity rather than remove it.

**Assuming no bounce means delivered.** The industry default, and the thing this ADR exists
to refuse.

## Note on novelty

The non-injective map is the same shape Shoehorn found between heading levels and
document outlines. Reused because the failure has the same structure, not offered as new.
The difference: an outline collapse is recoverable if you keep the source, and a discarded
message is gone.
