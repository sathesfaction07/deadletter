"""Deciding whether two address strings are the same person.

The brief asks for "batch deduplication: don't notify the same recipient twice for the same
recall". That requires an identity function on addresses, and there isn't one.

RFC 5321 2.4 is explicit: the local part is case-SENSITIVE and only the domain is
case-insensitive. So `John@x.example` and `john@x.example` are, per the spec, potentially
two different mailboxes. Meanwhile Gmail ignores dots entirely and truncates at `+`, which
no RFC sanctions but which is what actually happens to the mail. Neither behaviour is
discoverable from the address string.

So the number of distinct recipients in a list is a function of POLICY, not of the list. On
the shipped corpus the same addresses resolve to anywhere between one recipient and all of
them, and no observation from the sending side settles it.

Dedup itself is not new here -- five other projects in this portfolio do it. What is new is
that the key is unknowable, and that the two ways of being wrong have wildly different
costs for a safety notice.
"""

from __future__ import annotations

from collections.abc import Iterable

from pydantic import BaseModel, ConfigDict

from .models import Normalisation

#: RFC 5321 2.4, paraphrased. Cited because it contradicts what nearly everyone ships.
RFC5321_CASE_RULE = (
    "The local-part of a mailbox MUST BE treated as case sensitive. Mailbox domains "
    "follow normal DNS rules and are hence not case sensitive. (RFC 5321 2.4)"
)

#: Domains known to fold dots and +tags. This list is the honest weak point of the whole
#: module: it is a hardcoded guess about provider behaviour, it cannot be derived from an
#: address, and it goes stale. `doctor` says so.
FOLDING_DOMAINS: frozenset[str] = frozenset({"gmail.com", "googlemail.com"})


def normalise(address: str, policy: Normalisation) -> str:
    """Reduce an address to whatever the policy considers its identity."""
    local, sep, domain = address.rpartition("@")
    if not sep:
        return address
    if policy is Normalisation.EXACT:
        return address
    if policy is Normalisation.RFC5321:
        return f"{local}@{domain.lower()}"
    if policy is Normalisation.LOWERCASE:
        return address.lower()
    # FOLDED
    local = local.split("+")[0].replace(".", "")
    return f"{local.lower()}@{domain.lower()}"


def normalise_per_domain(address: str) -> str:
    """The policy a careful engineer would write: fold only where folding is known to happen.

    Included because it is the obvious improvement, and because it does not escape the
    problem. It still rests on FOLDING_DOMAINS, which is a guess, and it still cannot tell
    whether a non-folding domain treats the local part case-sensitively -- so it merely
    moves the unknowable part rather than removing it.
    """
    local, sep, domain = address.rpartition("@")
    if not sep:
        return address
    if domain.lower() in FOLDING_DOMAINS:
        return normalise(address, Normalisation.FOLDED)
    return normalise(address, Normalisation.RFC5321)


class IdentitySpread(BaseModel):
    """How many distinct recipients one address list contains, under each policy.

    The spread is the finding. If the policies agreed, the identity function would be
    well-defined and the dedup requirement would be implementable as stated.
    """

    model_config = ConfigDict(frozen=True)

    addresses: int
    counts: dict[str, int]
    per_domain: int

    @property
    def widest(self) -> int:
        return max(self.counts.values())

    @property
    def narrowest(self) -> int:
        return min(self.counts.values())

    @property
    def ambiguous(self) -> bool:
        return self.widest != self.narrowest

    @property
    def possible_duplicates(self) -> int:
        """Notices sent twice to one person, if the truth is the narrowest reading and the
        widest policy is used. An annoyance."""
        return self.widest - self.narrowest

    @property
    def possible_silences(self) -> int:
        """People never told, if the truth is the widest reading and the narrowest policy is
        used. For a safety recall this is the expensive direction, and it is the same number
        -- the costs differ, the arithmetic does not."""
        return self.widest - self.narrowest


def identity_spread(addresses: Iterable[str]) -> IdentitySpread:
    """Count distinct recipients under every policy."""
    items = list(addresses)
    return IdentitySpread(
        addresses=len(items),
        counts={p.value: len({normalise(a, p) for a in items}) for p in Normalisation},
        per_domain=len({normalise_per_domain(a) for a in items}),
    )


class Collision(BaseModel):
    """Two or more addresses that one policy calls the same person and another does not."""

    model_config = ConfigDict(frozen=True)

    key: str
    policy: str
    members: tuple[str, ...]
    #: Policies under which these same addresses stay separate.
    separated_by: tuple[str, ...]

    @property
    def size(self) -> int:
        return len(self.members)


def collisions(addresses: Iterable[str], policy: Normalisation) -> list[Collision]:
    """Groups that `policy` merges, together with the policies that keep them apart.

    A collision is not a bug. It is a decision, made by whoever picked the policy, about
    whether two strings are one customer.
    """
    items = list(addresses)
    groups: dict[str, list[str]] = {}
    for address in items:
        groups.setdefault(normalise(address, policy), []).append(address)

    found = []
    for key, members in sorted(groups.items()):
        if len(members) < 2:
            continue
        separated = tuple(
            other.value
            for other in Normalisation
            if other is not policy and len({normalise(m, other) for m in members}) > 1
        )
        found.append(
            Collision(
                key=key, policy=policy.value, members=tuple(members), separated_by=separated
            )
        )
    return found


def asymmetry_note(spread: IdentitySpread) -> str:
    """The sentence that should decide the policy, spelled out.

    Both errors have the same magnitude. They do not have the same cost, and for a recall
    the cheap error is the one everyone tries to avoid.
    """
    if not spread.ambiguous:
        return (
            f"All {len(spread.counts)} policies agree on {spread.widest} recipients for these "
            f"{spread.addresses} addresses, so nothing is at stake in the choice HERE. That is "
            f"a property of this list, not a general result."
        )
    return (
        f"{spread.addresses} addresses are between {spread.narrowest} and {spread.widest} "
        f"people depending on policy. Merge too eagerly and up to {spread.possible_silences} "
        f"customers are never told their product is dangerous. Merge too little and up to "
        f"{spread.possible_duplicates} get a second copy of a notice they already read. "
        f"Same number, wildly different cost -- so for a SAFETY notice the defensible default "
        f"is the one that duplicates, which is precisely the behaviour the brief asks to "
        f"remove."
    )
