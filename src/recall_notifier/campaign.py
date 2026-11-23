"""Running a campaign, and reporting only what is supportable.

There is NO NETWORK HERE and no SMTP client. Delivery outcomes come from a deterministic
transport keyed on the recipient list, because every finding in this project is about what a
sender cannot learn, and a real socket does not change any of them. Shipping an SMTP client
would add plumbing and no argument. That is a limitation and it is stated as one.

What the transport DOES do is emit all four signals, with arrival times on both sides of the
deadline, so the reasoning downstream is exercised on real variety rather than asserted. The
PROPORTIONS are invented -- they are set so the silent case dominates, which is what makes
the ambiguity gap non-trivial, and no claim is made that they match anyone's real mail.
"""

from __future__ import annotations

import csv
import hashlib
from collections.abc import Iterable
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from .addresses import parse_address
from .compose import Notice, Rendered, render
from .delivery import FailureBounds, failure_bounds, verdict
from .identity import IdentitySpread, identity_spread, normalise
from .models import (
    Attempt,
    Fidelity,
    Normalisation,
    ParsedAddress,
    Recipient,
    Signal,
    Verdict,
)
from .timing import Budget


def load_recipients(path: Path) -> list[Recipient]:
    """Read a recipient list. Blank rows are skipped; nothing else is cleaned up.

    Deliberately not sanitising the addresses on the way in: the whole point is to report
    what a real list contains, and quietly fixing it here would hide the input.
    """
    rows: list[Recipient] = []
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            raw = (row.get("address") or "").strip()
            if not raw:
                continue
            rows.append(
                Recipient(raw=raw, name=(row.get("name") or ""), lot=(row.get("lot") or ""))
            )
    return rows


#: Outcomes planted on specific corpus mailboxes so that EVERY signal, every Decidability
#: and both sides of the deadline actually occur. Without these the shipped corpus produced
#: only `nothing`, `deferred` and one late `bounced` -- which left `REJECTED`,
#: `Decidability.IMMEDIATE` and `known_by_deadline=True` unexercised, and those three carry
#: the finding that a rejection is the only unambiguous answer SMTP gives. Planting them
#: explicitly is inspectable; tuning the hash until the numbers came out would not have been.
PLANTED_OUTCOMES: dict[str, tuple[Signal, float, int | None, str]] = {
    "bmehta@example.net": (
        Signal.REJECTED,
        0.0,
        550,
        "5.1.1 no such mailbox, refused at RCPT TO",
    ),
    "c.okafor@example.org": (
        Signal.BOUNCED,
        3.0,
        None,
        "DSN at 3h, mailbox over quota -- inside a 24h deadline, so actually actionable",
    ),
    "dlindqvist@example.se": (
        Signal.BOUNCED,
        78.0,
        None,
        "DSN at 78h after repeated deferral -- correct, and three days too late",
    ),
    "e.rossi@example.it": (
        Signal.DEFERRED,
        2.0,
        451,
        "4.7.1 greylisted, still retrying",
    ),
}


def _outcome_for(mailbox: str) -> tuple[Signal, float, int | None, str]:
    """A deterministic outcome for one mailbox.

    Four mailboxes carry planted outcomes (see `PLANTED_OUTCOMES`) so every branch of the
    reasoning is exercised by the shipped corpus. The rest are keyed on a hash of the
    address, so runs are reproducible and the mix is stable.

    The PROPORTIONS here are invented. They are set so the silent case dominates, because
    that is what makes the ambiguity gap the interesting part of the report -- but no claim
    is made that they match anyone's real mail.
    """
    if mailbox in PLANTED_OUTCOMES:
        return PLANTED_OUTCOMES[mailbox]
    digest = hashlib.sha256(mailbox.encode("utf-8")).digest()
    bucket = digest[0] % 20
    if bucket == 0:
        return Signal.REJECTED, 0.0, 550, "5.1.1 no such mailbox, refused at RCPT TO"
    if bucket == 1:
        return Signal.BOUNCED, 78.0, None, "DSN after repeated deferral"
    if bucket == 2:
        return Signal.BOUNCED, 3.0, None, "DSN arrived quickly, mailbox full"
    if bucket == 3:
        return Signal.DEFERRED, 2.0, 451, "4.7.1 greylisted, still retrying"
    return Signal.NOTHING, 0.0, None, "accepted; nothing further will ever be reported"


class RecipientReport(BaseModel):
    """One row of the report: what was supplied, what was sent to, what came back."""

    model_config = ConfigDict(frozen=True)

    raw: str
    parsed: ParsedAddress
    identity_key: str | None
    suppressed: bool
    attempt: Attempt | None
    verdict: Verdict | None

    @property
    def attempted(self) -> bool:
        return self.attempt is not None


