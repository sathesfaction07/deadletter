# Deadletter — Technical Architecture

## Overview

Sends a recall notice, then reports what a delivery report **cannot** tell you.

**Design principle:** the brief asks *"did every recipient actually receive the
notification?"* and answers *"bounce/complaint tracking tells you who didn't receive it."*
It does not. It enumerates a **lower bound** on the failures, and the part it misses arrives
**after** the deadline it was meant to protect.

No model. The accuracy problem is RFC semantics and time arithmetic.

---

## System Architecture

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                        CLI (deadletter)                                  │
│                                                                              │
│  doctor     config; and which claims rest on a SPEC, which on IMPLEMENTATION  │
│             BEHAVIOUR, and which are outright GUESSES that go stale           │
│  addresses  why no regex validates an address; the stdlib against itself      │
│  identity   how many people this list is -- one count per policy              │
│  merges     which addresses one policy calls one person, and which disagree    │
│  states     what a signal tells you about what happened, and what it cannot   │
│  timing     when the answer arrives, against when the recall needed it        │
│  compose    the two-document problem, and what tag-stripping costs            │
│  report     the honest report: a RANGE, never a number                        │
│  check      EXIT 1 only on what is fixable at source. Does NOT fail on        │
│             undecidable delivery, normalisation ambiguity or a silently       │
│             stripped comment -- those are properties of email, and a gate     │
│             that fires on every accepted message gets switched off inside a   │
│             week                                                             │
│  explain    one supplied string: what was known, and what was not             │
└────────────────────────────────┬─────────────────────────────────────────────┘
                                 ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                             delivery.py                                       │
│                            THE COLLAPSE                                       │
│                                                                              │
│  Two separate types on purpose. `TrueState` is what became of the message;    │
│  `Signal` is what the sender OBSERVES. The map between them is NOT INJECTIVE, │
│  so no care on the sending side recovers the state from the signal.           │
│                                                                              │
│    signal     outcomes   failures   which                                    │
│    rejected   1          1          never_accepted                           │
│    deferred   1          0          in_flight                                │
│    bounced    1          1          never_accepted                           │
│    nothing    4          2          read, in_inbox, in_spam, discarded        │
│                                                            ^ THE COLLAPSE     │
│                                                                              │
│  READ, IN_INBOX, IN_SPAM and DISCARDED are four different things that         │
│  happened. TWO ARE FAILURES. All four look identical from the sending side,   │
│  so "no bounce" is not evidence of delivery -- it is the absence of evidence  │
│  either way.                                                                 │
│                                                                              │
│  `emits_signal` takes a SECOND parameter, `discovered_at_handover`, because   │
│  the signal is not a function of the outcome alone: NEVER_ACCEPTED produces   │
│  REJECTED at RCPT TO and BOUNCED when the same refusal surfaces days later.   │
│  An earlier version took only the outcome, which left `bounced` as an EMPTY   │
│  BUCKET in collapse_table -- a row that could never be populated, sitting in  │
│  the table looking like it meant something. The fix produced a better claim   │
│  than the bug: identical outcome, different signal, and the only difference   │
│  is WHEN it was found out.                                                   │
│                                                                              │
│  consistent_states(signal, window_closed)  and waiting does not help:        │
│                                                                              │
│    signal     window open     window closed   settled?                       │
│    rejected   1               1               yes                            │
│    deferred   1               4               NO                             │
│    bounced    1               1               yes                            │
│    nothing    5               4               NO                             │
│                                                                              │
│  Closing the retry window removes EXACTLY ONE candidate -- IN_FLIGHT --       │
│  taking silence from 5 to 4. NEVER TO ONE. A report run a year later says     │
│  the same thing.                                                             │
│                                                                              │
│  THE INVERSION: the only signals that ever settle an outcome are `rejected`   │
│  and `bounced`, and BOTH mean the message was not accepted. You can learn     │
│  that you failed. You cannot learn that you succeeded.                       │
│                                                                              │
│  FailureBounds  floor <= truth <= ceiling, because the number is not          │
│    observable. The gap is split into `silent` (no signal is ever coming) and  │
│    `pending` (a signal is coming, after the deadline) -- an earlier summary    │
│    called the WHOLE gap permanent, which overstated the deferred rows.        │
└────────────────────────────────┬─────────────────────────────────────────────┘
                                 ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                              timing.py                                        │
