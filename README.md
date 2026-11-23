# RecallNotifier

Sends a product recall notice, then reports what a delivery report **cannot** tell you.

No model. The accuracy problem here is RFC semantics and time arithmetic.

---

## The Brief's Verdict Is False

> **Verdict:** SES for delivery confidence. Bounce/complaint tracking tells you who didn't
> receive it.

The first half is sound. The second half is not, and checking it first produced the whole
project.

Bounce tracking enumerates a **lower bound** on the failures. It cannot enumerate the failure
set, and the part it misses arrives after the deadline it was meant to protect.

The diligence check also found the mechanisms genuinely absent portfolio-wide — `smtplib`,
MIME, SES, `EmailStr`, `email-validator`, RFC 5321/5322, DSN handling: **zero files each**.
Dedup exists in five other projects, so that is named as a repeat; what is new is that **the
identity function for an email address does not exist.**

---

## Four Outcomes Emit Nothing

```
signal     outcomes   failures   which
rejected   1          1          never_accepted
deferred   1          0          in_flight
bounced    1          1          never_accepted
nothing    4          2          read, in_inbox, in_spam, discarded   <- THE COLLAPSE
```

`READ`, `IN_INBOX`, `IN_SPAM` and `DISCARDED` are four different things that happened. **Two
are failures.** All four look identical from the sending side, so "no bounce" is not evidence
of delivery — it is the absence of evidence either way.

### Waiting does not help

```
signal     window open     window closed   settled?
rejected   1               1               yes
deferred   1               4               NO
bounced    1               1               yes
nothing    5               4               NO
```

Closing the retry window removes **exactly one** candidate — `IN_FLIGHT` — taking silence from
five to four. **Never to one.** A report run a year later says the same thing.

### And only the negative answers are ever trustworthy

The only signals that settle an outcome are `rejected` and `bounced`, and **both mean the
message was not accepted**:

> **You can learn that you failed. You cannot learn that you succeeded.**

---

## The Answer Arrives After the Deadline

RFC 5321 4.5.4.1:

> Retries continue until the message is transmitted or the sender gives up; the give-up time
> generally needs to be **at least 4-5 days**.

A recall deadline is set in hours.

```
deadline    window/deadline   actionable classes    deadline inside window?
1           96.0              1 of 4                YES
6           16.0              1 of 4                YES
24          4.0               1 of 4                YES
72          1.3               1 of 4                YES
120         0.8               3 of 4                no
```

At a 24-hour deadline the retry window is **4x** longer, so a deferred message cannot be
resolved in time no matter what the sender does. **One of four signal classes is actionable,
and it is the one that says NO.**

Bounce tracking is a genuinely useful post-mortem instrument. It is not an input to the
decision it is being asked to inform.

---

## No Regex Validates an Email Address

RFC 5322 3.2.2:

```
comment  = "(" *([FWS] ccontent) [FWS] ")"
ccontent = ctext / quoted-pair / comment      <-- comment contains itself
```

`comment` appears in its own expansion, so nesting is unbounded. A regex has finitely many
states and cannot count it. **The address set is not a regular language.** A grammar fact,
not a judgement about anyone's pattern.

```
depth   a VALID address              everyone writes   the careful one   the "RFC-compliant" one
1       user(x)@example.com          accept            REJECT            REJECT
2       user((x))@example.com        accept            REJECT            REJECT
3       user(((x)))@example.com      accept            REJECT            REJECT
```

Not a threshold effect — the careful regexes reject **every** depth including 1, while the
sloppy one accepts them all by ignoring parentheses. **The least rigorous regex is the only
one that delivers this customer's recall notice.** Accepting a bad address costs a bounce;
rejecting a good one means somebody is never told their product is dangerous.

### The stdlib disagrees with itself

```
input                           parseaddr                   getaddresses
not-an-address                  'not-an-address'            ['not-an-address']
user@[192.168.1.1]              ''                          []
Doe, John <john@example.com>    ''                          ['Doe', 'john@example.com']
user(a(b)c)@example.com         'user@example.com'          ['user@example.com']
```

