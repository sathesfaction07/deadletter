"""When the answer arrives, compared with when it was needed.

RFC 5321 4.5.4.1 on retrying a temporary failure:

    "Retries continue until the message is transmitted or the sender gives up; the give-up
     time generally needs to be at least 4-5 days."

A product recall does not have 4-5 days. Notification deadlines are set in hours, by
regulators or by the fact that the product is dangerous now. So the mechanism the brief
recommends for delivery confidence reports its findings between one and two orders of
magnitude later than the deadline it is meant to protect.

That makes bounce tracking a post-mortem instrument. It is genuinely useful for the
post-mortem. It is not an input to the decision it is being asked to inform.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from .models import Decidability, Signal

#: RFC 5321 4.5.4.1. Quoted rather than paraphrased because the number is the argument.
RFC5321_GIVE_UP = (
    "Retries continue until the message is transmitted or the sender gives up; the give-up "
    "time generally needs to be at least 4-5 days. (RFC 5321 4.5.4.1)"
)

#: The lower end of that range, in hours. Used as the default give-up window.
SPEC_MINIMUM_GIVE_UP_HOURS: float = 4 * 24.0


class Budget(BaseModel):
    """A recall's notification deadline set against SMTP's retry window."""

    model_config = ConfigDict(frozen=True)

    deadline_hours: float = Field(gt=0)
    give_up_hours: float = Field(gt=0)

    @property
    def lag_ratio(self) -> float:
        """How many times longer the retry window is than the deadline.

        Above 1.0 means a deferred message cannot be resolved in time, whatever anyone does.
        """
        return self.give_up_hours / self.deadline_hours

    @property
    def deadline_inside_window(self) -> bool:
        return self.deadline_hours < self.give_up_hours

    def decidable_by_deadline(self) -> dict[str, bool]:
        """Which signal classes can settle a recipient's fate before the deadline.

        `bounced` is the interesting one: it depends entirely on whether the DSN happens to
        arrive early, which is not something a sender controls or can predict.
        """
        return {
            Signal.REJECTED.value: True,
            Signal.BOUNCED.value: not self.deadline_inside_window,
            Signal.DEFERRED.value: not self.deadline_inside_window,
            Signal.NOTHING.value: False,
        }

    @property
    def actionable_classes(self) -> int:
        return sum(self.decidable_by_deadline().values())

    def summary(self) -> str:
        if not self.deadline_inside_window:
            return (
                f"a {self.deadline_hours:g}h deadline is longer than the {self.give_up_hours:g}h "
                f"give-up window, so every signal that is ever coming arrives in time. This is "
                f"the comfortable case and it is not the one recalls are in."
            )
        return (
            f"the retry window is {self.lag_ratio:.1f}x the deadline "
            f"({self.give_up_hours:g}h against {self.deadline_hours:g}h), so a deferred message "
            f"cannot be resolved before the deadline no matter what the sender does. "
            f"{self.actionable_classes} of {len(self.decidable_by_deadline())} signal classes "
            f"are actionable in time, and it is the one that says NO."
        )


def signal_arrival(signal: Signal, give_up_hours: float) -> tuple[Decidability, str]:
    """When each signal class becomes available, and why."""
    if signal is Signal.REJECTED:
        return (
            Decidability.IMMEDIATE,
            "5xx during the SMTP conversation, so it is known before the connection closes",
        )
    if signal is Signal.DEFERRED:
        return (
            Decidability.EVENTUAL,
            f"4xx means retry; nothing is settled until the {give_up_hours:g}h window closes",
        )
    if signal is Signal.BOUNCED:
        return (
            Decidability.EVENTUAL,
            f"a DSN arrives whenever the far side gets round to it, up to {give_up_hours:g}h",
        )
    return (
        Decidability.NEVER,
        "no signal is emitted for a message that was accepted, whatever became of it after",
    )


def budget_table(
    deadlines: tuple[float, ...] = (1.0, 6.0, 24.0, 72.0, 120.0),
    give_up_hours: float = SPEC_MINIMUM_GIVE_UP_HOURS,
) -> list[tuple[float, float, int, bool]]:
    """Actionable signal classes across a range of deadlines.

    The row that matters is 24h: a one-day notification deadline against the spec's minimum
    retry window leaves exactly one signal class usable.
    """
    rows = []
    for deadline in deadlines:
        budget = Budget(deadline_hours=deadline, give_up_hours=give_up_hours)
        rows.append(
            (deadline, budget.lag_ratio, budget.actionable_classes, budget.deadline_inside_window)
        )
    return rows
