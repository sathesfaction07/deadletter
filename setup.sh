#!/usr/bin/env bash
# Re-derives every finding in the README from scratch. No network, no credentials.
set -euo pipefail

cd "$(dirname "$0")"

echo "==> environment"
python3 -m venv .venv 2>/dev/null || true
.venv/bin/pip install -q -e ".[dev]"
echo "    python $(.venv/bin/python -V 2>&1 | cut -d' ' -f2), no network needed from here on"

echo
echo "==> corpus"
.venv/bin/python data/generate.py

echo
echo "==> FINDING 1: no regex validates an email address (RFC 5322 3.2.2)"
.venv/bin/python - <<'PY'
from recall_notifier.addresses import COMMENT_GRAMMAR, demonstrate_non_regularity, strip_comments

for line in COMMENT_GRAMMAR.splitlines():
    print(f"    {line}")
print()
print("    `comment` appears in its own expansion, so nesting is unbounded. A regex has")
print("    finitely many states and cannot count it. NOT REGULAR -- by construction.")
print()
rows = demonstrate_non_regularity(4)
names = list(rows[0][2])
print(f"    {'depth':<6}{'a VALID address':<32}" + "".join(f"{n[:22]:<24}" for n in names))
for depth, address, verdicts in rows:
    cells = "".join(f"{('accept' if verdicts[n] else 'REJECT'):<24}" for n in names)
    print(f"    {depth:<6}{address:<32}{cells}")
print()
print("    The two careful regexes REJECT every depth. The sloppy one accepts them all, by")
print("    not caring about parens -- so the least rigorous regex is the only one that")
print("    delivers this customer's recall notice.")
print()
print("    A counter-based scan handles what a regex cannot:")
for local in ("user(x)", "user((a))", "a(1)b(2)c", '"u(x)"'):
    text, depth = strip_comments(local)
    print(f"      {local:<14} -> text={text!r:<24} max_depth={depth}")
PY

echo
echo "==> FINDING 2: the stdlib disagrees with itself, in both directions"
.venv/bin/python - <<'PY'
from recall_notifier.addresses import stdlib_readings

print(f"    {'input':<32}{'parseaddr':<28}getaddresses")
for raw in (
    "user@example.com",
    "not-an-address",
    "user@[192.168.1.1]",
    "Doe, John <john@example.com>",
    "user(a(b)c)@example.com",
):
    single, many = stdlib_readings(raw)
    print(f"    {raw:<32}{single!r:<28}{many!r}")
print()
print("    `not-an-address` comes back AS A MAILBOX -- no @, and no error either.")
print("    `user@[192.168.1.1]` is refused, and RFC 5321 4.1.3 explicitly permits it.")
print("    `Doe, John <...>` becomes TWO recipients, one being a SURNAME, while parseaddr")
print("    returns nothing at all. One INVENTS a recipient; the other DROPS it.")
PY

echo
echo "==> FINDING 3: a recipient count is a function of POLICY, not of the list"
.venv/bin/python - <<'PY'
from recall_notifier.identity import RFC5321_CASE_RULE, asymmetry_note, identity_spread

print(f"    {RFC5321_CASE_RULE}")
print()
addresses = [
    "John.Doe@Example.COM",
    "john.doe@example.com",
    "j.o.h.n.d.o.e@example.com",
    "johndoe+recall@example.com",
    "JOHNDOE@EXAMPLE.COM",
]
spread = identity_spread(addresses)
for policy, count in spread.counts.items():
    print(f"      {policy:<12} -> {count} recipients from {spread.addresses} addresses")
print()
print(f"    {asymmetry_note(spread)}")
PY

echo
echo "==> FINDING 4 (the headline): four outcomes emit nothing, and waiting does not help"
.venv/bin/python - <<'PY'
from recall_notifier.delivery import AMBIGUITY_FLOOR, collapse_table, consistent_states
from recall_notifier.models import FAILURE_STATES, Signal

print(f"    {'signal':<11}{'outcomes':<11}{'failures':<11}which")
for name, count, failures, which in collapse_table():
    flag = "   <- THE COLLAPSE" if count > 1 else ""
    print(f"    {name:<11}{count:<11}{failures:<11}{which}{flag}")
print()
print(f"    {'signal':<11}{'window open':<16}{'window closed':<16}settled?")
for signal in Signal:
    a, b = consistent_states(signal, False), consistent_states(signal, True)
    print(f"    {signal.value:<11}{len(a):<16}{len(b):<16}{'yes' if len(b) == 1 else 'NO'}")
print()
print(f"    Closing the retry window removes EXACTLY ONE candidate -- IN_FLIGHT -- taking")
print(f"    silence from {AMBIGUITY_FLOOR + 1} to {AMBIGUITY_FLOOR}. Never to one.")
print()
decisive = {s.value for s in Signal if len(consistent_states(s, True)) == 1}
print(f"    Signals that ever settle an outcome: {sorted(decisive)}")
print(f"    ...and both of them mean the message was NOT accepted. You can learn that you")
print(f"    failed. You cannot learn that you succeeded.")
assert all(
    consistent_states(Signal(s), True)[0] in FAILURE_STATES for s in decisive
)
PY

echo
echo "==> FINDING 5: the answer arrives after the deadline (RFC 5321 4.5.4.1)"
.venv/bin/python - <<'PY'
from recall_notifier.timing import RFC5321_GIVE_UP, Budget, budget_table

print(f"    {RFC5321_GIVE_UP}")
print()
print(f"    {'deadline':<12}{'window/deadline':<18}{'actionable classes':<22}deadline inside window?")
for deadline, ratio, actionable, inside in budget_table():
    print(f"    {deadline:<12g}{ratio:<18.1f}{f'{actionable} of 4':<22}{'YES' if inside else 'no'}")
print()
print(f"    {Budget(deadline_hours=24.0, give_up_hours=96.0).summary()}")
PY

echo
echo "==> FINDING 6: a multipart/alternative message is TWO documents"
.venv/bin/python - <<'PY'
from recall_notifier.cli import NOTICE
from recall_notifier.compose import render

for label, flag in (("two templates", False), ("text stripped from the HTML", True)):
    r = render(NOTICE, text_from_html=flag)
    print(f"    {label:<30} agree={r.agree}  missing from text: {r.missing_from_text or 'none'}")
print()
r = render(NOTICE, text_from_html=True)
print("    The shortcut produced:")
print(f"      ...{r.text[90:200]}...")
print()
print("    The header cells and the data cells are now adjacent to each OTHER, so LOT-4471")
print("    sits next to nothing that says it is a lot number. The VALUE survives; the fact")
print("    does not -- which is why a value-presence check passes and says nothing.")
PY

echo
echo "==> the campaign, and what it can honestly claim"
.venv/bin/recall-notifier report 2>&1 | sed -n "9,34p" || true

echo
echo "==> check: fails only on what someone can fix"
.venv/bin/recall-notifier check 2>&1 | tail -14 || true

echo
echo "==> tests"
.venv/bin/python -m pytest -q --cov=recall_notifier --cov-report=term 2>&1 | tail -4
rm -f .coverage

echo
echo "Done. Nothing above needed a network, a credential or an SMTP server."
echo "Try: .venv/bin/recall-notifier states"
