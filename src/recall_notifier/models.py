"""The vocabulary. Four enums carry the whole argument.

`Signal` is what the sending side OBSERVES. `TrueState` is what actually happened to the
message. The two are different types on purpose: the central finding of this project is that
the map from TrueState to Signal is not injective, so no amount of care on the sending side
recovers the state from the signal.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Signal(StrEnum):
    """What the sender can actually observe. There are only four, and one is the absence of
    the other three.

    REJECTED is the only signal that determines the outcome. Every other signal, including
    silence, is consistent with more than one TrueState.
    """

    REJECTED = "rejected"  # 5xx at RCPT TO or DATA -- synchronous, permanent, UNAMBIGUOUS
    DEFERRED = "deferred"  # 4xx -- the receiving MTA said "not now", retry pending
    BOUNCED = "bounced"  # an asynchronous DSN arrived, possibly days later
    NOTHING = "nothing"  # no signal. NOT the same as success, and this is the whole problem


class TrueState(StrEnum):
    """What actually became of the message. The sender does not get to see this."""

    READ = "read"  # a human read it. The only state that discharges a recall duty.
    IN_INBOX = "in_inbox"  # delivered, sitting unread
    IN_SPAM = "in_spam"  # delivered to a folder nobody opens
    DISCARDED = "discarded"  # accepted with a 2xx, then dropped. NO SIGNAL, EVER.
    NEVER_ACCEPTED = "never_accepted"  # refused outright
    IN_FLIGHT = "in_flight"  # still being retried; outcome not yet determined


#: Which TrueStates mean the recipient was NOT informed. IN_INBOX is deliberately absent:
#: a notice sitting unread in an inbox was delivered, and delivery is all a sender can be
#: responsible for. IN_SPAM is present because a spam folder is not a place people look.
FAILURE_STATES: frozenset[TrueState] = frozenset(
    {TrueState.IN_SPAM, TrueState.DISCARDED, TrueState.NEVER_ACCEPTED}
)


class Decidability(StrEnum):
    """WHEN the outcome becomes knowable, relative to a deadline. This is the axis the brief
    does not have, and it is the one that matters for a recall."""

    IMMEDIATE = "immediate"  # known at send time. Actionable within any deadline.
    EVENTUAL = "eventual"  # known when the retry window closes -- typically DAYS later
    NEVER = "never"  # no signal is ever emitted. Indistinguishable from success.


class Normalisation(StrEnum):
    """How to decide whether two address strings are the same person.

    EXACT and RFC5321 are defensible readings of the spec. LOWERCASE is what almost
    everybody ships. FOLDED is what Gmail actually does. They give different recipient
    counts for the same list, and the differences are not small.
    """

    EXACT = "exact"  # byte-identical. Never merges. Duplicates get duplicate notices.
    RFC5321 = "rfc5321"  # lowercase the domain ONLY -- RFC 5321 2.4 makes local-part case-SENSITIVE
    LOWERCASE = "lowercase"  # lowercase everything. Common, and NOT what the spec says.
    FOLDED = "folded"  # strip dots and +tags, lowercase. Gmail's behaviour, no RFC backing.


class Fidelity(StrEnum):
    """How a parsed address relates to the string it came from.

    Four values rather than a `valid: bool`, because INVENTED and DROPPED fail in opposite
    directions and a boolean collapses them. Same distinction as DocConsolidator's Fidelity,
    and it is the same distinction for the same reason -- not a new idea, reused because the
    failure has the same shape.
    """

    CLEAN = "clean"  # the string is a mailbox and parsing returned it unchanged
    NORMALISED = "normalised"  # a mailbox, but the parser rewrote it (comments stripped)
    DROPPED = "dropped"  # a valid mailbox the parser refused -- a recipient LOST
    INVENTED = "invented"  # the parser produced a recipient the string did not name


class Recipient(BaseModel):
    """One row of a recipient list, as given. `raw` is preserved verbatim so that every
    later claim can be traced back to what was actually supplied."""

    model_config = ConfigDict(frozen=True)

    raw: str
    name: str = ""
    lot: str = ""

    @field_validator("raw")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("raw address string cannot be blank")
        return v


class ParsedAddress(BaseModel):
    """The result of trying to turn one string into one mailbox.

    `mailbox` is None when no parser produced one. `disagreement` records that the two
    stdlib entry points returned different answers for the same input -- which they do, in
    both directions.
    """

    model_config = ConfigDict(frozen=True)

    raw: str
    mailbox: str | None
    fidelity: Fidelity
    detail: str
    disagreement: bool = False
    #: How many mailboxes the parsers between them claimed this ONE string names.
    #: 0 means the string was dropped; 2 or more means a recipient was invented.
    claimed_count: int = 1

    @model_validator(mode="after")
    def _fidelity_agrees_with_mailbox(self) -> ParsedAddress:
        if self.fidelity is Fidelity.DROPPED and self.mailbox is not None:
            raise ValueError("DROPPED must carry no mailbox")
        if self.fidelity is not Fidelity.DROPPED and self.mailbox is None:
            raise ValueError(f"{self.fidelity.value} requires a mailbox")
        if self.fidelity is Fidelity.CLEAN and self.mailbox != self.raw:
            raise ValueError("CLEAN means the parser returned the string unchanged")
        if self.fidelity is Fidelity.INVENTED and self.claimed_count < 2:
            raise ValueError("INVENTED means more mailboxes were claimed than the string named")
        return self

    @property
    def deliverable(self) -> bool:
        return self.mailbox is not None


class Attempt(BaseModel):
    """One delivery attempt and everything the sender learned from it.

    `signal` is an observation. `elapsed_hours` is when the signal arrived, which for
    BOUNCED can be days after the send.
    """

    model_config = ConfigDict(frozen=True)

    mailbox: str
    signal: Signal
    elapsed_hours: float = Field(ge=0.0)
    smtp_code: int | None = None
    detail: str = ""

    @model_validator(mode="after")
    def _signal_agrees_with_code(self) -> Attempt:
        if self.signal is Signal.REJECTED and not (self.smtp_code and 500 <= self.smtp_code < 600):
            raise ValueError("REJECTED requires a 5xx code")
        if self.signal is Signal.DEFERRED and not (self.smtp_code and 400 <= self.smtp_code < 500):
            raise ValueError("DEFERRED requires a 4xx code")
        if self.signal is Signal.NOTHING and self.elapsed_hours != 0.0:
            raise ValueError("NOTHING is the absence of a signal, so it has no arrival time")
        return self


class Verdict(BaseModel):
    """What can honestly be said about one recipient at a given report time.

    `consistent_states` is the point of the whole model: the set of TrueStates the observed
    signal does not rule out. It has more than one member for every signal except REJECTED.
    """

    model_config = ConfigDict(frozen=True)

    mailbox: str
    signal: Signal
    consistent_states: tuple[TrueState, ...]
    decidability: Decidability
    known_by_deadline: bool
    detail: str = ""

    @model_validator(mode="after")
    def _states_non_empty(self) -> Verdict:
        if not self.consistent_states:
            raise ValueError("a signal that rules out every state is a bug in the state map")
        return self

    @property
    def determined(self) -> bool:
        """True only when the signal settles the OUTCOME.

        IN_FLIGHT is a single consistent state but it is not an outcome. An earlier version
        returned True here for a deferred message, reporting something still being retried
        as settled -- a plausible boolean that meant the wrong thing.
        """
        return (
            len(self.consistent_states) == 1
            and self.consistent_states[0] is not TrueState.IN_FLIGHT
        )

    @property
    def could_be_failure(self) -> bool:
        return any(s in FAILURE_STATES for s in self.consistent_states)

    @property
    def could_be_success(self) -> bool:
        return any(s not in FAILURE_STATES for s in self.consistent_states)

    @property
    def ambiguous_about_failure(self) -> bool:
        """The state that matters: this recipient may or may not have been informed, and
        nothing observable says which.

        Defined as "the outcome is not settled" rather than as `could_be_failure and
        could_be_success`, because IN_FLIGHT is in neither set and a still-retrying message
        is exactly a case where nobody knows yet.
        """
        return not self.determined
