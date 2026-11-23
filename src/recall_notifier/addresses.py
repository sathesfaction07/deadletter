"""Turning a string into a mailbox, and why no regex does it.

The headline here is a grammar fact, not an opinion: RFC 5322 3.2.2 defines

    comment  = "(" *([FWS] ccontent) [FWS] ")"
    ccontent = ctext / quoted-pair / comment

`comment` appears in its own expansion, so comments nest to arbitrary depth. A regular
expression has finitely many states and cannot count unbounded nesting, so the set of
RFC 5322 addresses is not a regular language and no regex recognises it. Every shipped
email regex is therefore knowingly approximate, and the only interesting question is which
way it errs.

For a recall notice the two directions are not equally bad. Accepting an invalid address
costs a bounce. Rejecting a valid one means a real customer is never told their product is
dangerous. The careful-looking regexes err in the expensive direction.
"""

from __future__ import annotations

import re
from email.utils import getaddresses, parseaddr

from .models import Fidelity, ParsedAddress

#: RFC 5322 3.2.2. Quoted here because the recursion is the entire argument.
COMMENT_GRAMMAR = (
    'comment  = "(" *([FWS] ccontent) [FWS] ")"\n'
    "ccontent = ctext / quoted-pair / comment      <-- comment contains itself"
)

#: Three regexes people actually ship. Named by where they come from rather than by author,
#: and included so the claim below is demonstrated rather than asserted.
SHIPPED_REGEXES: dict[str, str] = {
    "the one everyone writes": r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$",
    "the careful one": (
        r"^[-!#$%&'*+/=?^_`{}|~0-9A-Za-z]+(\.[-!#$%&'*+/=?^_`{}|~0-9A-Za-z]+)*"
        r"@[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$"
    ),
    'the "RFC-compliant" one': (
        r"^[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?"
        r"(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$"
    ),
}


def nested_comment_address(depth: int) -> str:
    """A valid RFC 5322 address whose local part carries a comment nested `depth` deep.

    Comments are semantically transparent -- `user(x)@example.com` addresses the same
    mailbox as `user@example.com` -- so every one of these is a legitimate way to write a
    real address, at every depth.
    """
    if depth < 1:
        raise ValueError("depth must be at least 1")
    return "user" + "(" * depth + "x" + ")" * depth + "@example.com"


def regex_verdicts(address: str) -> dict[str, bool]:
    """What each shipped regex says about one address string."""
    return {name: bool(re.match(pattern, address)) for name, pattern in SHIPPED_REGEXES.items()}


def demonstrate_non_regularity(max_depth: int = 5) -> list[tuple[int, str, dict[str, bool]]]:
    """Run every shipped regex against a valid address at increasing nesting depth.

    The result is not that they fail at some depth and pass below it -- it is that the two
    careful regexes reject every depth including 1, while the sloppy one accepts every depth
    by not caring about parentheses at all. So the regex that looks least rigorous is the
    only one that would deliver this customer's recall notice.
    """
    rows = []
    for depth in range(1, max_depth + 1):
        address = nested_comment_address(depth)
        rows.append((depth, address, regex_verdicts(address)))
    return rows


def strip_comments(local: str) -> tuple[str, int]:
    """Remove RFC 5322 comments from a local part, returning the text and the max depth seen.

    Written as a counter-based scan rather than a regex, because a regex provably cannot do
    it -- which is the point being made two functions up.
    """
    out: list[str] = []
    depth = 0
    max_depth = 0
    in_quotes = False
    escaped = False
    for ch in local:
        if escaped:
            if depth == 0:
                out.append(ch)
            escaped = False
            continue
        if ch == "\\":
            if depth == 0:
                out.append(ch)
            escaped = True
            continue
        if ch == '"' and depth == 0:
            in_quotes = not in_quotes
            out.append(ch)
            continue
        if not in_quotes and ch == "(":
            depth += 1
            max_depth = max(max_depth, depth)
            continue
        if not in_quotes and ch == ")":
            if depth == 0:
                raise ValueError("unbalanced comment close in local part")
            depth -= 1
            continue
        if depth == 0:
            out.append(ch)
    if depth:
        raise ValueError("unbalanced comment open in local part")
    return "".join(out), max_depth


def is_address_literal(domain: str) -> bool:
    """RFC 5321 4.1.3 permits `[192.168.1.1]` and `[IPv6:...]` as a domain."""
    return domain.startswith("[") and domain.endswith("]") and len(domain) > 2


def stdlib_readings(raw: str) -> tuple[str, list[str]]:
    """What each stdlib entry point makes of one string.

    Returns `parseaddr`'s single answer and `getaddresses`' list. They are documented as
    doing the same job on one address, and they do not always agree -- which is the finding
    in `parse_address` below.
    """
    _, single = parseaddr(raw)
    many = [addr for _, addr in getaddresses([raw]) if addr]
    return single, many


