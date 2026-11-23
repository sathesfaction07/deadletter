"""What a signal tells you about what happened, which is less than it appears.

The brief's verdict is that "bounce/complaint tracking tells you who didn't receive it".
It does not. It enumerates a LOWER BOUND on the failures and says nothing about the rest.

The reason is that the map from what happened (`TrueState`) to what the sender sees
(`Signal`) is not injective. Four distinct outcomes emit no signal at all:

    READ         -- a human read it
    IN_INBOX     -- delivered, unread
    IN_SPAM      -- delivered somewhere nobody looks
    DISCARDED    -- accepted with a 2xx, then dropped on the floor

Two of those four are failures. Silence is consistent with all four, and no amount of
waiting separates them, because none of them ever emits anything. So "no bounce" is not
evidence of delivery -- it is the absence of evidence either way.

The inversion worth noticing: the only signals that determine an outcome are the NEGATIVE
ones. A 5xx rejection pins the state exactly. Silence never does. You can learn that you
failed; you cannot learn that you succeeded.

(The not-injective shape is the same one Shoehorn found in the heading-level to
outline map. Reused because the failure has the same structure, not offered as new.)
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from .models import FAILURE_STATES, Attempt, Decidability, Signal, TrueState, Verdict

#: The states that emit nothing observable. This tuple IS the finding: its length is the
#: floor on how ambiguous silence can ever be, and it does not shrink with time.
SILENT_STATES: tuple[TrueState, ...] = (
    TrueState.READ,
    TrueState.IN_INBOX,
    TrueState.IN_SPAM,
    TrueState.DISCARDED,
)

#: How many TrueStates silence can never distinguish. Named so tests can assert on the
#: number rather than restating the tuple.
AMBIGUITY_FLOOR: int = len(SILENT_STATES)


def emits_signal(state: TrueState, *, discovered_at_handover: bool = True) -> Signal:
    """What the sender observes, given what actually happened.

    Note the second parameter. The signal is NOT a function of the state alone:
    NEVER_ACCEPTED produces REJECTED when the receiving MTA refuses at RCPT TO, and BOUNCED
    when the same refusal surfaces later as a DSN. Identical outcome, different signal,
    and the only difference is WHEN it was found out.

    An earlier version took only the state, which left `bounced` as an empty bucket in
    `collapse_table` -- a row that could never be populated, sitting in the table looking
    like it meant something.
    """
    if state is TrueState.NEVER_ACCEPTED:
        return Signal.REJECTED if discovered_at_handover else Signal.BOUNCED
    if state is TrueState.IN_FLIGHT:
        return Signal.DEFERRED
    return Signal.NOTHING


def consistent_states(signal: Signal, window_closed: bool) -> tuple[TrueState, ...]:
    """Every TrueState the observation fails to rule out.

    `window_closed` is whether the retry window has expired. It is the only thing that ever
    reduces the set, and it reduces it by exactly one member -- IN_FLIGHT -- taking silence
    from five candidates to four. Never to one.
    """
    if signal is Signal.REJECTED:
        return (TrueState.NEVER_ACCEPTED,)
    if signal is Signal.BOUNCED:
        # A DSN arrived. Late, but unambiguous about the outcome.
        return (TrueState.NEVER_ACCEPTED,)
    if signal is Signal.DEFERRED:
        if not window_closed:
            return (TrueState.IN_FLIGHT,)
        # Deferred, window closed, and no DSN ever came. Something got through, or something
        # gave up quietly. Back to the silent four.
        return SILENT_STATES
    # NOTHING
    if window_closed:
        return SILENT_STATES
    return (*SILENT_STATES, TrueState.IN_FLIGHT)


def decidability(signal: Signal) -> Decidability:
    """When, if ever, this signal settles the outcome."""
    if signal is Signal.REJECTED:
        return Decidability.IMMEDIATE
    if signal in (Signal.BOUNCED, Signal.DEFERRED):
        return Decidability.EVENTUAL
    return Decidability.NEVER


def verdict(attempt: Attempt, deadline_hours: float, give_up_hours: float) -> Verdict:
    """Everything that can honestly be said about one recipient.

    `known_by_deadline` is the number a recall programme actually needs, and it is false for
    every outcome that is not a synchronous rejection or a bounce that happened to arrive in
    time.
    """
    window_closed = attempt.elapsed_hours >= give_up_hours
    states = consistent_states(attempt.signal, window_closed)
    how = decidability(attempt.signal)

    if how is Decidability.IMMEDIATE:
        known = True
        detail = "5xx at handover: the only unambiguous answer SMTP ever gives, and it is a NO"
    elif attempt.signal is Signal.BOUNCED:
        known = attempt.elapsed_hours <= deadline_hours
        detail = (
            f"a DSN arrived at {attempt.elapsed_hours:g}h, "
            + (
                "inside the deadline"
                if known
                else f"which is AFTER the {deadline_hours:g}h deadline -- known too late to act on"
            )
        )
    elif attempt.signal is Signal.DEFERRED:
        known = False
        detail = (
            f"still being retried; nothing is decided until the {give_up_hours:g}h give-up "
            f"window closes, which is after the {deadline_hours:g}h deadline"
        )
    else:
        known = False
        detail = (
            f"no signal, and there will not be one. {len(states)} outcomes remain consistent, "
            f"{sum(1 for s in states if s in FAILURE_STATES)} of which mean this customer was "
            f"never informed"
        )

    return Verdict(
        mailbox=attempt.mailbox,
        signal=attempt.signal,
        consistent_states=states,
        decidability=how,
        known_by_deadline=known,
        detail=detail,
    )


class FailureBounds(BaseModel):
    """How many recipients were not informed: a range, because the number is not observable.

    The brief asks for the set. What exists is `floor <= truth <= ceiling`, where the gap is
    made of recipients whose outcome emits no signal. Reporting a single number here would
    mean picking one end and not saying so.
    """

    model_config = ConfigDict(frozen=True)

    recipients: int
    floor: int
    ceiling: int
    determined: int
    ambiguous: int
    #: Ambiguous AND no signal will ever arrive. This part of the gap is permanent.
    silent: int
    #: Ambiguous but a signal is still coming -- it will just arrive after the deadline.
    #: Kept separate because an earlier version of `summary` called the whole gap permanent,
    #: which overstated the case for the deferred ones.
    pending: int

    @property
    def gap(self) -> int:
        return self.ceiling - self.floor

    @property
    def observable(self) -> bool:
        """True only when every recipient's outcome was determined by some signal."""
        return self.gap == 0

    def summary(self) -> str:
        if self.observable:
            return (
                f"every one of {self.recipients} recipients produced a determining signal, so "
                f"{self.floor} failures is exact. That does not generalise -- it means this run "
                f"happened to contain no silent outcomes."
            )
        parts = []
        if self.silent:
            parts.append(f"{self.silent} will never produce a signal at all")
        if self.pending:
            parts.append(f"{self.pending} will resolve, but only after the deadline")
        return (
            f"between {self.floor} and {self.ceiling} of {self.recipients} recipients were not "
            f"informed. Of the {self.gap} in between, {' and '.join(parts)}."
        )