│                                                                              │
│  RFC 5321 4.5.4.1: "the give-up time generally needs to be AT LEAST 4-5       │
│  DAYS." A recall deadline is set in HOURS.                                    │
│                                                                              │
│    deadline    window/deadline   actionable classes   deadline inside window?  │
│    1           96.0              1 of 4               YES                     │
│    24          4.0               1 of 4               YES                     │
│    72          1.3               1 of 4               YES                     │
│    120         0.8               3 of 4               no                      │
│                                                                              │
│  At 24h the retry window is 4x the deadline, so a deferred message CANNOT be  │
│  resolved in time whatever the sender does. One of four signal classes is     │
│  actionable, AND IT IS THE ONE THAT SAYS NO.                                  │
│                                                                              │
│  So bounce tracking is a post-mortem instrument -- genuinely useful for the    │
│  post-mortem, and not an input to the decision it is asked to inform.         │
│                                                                              │
│  give_up_hours defaults to the LOW end of the spec's own range, so the lag     │
│  reported is the smallest a compliant MTA could produce, not the worst.       │
└────────────────────────────────┬─────────────────────────────────────────────┘
                                 ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                             addresses.py                                      │
│                                                                              │
│  RFC 5322 3.2.2:   comment  = "(" *([FWS] ccontent) [FWS] ")"                │
│                    ccontent = ctext / quoted-pair / comment  <-- RECURSIVE    │
│                                                                              │
│  `comment` appears in its own expansion, so nesting is unbounded. A regex has │
│  finitely many states and cannot count it. THE ADDRESS SET IS NOT A REGULAR   │
│  LANGUAGE, so no regex recognises it -- a grammar fact, not a judgement about │
│  anyone's pattern. And comments are semantically TRANSPARENT, so every depth  │
│  is a legitimate way to write a real address.                                │
│                                                                              │
│    depth  a VALID address           everyone writes  careful  "RFC-compliant" │
│    1      user(x)@example.com       accept           REJECT   REJECT          │
│    3      user(((x)))@example.com   accept           REJECT   REJECT          │
│                                                                              │
│  NOT a threshold effect: the careful ones reject EVERY depth including 1.     │
│  The sloppy one accepts them all by ignoring parens. THE LEAST RIGOROUS       │
│  REGEX IS THE ONLY ONE THAT DELIVERS THIS CUSTOMER'S RECALL NOTICE.           │
│                                                                              │
│  And the directions do not cost the same:                                    │
│    accept an invalid address  -> one bounce                                  │
│    REJECT A VALID ADDRESS     -> a customer is never told the product is      │
│                                  dangerous                                   │
│                                                                              │
│  strip_comments()  a counter-based scan, written that way because a regex     │
│    provably cannot do it. Respects quoting: a paren inside a quoted string is │
│    a literal paren (RFC 5322 3.2.4). Raises on unbalanced input rather than   │
│    guessing.                                                                 │
│                                                                              │
│  THE STDLIB DISAGREES WITH ITSELF, in both directions:                        │
│                                                                              │
│    input                         parseaddr           getaddresses            │
│    not-an-address                'not-an-address'    ['not-an-address']      │
│    user@[192.168.1.1]            ''                  []                      │
│    Doe, John <john@example.com>  ''                  ['Doe', 'john@...']     │
│    user(a(b)c)@example.com       'user@example.com'  ['user@example.com']    │
│                                                                              │
│    * `not-an-address` comes back AS A MAILBOX. No @, and no error either --   │
│      an unguarded caller attempts delivery to a surname.                     │
│    * `user@[192.168.1.1]` is REFUSED, and RFC 5321 4.1.3 permits it.         │
│    * `Doe, John <...>` becomes TWO recipients, the first a SURNAME, while     │
│      parseaddr returns nothing. ONE INVENTS A RECIPIENT AND THE OTHER DROPS   │
│      IT, on the same input.                                                  │
│    * comments are stripped SILENTLY, so the mailbox delivered to is not the   │
│      string supplied.                                                        │
│                                                                              │
│  Fidelity  CLEAN / NORMALISED / DROPPED / INVENTED. Four values rather than   │
│    a `valid: bool`, because INVENTED and DROPPED fail in OPPOSITE directions  │
│    and a boolean collapses them. (Same distinction as Shoehorn's       │
│    Fidelity, reused for the same reason -- not offered as new.)               │
│                                                                              │
│    The two ways of being DROPPED get DIFFERENT explanations, because they     │
│    are different failures: one string came back and would be delivered to,    │
│    the other came back empty and is simply gone.                              │
│                                                                              │
│  Comment depth is scanned on the RAW string. Scanning parseaddr's output      │
│  would report 0 every time -- verified across twelve inputs including         │
│  `us(er)@ex.com` -> `us@ex.com` -- making the reporting branch DEAD CODE      │
│  that made the function look more careful than it was.                       │
└────────────────────────────────┬─────────────────────────────────────────────┘
                                 ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                             identity.py                                       │