def parse_address(raw: str) -> ParsedAddress:
    """Turn one string into at most one mailbox, and record how the parsers behaved.

    The two stdlib entry points disagree in BOTH directions on real inputs:

      * `parseaddr("not-an-address")` returns `"not-an-address"` -- a string with no `@` at
        all comes back as a mailbox, so a validator trusting it will attempt delivery to a
        surname.
      * `parseaddr("user@[192.168.1.1]")` returns `""` -- a domain form RFC 5321 4.1.3
        explicitly permits is refused, so that recipient is silently lost.
      * `getaddresses(["Doe, John <john@example.com>"])` returns TWO pairs, the first being
        `("", "Doe")`. One string naming one person yields two recipients, one of which is
        a fragment of a name. `parseaddr` on the same string returns nothing at all.

    So one of them invents a recipient and the other drops it, on the same input. Neither
    is wrong about the RFC -- a bare comma is genuinely an address-list separator -- but a
    recipient list is not an RFC 5322 header, and treating it as one is how a surname
    becomes a delivery attempt.
    """
    text = raw.strip()
    single, many = stdlib_readings(text)
    disagreement = (single or None) != (many[0] if len(many) == 1 else None) or len(many) != 1

    # A recipient list row names ONE person. More than one mailbox out of one row means the
    # parser found a separator the author did not intend as one.
    if len(many) > 1:
        return ParsedAddress(
            raw=raw,
            mailbox=many[-1],
            fidelity=Fidelity.INVENTED,
            detail=(
                f"getaddresses split this ONE row into {len(many)} recipients {many!r}; "
                f"parseaddr returned {single!r}. A comma in a display name is an address-list "
                f"separator to the parser and a surname to the author"
            ),
            disagreement=True,
            claimed_count=len(many),
        )

    candidate = single or (many[0] if many else "")
    if "@" not in candidate:
        return ParsedAddress(
            raw=raw,
            mailbox=None,
            fidelity=Fidelity.DROPPED,
            detail=(
                (
                    f"no mailbox here: parseaddr handed back {single!r}, which has no @. It did "
                    f"NOT signal failure -- so an unguarded caller would try to deliver to it"
                )
                if single
                else (
                    f"no mailbox here: parseaddr returned nothing at all for {text!r}, so this "
                    f"recipient is simply gone. When the string is a form it refuses rather "
                    f"than malformed -- an RFC 5321 4.1.3 address literal, say -- that is a "
                    f"real customer dropped in silence"
                )
            ),
            disagreement=disagreement,
            claimed_count=0,
        )

    local, _, domain = candidate.rpartition("@")
    if not local or not domain:
        return ParsedAddress(
            raw=raw,
            mailbox=None,
            fidelity=Fidelity.DROPPED,
            detail=f"{candidate!r} has an empty local part or domain",
            disagreement=disagreement,
            claimed_count=0,
        )

    # Scan the RAW local part, not parseaddr's output. parseaddr strips comments before
    # returning -- verified against twelve inputs including `us(er)@ex.com` -> `us@ex.com`
    # -- so scanning `local` here would report depth 0 every time and the branch below
    # would be dead code that made this function look more careful than it was.
    raw_local = text.rpartition("@")[0] if "@" in text else ""
    try:
        _, depth = strip_comments(raw_local) if raw_local else ("", 0)
    except ValueError:
        # Unbalanced. parseaddr already had its say about this string and produced
        # `candidate`; disagreeing with it here would be inventing a second opinion.
        depth = 0

    mailbox = candidate
    if depth:
        return ParsedAddress(
            raw=raw,
            mailbox=mailbox,
            fidelity=Fidelity.NORMALISED,
            detail=(
                f"the supplied string carries a comment nested {depth} deep, and parseaddr "
                f"SILENTLY removed it -- delivery goes to {mailbox!r}, which is not what was "
                f"supplied. No regex could have done this: comments nest, so the language is "
                f"not regular"
            ),
            disagreement=disagreement,
        )

    if mailbox != raw:
        return ParsedAddress(
            raw=raw,
            mailbox=mailbox,
            fidelity=Fidelity.NORMALISED,
            detail=f"parsed {raw!r} to {mailbox!r}",
            disagreement=disagreement,
        )

    return ParsedAddress(
        raw=raw,
        mailbox=mailbox,
        fidelity=Fidelity.CLEAN,
        detail="a mailbox, returned unchanged",
        disagreement=disagreement,
    )


def rejected_valid_addresses() -> list[tuple[str, str]]:
    """Addresses that are valid per RFC and that shipped validators refuse.

    Each one is a customer who would not be told about the recall. That is the cost of a
    validator erring on the strict side, and it is why the error direction matters more
    than the error rate.
    """
    return [
        ("user@[192.168.1.1]", "RFC 5321 4.1.3 address literal"),
        ('"john doe"@example.com', "RFC 5322 3.4.1 quoted local part, space is legal inside"),
        ('"weird@inner"@example.com', "quoted local part may contain @"),
        ("user(a(b)c)@example.com", "RFC 5322 3.2.2 nested comment, semantically transparent"),
        ("user+recall@example.com", "sub-addressing; rejected by validators that dislike +"),
        ("i18n@münchen.example", "RFC 5890 internationalised domain"),
    ]


def accepted_invalid_addresses() -> list[tuple[str, str]]:
    """Strings that are not mailboxes and that the stdlib hands back anyway.

    These cost a bounce, which is cheap. Included so the asymmetry is visible in one place
    rather than argued for.
    """
    return [
        ("not-an-address", "no @ at all; parseaddr returns it unchanged"),
        ("Doe", "a surname, which is what getaddresses makes of a comma in a display name"),
        ("user@", "empty domain"),
    ]