class CampaignReport(BaseModel):
    """Everything the campaign can honestly say, including where it cannot say anything."""

    model_config = ConfigDict(frozen=True)

    supplied: int
    rows: tuple[RecipientReport, ...]
    spread: IdentitySpread
    bounds: FailureBounds
    budget: Budget
    rendered_agree: bool
    divergent_facts: tuple[str, ...]
    normalisation: str

    @property
    def undeliverable(self) -> tuple[RecipientReport, ...]:
        """Rows no parser turned into a mailbox. Fixable at source, so `check` gates on it."""
        return tuple(r for r in self.rows if r.parsed.fidelity is Fidelity.DROPPED)

    @property
    def invented(self) -> tuple[RecipientReport, ...]:
        """Rows where a parser produced more recipients than the row named."""
        return tuple(r for r in self.rows if r.parsed.fidelity is Fidelity.INVENTED)

    @property
    def disagreements(self) -> tuple[RecipientReport, ...]:
        """Rows where the two stdlib parsers returned different answers."""
        return tuple(r for r in self.rows if r.parsed.disagreement)

    @property
    def suppressed(self) -> tuple[RecipientReport, ...]:
        return tuple(r for r in self.rows if r.suppressed)

    @property
    def attempted(self) -> int:
        return sum(1 for r in self.rows if r.attempted)

    @property
    def informed_ceiling(self) -> int:
        """The most optimistic honest reading: everyone whose outcome was not a determined
        failure. Named `ceiling` so nobody mistakes it for a count of people reached."""
        return self.attempted - self.bounds.floor

    def as_dict(self) -> dict[str, object]:
        return {
            "supplied": self.supplied,
            "attempted": self.attempted,
            "normalisation": self.normalisation,
            "undeliverable": [r.raw for r in self.undeliverable],
            "invented": [r.raw for r in self.invented],
            "disagreements": [r.raw for r in self.disagreements],
            "suppressed": [r.raw for r in self.suppressed],
            "identity_counts": self.spread.counts,
            "identity_per_domain": self.spread.per_domain,
            "failures_floor": self.bounds.floor,
            "failures_ceiling": self.bounds.ceiling,
            "never_decidable": self.bounds.silent,
            "decidable_late": self.bounds.pending,
            "informed_ceiling": self.informed_ceiling,
            "deadline_hours": self.budget.deadline_hours,
            "give_up_hours": self.budget.give_up_hours,
            "lag_ratio": round(self.budget.lag_ratio, 2),
            "rendered_agree": self.rendered_agree,
            "divergent_facts": list(self.divergent_facts),
        }


def run_campaign(
    recipients: Iterable[Recipient],
    notice: Notice,
    *,
    deadline_hours: float,
    give_up_hours: float,
    policy: Normalisation,
    text_from_html: bool = False,
) -> tuple[CampaignReport, Rendered]:
    """Parse, deduplicate, attempt, and report.

    Suppression happens on the identity key, so which recipients get skipped depends on the
    policy -- and `spread` records what the other policies would have done, so the choice is
    visible in the output rather than buried in a config value.
    """
    supplied = list(recipients)
    rendered = render(notice, text_from_html=text_from_html)

    rows: list[RecipientReport] = []
    verdicts: list[Verdict] = []
    seen: set[str] = set()

    for recipient in supplied:
        parsed = parse_address(recipient.raw)
        if not parsed.deliverable:
            rows.append(
                RecipientReport(
                    raw=recipient.raw,
                    parsed=parsed,
                    identity_key=None,
                    suppressed=False,
                    attempt=None,
                    verdict=None,
                )
            )
            continue

        key = normalise(parsed.mailbox, policy)
        if key in seen:
            rows.append(
                RecipientReport(
                    raw=recipient.raw,
                    parsed=parsed,
                    identity_key=key,
                    suppressed=True,
                    attempt=None,
                    verdict=None,
                )
            )
            continue
        seen.add(key)

        signal, elapsed, code, detail = _outcome_for(parsed.mailbox)
        attempt = Attempt(
            mailbox=parsed.mailbox,
            signal=signal,
            elapsed_hours=elapsed,
            smtp_code=code,
            detail=detail,
        )
        row_verdict = verdict(attempt, deadline_hours, give_up_hours)
        verdicts.append(row_verdict)
        rows.append(
            RecipientReport(
                raw=recipient.raw,
                parsed=parsed,
                identity_key=key,
                suppressed=False,
                attempt=attempt,
                verdict=row_verdict,
            )
        )

    deliverable = [r.parsed.mailbox for r in rows if r.parsed.deliverable]
    report = CampaignReport(
        supplied=len(supplied),
        rows=tuple(rows),
        spread=identity_spread(deliverable),
        bounds=failure_bounds(verdicts),
        budget=Budget(deadline_hours=deadline_hours, give_up_hours=give_up_hours),
        rendered_agree=rendered.agree,
        divergent_facts=rendered.divergent_facts,
        normalisation=policy.value,
    )
    return report, rendered