│                                                                              │
│  The brief asks for "batch deduplication: don't notify the same recipient     │
│  twice". That needs an identity function on addresses, and there isn't one.   │
│                                                                              │
│  RFC 5321 2.4: the LOCAL PART IS CASE-SENSITIVE; only the domain is not. So   │
│  `John@x` and `john@x` are, per the spec, potentially different mailboxes.    │
│  Meanwhile Gmail ignores dots and truncates at `+`, which NO RFC sanctions    │
│  and which is invisible in the string.                                       │
│                                                                              │
│    exact      -> 5 recipients from 5 addresses                               │
│    rfc5321    -> 5                                                           │
│    lowercase  -> 4      (what almost everybody ships; not what the spec says) │
│    folded     -> 1      (what Gmail actually does)                            │
│                                                                              │
│  SAME FIVE ADDRESSES, BETWEEN ONE AND FIVE PEOPLE. The count is a function    │
│  of POLICY, not of the list.                                                 │
│                                                                              │
│  possible_duplicates and possible_silences return the SAME NUMBER, and both   │
│  exist because the number means two different things depending on which way   │
│  the truth lies. Merge too eagerly and customers are never told; merge too    │
│  little and they get a second copy. Same arithmetic, wildly different cost --  │
│  so for a SAFETY notice the defensible default is the one that DUPLICATES,     │
│  which is exactly the behaviour the brief asks to remove.                     │
│                                                                              │
│  normalise_per_domain()  the obvious improvement, included BECAUSE it does    │
│    not escape the problem: it still rests on FOLDING_DOMAINS, a hardcoded     │
│    guess that cannot be derived from an address and that goes stale. It moves │
│    the unknowable part rather than removing it. `doctor` says so.             │
│                                                                              │
│  Dedup is NOT new here -- five other portfolio projects do it. What is new is │
│  that the KEY is unknowable.                                                  │
└────────────────────────────────┬─────────────────────────────────────────────┘
                                 ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                    compose.py                      campaign.py                │
│                                                                              │
│  A multipart/alternative message is TWO        NO NETWORK, NO SMTP CLIENT.    │
│  DOCUMENTS. The client picks one; the           Outcomes come from a          │
│  recipient never sees the other. Whether       deterministic fixture, because │
│  they make the same claims is nobody's         every finding here is about    │
│  job.                                          what a sender CANNOT learn,   │
│                                                and a real socket changes     │
│  Jinja2 with StrictUndefined, so a             none of them. Stated as a     │
│  template naming a fact that does not          limitation, and `doctor` says  │
│  exist FAILS LOUDLY. The default renders       it out loud.                  │
│  an empty string -- for a recall notice                                      │
│  that means shipping a blank hazard            PLANTED_OUTCOMES fixes four    │
│  description with no error anywhere.           named mailboxes so EVERY       │
│                                                signal, every Decidability    │
│  Association is checked DIFFERENTLY per        and both sides of the deadline │
│  format, on purpose:                           actually occur. Without them   │
│    HTML  header column index vs cell           the corpus emitted no         │
│          column index -- STRUCTURAL            REJECTED at all, leaving       │
│    text  the value must DIRECTLY FOLLOW        Decidability.IMMEDIATE,        │
│          its label -- ADJACENCY                known_by_deadline=True and the │
│                                                "a NO is the only unambiguous  │
│  Two earlier versions could not fail:          answer" finding UNTESTED.      │
│    (1) raw character distance in a             Planting explicitly is         │
│        40-char window -- and the CORRECT       inspectable; tuning the hash   │
│        template failed at 42, because          until the numbers came out     │
│        the gap is made of MARKUP. A            would not have been.           │
│        threshold artifact reporting a                                        │
│        good message as divergent is            The recipient list is NOT      │
│        worse than no check.                    sanitised on the way in. The   │
│    (2) same-LINE, which tag-stripping          point is to report what a real │
│        satisfies VACUOUSLY by collapsing       list contains, and quietly     │
│        everything onto one line. The           fixing it would hide the       │
│        `all([])` trap in other clothes.        input.                         │
│                                                                              │
│  The shortcut produces:                        Suppression happens on the     │
│    ... Lot Sold between LOT-4471 ...           identity key, so WHICH rows    │
│  Header cells now adjacent to each             are skipped depends on the     │
│  OTHER, so LOT-4471 sits next to nothing       policy -- and `spread` records  │
│  saying it is a lot number. THE VALUE          what the others would have     │
│  SURVIVES; THE FACT DOES NOT -- which is       done, so the choice is visible │
│  why a value-presence check passes and         in the output rather than      │
│  says nothing.                                 buried in a config value.     │
│                                                                              │
│  (Shoehorn's finding through a          informed_ceiling is named a    │
│  different door. Difference: here BOTH         CEILING so nobody reads it as  │
│  documents ship, and only one is read.)        a count of people reached.     │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## The Findings