- **`not-an-address` comes back as a mailbox.** No `@`, and no error either.
- **`user@[192.168.1.1]` is refused** — and RFC 5321 4.1.3 explicitly permits it.
- **`Doe, John <...>` becomes two recipients**, one being a surname, while `parseaddr` returns
  nothing. **One invents a recipient, the other drops it. Same input.**
- **Comments are stripped silently**, so the mailbox delivered to is not the string supplied.

---

## A Recipient Count Is a Function of Policy, Not of the List

RFC 5321 2.4 is explicit: the **local part is case-sensitive**; only the domain is not.
Meanwhile Gmail ignores dots and truncates at `+`, which no RFC sanctions.

```
exact        -> 5 recipients from 5 addresses
rfc5321      -> 5
lowercase    -> 4
folded       -> 1
```

Same five addresses, **between one and five people.** Merge too eagerly and up to four
customers are never told. Merge too little and up to four get a duplicate. Same number,
wildly different cost — so for a safety notice the defensible default is the one that
**duplicates**, which is exactly the behaviour the brief asks to remove.

---

## A multipart/alternative Message Is Two Documents

```
two templates                  agree=True   missing from text: none
text stripped from the HTML    agree=False  missing from text: ('lot', 'sold_between')
```

The tag-stripping shortcut produces:

```
... Lot Sold between LOT-4471 March 2025 and August 2026 What to do: ...
```

The header cells and the data cells are now adjacent to **each other**, so `LOT-4471` sits
next to nothing saying it is a lot number. **The value survives; the fact does not** — which
is why a value-presence check passes and says nothing. (DocConsolidator's finding arriving
through a different door. The difference: here both documents ship, and only one is read.)

---

## What the Campaign Can Honestly Claim

```
between 5 and 26 of 26 recipients were not informed. Of the 21 in between, 18 will never
produce a signal at all and 3 will resolve, but only after the deadline.

2 of 26 outcomes were knowable by the 24h deadline.
```

Two. And one of those two was a rejection.

---

## Running

```bash
bash setup.sh                      # re-derives every finding above
source .venv/bin/activate

recall-notifier doctor             # config, and which claims are weaker than a spec
recall-notifier addresses          # why no regex works; the stdlib against itself
recall-notifier identity           # how many people this list is, under each policy
recall-notifier merges --policy folded
recall-notifier states             # what a signal tells you, and what it cannot
recall-notifier timing             # when the answer arrives against when it was needed
recall-notifier compose            # the two-document problem
recall-notifier compose --text-from-html
recall-notifier report -o out/     # the honest report
recall-notifier check              # exit 1 on what is fixable at source
recall-notifier explain "Sato, Kenji <k.sato@example.jp>"
```

| Command | Exit |
|:--|:--|
| `check` | **1** on a row with no mailbox, a row that produced extra recipients, or a message whose two parts disagree |
| `report` | **1** if the list carries either of the first two |
| everything else | 0 |

`check` does **not** fail on undecidable delivery, normalisation ambiguity or a silently
stripped comment. Those are properties of email, not defects anyone can fix, and a gate that
fires on every accepted message gets switched off inside a week.

---

## Testing

```bash
pytest                                                  # 227 tests, ~2s
pytest --cov=recall_notifier --cov-report=term-missing   # 99%
```

Six tests exist to stop the others being vacuous: every `Signal`, every `Decidability`, every
`Fidelity`, both sides of the deadline, and the `PLANTED` manifest matching what is on disk.

Four delivery outcomes are **planted on named mailboxes** rather than produced by the hash,
because the shipped corpus otherwise emitted no `REJECTED` at all — which would have left
`Decidability.IMMEDIATE`, `known_by_deadline=True` and the entire "a NO is the only
unambiguous answer" finding untested. Planting them explicitly is inspectable; tuning the
hash until the numbers came out would not have been.

---

## Four Things I Got Wrong, Found by Reading Output

**A branch that could never fire.** `parse_address` scanned for comment nesting in
`parseaddr`'s output — which has already had comments removed. Verified across twelve inputs:
depth is **always** 0 there. The reporting branch was dead code that made the function look
more careful than it was. Now it scans the raw string.