def failure_bounds(verdicts: list[Verdict]) -> FailureBounds:
    """Turn per-recipient verdicts into the range the sender can honestly claim."""
    determined_failures = sum(
        1 for v in verdicts if v.determined and v.consistent_states[0] in FAILURE_STATES
    )
    unsettled = [v for v in verdicts if v.ambiguous_about_failure]
    return FailureBounds(
        recipients=len(verdicts),
        floor=determined_failures,
        ceiling=determined_failures + len(unsettled),
        determined=sum(1 for v in verdicts if v.determined),
        ambiguous=len(unsettled),
        silent=sum(1 for v in unsettled if v.decidability is Decidability.NEVER),
        pending=sum(1 for v in unsettled if v.decidability is not Decidability.NEVER),
    )


def collapse_table() -> list[tuple[str, int, int, str]]:
    """The forward map, tabulated: how many TrueStates map onto each Signal.

    Reading this table is the argument. Three signals come from one state each; one signal
    comes from four, and it is the signal you get when nothing goes visibly wrong.

    REJECTED and BOUNCED both carry NEVER_ACCEPTED, because they are the same outcome found
    out at different times -- which is why timing needs its own axis rather than being
    folded into the signal.
    """
    buckets: dict[Signal, list[TrueState]] = {s: [] for s in Signal}
    for state in TrueState:
        for sync in (True, False):
            signal = emits_signal(state, discovered_at_handover=sync)
            if state not in buckets[signal]:
                buckets[signal].append(state)
    rows = []
    for signal, states in buckets.items():
        failures = sum(1 for s in states if s in FAILURE_STATES)
        rows.append((signal.value, len(states), failures, ", ".join(s.value for s in states)))
    return rows