### One: four outcomes emit nothing, and waiting narrows it by exactly one

`nothing` is consistent with `READ`, `IN_INBOX`, `IN_SPAM` and `DISCARDED`. Two are failures.
Closing the retry window takes the count from 5 to 4, never to 1.

### Two: only a NO is ever unambiguous

`rejected` and `bounced` are the only signals that settle an outcome, and both mean the
message was not accepted.

### Three: the signal arrives 4x too late

RFC 5321's minimum give-up window is 96h. A recall deadline is 24h.

### Four: no regex validates an address, and the careful ones err expensively

Comments nest, so the language is not regular. The careful regexes reject valid addresses;
the sloppy one accepts them.

### Five: the recipient count is a policy choice

Five addresses, between one and five people, and nothing observable settles it.

---

## Data Flow

```
1.  deadletter report
2.  load 29 rows verbatim -- NO sanitising, because the input is the subject
3.  parse each: 24 CLEAN, 2 NORMALISED (comments stripped silently), 2 DROPPED,
      1 INVENTED (a display-name comma became a surname-as-recipient)
4.  suppress on the identity key: 1 row, under RFC5321. Under `folded` it is more.
5.  26 delivery attempts against the fixture
      18 nothing, 4 bounced, 3 deferred, 1 rejected
6.  per-recipient verdict: how many outcomes remain consistent, and when -- if ever --
      the answer arrives relative to the 24h deadline
7.  bounds: floor 5, ceiling 26. Of the 21 between, 18 NEVER decidable, 3 merely late.
8.  2 OF 26 outcomes were knowable by the deadline. One was a rejection.
9.  exit 1 -- not for the undecidability, but for the 2 unparseable rows and the 1
      invented recipient, all three of which a human can fix in the CSV
```

---

## Testing

```bash
pytest                                                    # 227 tests, ~2s
pytest --cov=recall_notifier --cov-report=term-missing      # 99%
```

| File | Covers |
|:--|:--|
| `conftest.py` | corpus loaded once, campaign run once, the five probe addresses |
| `unit/test_core.py` | non-regularity at five depths; the verdict inversion; quoting and escaping in the comment scan; unbalanced input raising; `parseaddr` accepting a string with no `@`; refusing an address literal; `getaddresses` inventing a recipient; the comment branch being **reachable**; the two DROPPED messages differing; every `Fidelity` occurring; the 1-to-5 identity spread; both error magnitudes; `per_domain` still resting on a guess; every model validator; **`IN_FLIGHT` not counting as settled** |
| `unit/test_delivery_timing_compose.py` | the four silent outcomes; the same outcome producing two signals; **no empty bucket**; the window closing by exactly one; only negative signals being decisive; the range not the number; **`silent` vs `pending`**; the 4x lag; one actionable class at 24h; the correct message **not** reported divergent; tag-stripping losing the association; **the one-line document not passing vacuously**; every signal and decidability occurring in the corpus; policy monotonicity; determinism |
| `integration/test_cli.py` | all eleven commands, every exit-code reason, the RFC citations, the JSON report's contents |

Six tests exist to stop the others being vacuous: every `Signal`, every `Decidability`, every
`Fidelity`, both sides of `known_by_deadline`, and `PLANTED` matching what is on disk.

Nothing is mocked. The `parseaddr` and `getaddresses` findings **are** the behaviour of
CPython, and a mock would assert my belief about it instead.

---

## Configuration

`RN_`-prefixed environment variables or a `.env` file. No list-typed fields, since Pydantic
Settings parses those as JSON and `RN_X=a,b` would fail with a decode error reading like a bug
in the tool.

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RN_", env_file=".env", extra="ignore")

    recipients: Path = Path("data/recipients.csv")
    deadline_hours: float = Field(default=24.0, gt=0)
    give_up_hours: float = Field(default=SPEC_MINIMUM_GIVE_UP_HOURS, gt=0)  # the LOW end
    normalisation: Normalisation = Normalisation.RFC5321   # the spec, not the common choice
    text_from_html: bool = False
```

`normalisation` defaults to `RFC5321` rather than to `LOWERCASE`, which is what almost
everybody ships — and `identity` prints what the choice costs either way rather than leaving
the default to imply it is safe.