**An empty bucket in the table.** `bounced` showed **zero** outcomes, because the forward map
took only the outcome and `NEVER_ACCEPTED` mapped to `REJECTED`. The real cause is better than
the bug: a rejection and a bounce are the **same outcome discovered at different times**, which
is why timing needs its own axis.

**A boolean that meant the wrong thing.** `determined` returned True for a deferred message —
`IN_FLIGHT` is one consistent state, but it is not an *outcome*. So something still being
retried was reported as settled. And the summary called the whole ambiguity gap permanent,
which was wrong for exactly those rows; `silent` and `pending` are now separate.

**Two checks that could not fail.** The HTML/text agreement check first measured raw character
distance in a 40-character window — and the *correct* template failed it at 42, because the gap
is made of markup. Replaced with a structural column check. Then the text side asked whether
label and value were on the same **line**, which tag-stripping satisfies **vacuously** by
collapsing the document onto one line. That is the `all([])` trap in different clothes. Now it
requires adjacency.

---

## Scope: What This Deliberately Does Not Do

**Send email.** There is no SMTP client and no network. Every finding here is about what a
sender *cannot* learn, and a real socket changes none of them. Outcomes come from a
deterministic fixture, which `doctor` says out loud.

**Route through SES or the Gmail API**, which the brief asks for. Worth doing — the brief is
right that SES beats raw SMTP — but it does not change a single conclusion above, and the
conclusions were the point.

**Guess whether a mailbox is a role account or a person.** `safety@example.coop` is in the
corpus precisely because one mailbox with unknown readership is not something an address
tells you.

---

## Tradeoffs

**The failure ceiling is weak.** On this corpus it is the entire recipient list, because it
genuinely is possible that every accepted message was discarded. Unsatisfying, and correct.

**`FOLDING_DOMAINS` is a hardcoded guess.** It cannot be derived from an address and it goes
stale. `normalise_per_domain` is the obvious improvement and it does not escape the problem —
it only moves the unknowable part.

**The outcome proportions are invented**, not measured. They are set so the silent case
dominates, because that is what makes the ambiguity gap the interesting part.

**Whether `IN_SPAM` is a failure is a judgement.** So is excluding `IN_INBOX`. Both are listed
as judgements by `doctor` rather than presented as findings.

**The corpus is mine and it is small.** "2 of 26 knowable in time" is a fact about 29 rows I
wrote, not an estimate for anyone's recipient list.

**The `parseaddr` claims rest on implementation behaviour**, not on a spec. A CPython change
could invalidate them.

**Nothing here fixes anything.** Clean the recipient list, publish a deadline you can actually
verify against, and accept that for most recipients you will never know.

---

## Configuration

```bash
RN_RECIPIENTS=data/recipients.csv
RN_DEADLINE_HOURS=24         # recalls are set in hours
RN_GIVE_UP_HOURS=96          # the LOW end of RFC 5321 4.5.4.1's own range
RN_NORMALISATION=rfc5321     # exact | rfc5321 | lowercase | folded
RN_TEXT_FROM_HTML=false      # true reproduces the shortcut, and what it costs
```

`give_up_hours` defaults to the **low** end of the spec's range, so the lag this tool reports
is the smallest a compliant MTA could produce rather than the most alarming.

---

## Stack

| Concern | Choice |
|:--|:--|
| Language | Python 3.11+ |
| Models + config | Pydantic, Pydantic Settings |
| CLI | Click |
| Templates | Jinja2 with **StrictUndefined**, so a missing fact fails loudly instead of rendering blank |
| Address parsing | `email.utils`, plus a counter-based comment scan a regex cannot replace |
| Output | Rich |
| Tests | pytest, Click's CliRunner |
| Network, SMTP, models/AI | none, deliberately |

The corpus is deterministic via `data/generate.py`: 29 rows with planted cases — case
variants, Gmail dot and `+tag` variants, a non-folding domain where those dots matter,
comments at depth 1 and 2, a display-name comma that makes a surname into a recipient, a
quoted local part, an RFC 5321 address literal, a string with no `@`, an exact duplicate, and
a role address.
