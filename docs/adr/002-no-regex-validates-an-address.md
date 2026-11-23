# ADR 002: No regex validates an email address, and the error direction decides the cost

**Status:** accepted
**Date:** 2026-09-17

## Context

Every recipient list contains strings that are not obviously addresses. Something has to
decide which are deliverable. The default reflex is a regex, and the second reflex is
`email.utils.parseaddr`. Both are wrong, in ways that are worth being precise about.

## The grammar problem

RFC 5322 3.2.2:

```
comment  = "(" *([FWS] ccontent) [FWS] ")"
ccontent = ctext / quoted-pair / comment      <-- comment contains itself
```

`comment` appears inside its own expansion, so comments nest to arbitrary depth. A regular
expression has finitely many states and cannot count unbounded nesting. **The set of
RFC 5322 addresses is not a regular language, so no regex recognises it.** That is a
statement about the grammar, not a judgement about anyone's pattern.

Comments are semantically transparent: `user(x)@example.com` addresses the same mailbox as
`user@example.com`. So every nesting depth is a legitimate way to write a real address.

### The inversion

```
depth   a VALID address              the one everyone writes   the careful one   the "RFC-compliant" one
1       user(x)@example.com          accept                    REJECT            REJECT
2       user((x))@example.com        accept                    REJECT            REJECT
3       user(((x)))@example.com      accept                    REJECT            REJECT
4       user((((x))))@example.com    accept                    REJECT            REJECT
```

Not a threshold effect. The two careful regexes reject **every** depth including 1; the
sloppy one accepts them all by not caring about parentheses. **The regex that looks least
rigorous is the only one that would deliver this customer's recall notice.**

### And the costs are not symmetric

| Direction | Cost |
|:--|:--|
| accept an invalid address | one bounce |
| **reject a valid address** | **a customer is never told the product is dangerous** |

For a safety notice those are not comparable, and the careful-looking validator errs in the
expensive direction.

## The stdlib problem

`parseaddr` and `getaddresses` are documented as doing the same job. They do not:

```
input                           parseaddr                   getaddresses
user@example.com                'user@example.com'          ['user@example.com']
not-an-address                  'not-an-address'            ['not-an-address']
user@[192.168.1.1]              ''                          []
Doe, John <john@example.com>    ''                          ['Doe', 'john@example.com']
user(a(b)c)@example.com         'user@example.com'          ['user@example.com']
```

Three separate problems:

**`not-an-address` comes back as a mailbox.** No `@` anywhere, and no error either. A
validator that trusts the return value will attempt delivery to a surname.

**`user@[192.168.1.1]` is refused**, and RFC 5321 4.1.3 explicitly permits an address
literal. That recipient is silently lost.

**`Doe, John <john@example.com>` becomes two recipients**, the first being `Doe` — a fragment
of a person's name — while `parseaddr` on the same string returns nothing at all. So on one
input **one of them invents a recipient and the other drops it.** Neither is wrong about the
RFC; a bare comma genuinely is an address-list separator. But a CSV row is not an RFC 5322
header, and treating it as one is how a surname becomes a delivery attempt.

**And `parseaddr` strips comments before returning.** `us(er)@ex.com` comes back as
`us@ex.com`. Correct, and it means the mailbox delivered to is not the string supplied, with
nothing saying so.

## Decision

`Fidelity` has four values, not a `valid: bool`:

| Value | Meaning |
|:--|:--|
| `CLEAN` | a mailbox, returned unchanged |
| `NORMALISED` | a mailbox, but the parser rewrote it |
| `DROPPED` | no mailbox found — a recipient LOST |
| `INVENTED` | more recipients produced than the string named |

`INVENTED` and `DROPPED` fail in opposite directions, and a boolean collapses them. (Same
distinction as DocConsolidator's `Fidelity`, reused for the same reason.)

Comment depth is scanned on the **raw** string with a counter-based walk, not with a regex —
because a regex provably cannot — and not on `parseaddr`'s output, because that has already
had comments removed.

The two ways of being `DROPPED` get **different** explanations, because they are different
failures: one string came back and would be delivered to, the other came back empty and is
simply gone.

`check` fails on `DROPPED` and `INVENTED`. Both are fixable by cleaning the list. It does
**not** fail on `NORMALISED`, because a comment in an address is legal and the delivery is
correct.

## Consequences

**Good.** A row that silently became two recipients is now a build failure. The
`rejected_valid_addresses()` list makes the asymmetric cost visible in one place.

**Bad.** Four `Fidelity` values is more than most callers want, and `deliverable` exists
because most of them only need the boolean.

**Honest.** The claims about `parseaddr` and `getaddresses` rest on **implementation
behaviour**, not on a spec. A CPython change could invalidate them. `doctor` lists them
separately from the RFC-grounded claims for exactly that reason.

## What was rejected

**A better regex.** There isn't one. The language is not regular.

**`email-validator` / Pydantic's `EmailStr`.** They would move the decision into a dependency
whose error direction I would then have to characterise anyway — and characterising it is the
finding.

**Normalising the list on the way in.** The point is to report what a real recipient list
contains. Quietly fixing it would hide the input.
