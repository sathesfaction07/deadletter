"""Terminal output. Every table exists to make one claim legible."""

from __future__ import annotations

from rich.console import Console
from rich.table import Table

from .addresses import (
    COMMENT_GRAMMAR,
    accepted_invalid_addresses,
    demonstrate_non_regularity,
    rejected_valid_addresses,
    stdlib_readings,
)
from .campaign import CampaignReport
from .compose import Rendered
from .delivery import AMBIGUITY_FLOOR, collapse_table, consistent_states
from .identity import (
    FOLDING_DOMAINS,
    RFC5321_CASE_RULE,
    Collision,
    IdentitySpread,
    asymmetry_note,
)
from .models import FAILURE_STATES, Signal
from .timing import RFC5321_GIVE_UP, Budget, budget_table, signal_arrival

console = Console()


def _table(*columns: str, title: str | None = None) -> Table:
    table = Table(title=title, title_justify="left", header_style="bold")
    for column in columns:
        table.add_column(column)
    return table


def show_non_regularity(max_depth: int) -> None:
    console.print("[bold]Why no regex validates an email address[/bold]\n")
    console.print("RFC 5322 3.2.2:")
    for line in COMMENT_GRAMMAR.splitlines():
        console.print(f"  [dim]{line}[/dim]")
    console.print(
        "\n`comment` appears inside its own expansion, so comments nest to arbitrary depth.\n"
        "A regex has finitely many states and cannot count unbounded nesting, so the set of\n"
        "RFC 5322 addresses is NOT A REGULAR LANGUAGE. This is a grammar fact, not a\n"
        "judgement about anyone's regex.\n"
    )

    rows = demonstrate_non_regularity(max_depth)
    names = list(rows[0][2])
    table = _table("depth", "a VALID address", *names, title="what each shipped regex says")
    for depth, address, verdicts in rows:
        table.add_row(
            str(depth),
            address,
            *("[green]accept[/green]" if verdicts[n] else "[red]REJECT[/red]" for n in names),
        )
    console.print(table)
    console.print(
        "\nThe two careful regexes reject every depth INCLUDING 1. The sloppy one accepts them\n"
        "all, by not caring about parentheses. So the regex that looks least rigorous is the\n"
        "only one that would deliver this customer's recall notice.\n"
    )

    console.print("[bold]And the error directions do not cost the same[/bold]\n")
    strict = _table("valid address a validator may refuse", "why it is valid")
    for address, why in rejected_valid_addresses():
        strict.add_row(address, why)
    console.print(strict)
    console.print("  [red]Each row is a customer who is never told the product is dangerous.[/red]\n")

    loose = _table("not an address, accepted anyway", "what happens")
    for address, why in accepted_invalid_addresses():
        loose.add_row(address, why)
    console.print(loose)
    console.print("  [dim]Each row costs one bounce.[/dim]\n")

    console.print("[bold]The stdlib disagrees with itself[/bold]\n")
    dis = _table("input", "parseaddr", "getaddresses")
    for raw in (
        "user@example.com",
        "not-an-address",
        "user@[192.168.1.1]",
        "Doe, John <john@example.com>",
        "user(a(b)c)@example.com",
    ):
        single, many = stdlib_readings(raw)
        dis.add_row(raw, repr(single), repr(many))
    console.print(dis)
    console.print(
        "\n  `not-an-address` comes back as a mailbox -- no @ anywhere, and no error either.\n"
        "  `user@[192.168.1.1]` is refused, and RFC 5321 4.1.3 explicitly permits it.\n"
        "  `Doe, John <...>` becomes TWO recipients, one of them a surname -- while parseaddr\n"
        "  returns nothing for the same string. One INVENTS a recipient, the other DROPS it.\n"
    )


def show_identity(spread: IdentitySpread, collisions: list[Collision], policy: str) -> None:
    console.print("[bold]How many people is this list?[/bold]\n")
    console.print(f"  [dim]{RFC5321_CASE_RULE}[/dim]\n")

    table = _table("policy", "distinct recipients", "what it assumes")
    notes = {
        "exact": "two strings are one person only if byte-identical",
        "rfc5321": "the spec: domain case-insensitive, LOCAL PART CASE-SENSITIVE",
        "lowercase": "what almost everybody ships, and not what the spec says",
        "folded": "what Gmail does: dots ignored, +tag truncated. No RFC backing",
    }
    for name, count in spread.counts.items():
        table.add_row(name, str(count), notes.get(name, ""))
    table.add_row(
        "[cyan]per-domain[/cyan]",
        f"[cyan]{spread.per_domain}[/cyan]",
        f"fold only for {sorted(FOLDING_DOMAINS)} -- a hardcoded guess that goes stale",
    )
    console.print(table)
    console.print(f"\n  {asymmetry_note(spread)}\n")

    if collisions:
        merged = _table("key", "addresses merged", "kept apart by")
        for collision in collisions[:8]:
            merged.add_row(
                collision.key,
                "\n".join(collision.members),
                ", ".join(collision.separated_by) or "[dim]nothing[/dim]",
            )
        console.print(merged)
        console.print(
            f"\n  Under [bold]{policy}[/bold] these are one customer each. Under the policies in\n"
            "  the last column they are several. Nothing observable settles it.\n"
        )


def show_states() -> None:
    console.print("[bold]What a signal tells you about what happened[/bold]\n")

    forward = _table("signal", "outcomes that produce it", "of those, failures", "which")
    for name, count, failures, which in collapse_table():
        highlight = "[red]" if count > 1 else ""
        close = "[/red]" if count > 1 else ""
        forward.add_row(f"{highlight}{name}{close}", str(count), str(failures), which)
    console.print(forward)
    console.print(
        "\n  `rejected` and `bounced` carry the same outcome. The only difference is WHEN it\n"
        "  was found out, which is why timing needs its own axis.\n"
        f"  `nothing` carries {AMBIGUITY_FLOOR}, and two of those {AMBIGUITY_FLOOR} mean the "
        "customer was never informed.\n"
    )

    console.print("[bold]Does waiting help?[/bold]\n")
    waiting = _table("signal", "window open", "window closed", "settled?")
    for signal in Signal:
        open_states = consistent_states(signal, False)
        shut_states = consistent_states(signal, True)
        settled = len(shut_states) == 1
        waiting.add_row(
            signal.value,
            f"{len(open_states)} candidate(s)",
            f"{len(shut_states)} candidate(s)",
            "[green]yes[/green]" if settled else "[red]NO[/red]",
        )
    console.print(waiting)
    console.print(
        f"\n  Closing the window removes exactly one candidate -- IN_FLIGHT -- taking silence\n"
        f"  from {AMBIGUITY_FLOOR + 1} to {AMBIGUITY_FLOOR}. Never to one. So no report run "
        "later narrows it.\n"
        "\n  [bold]The inversion:[/bold] the only signals that settle anything are the negative\n"
        "  ones. You can learn that you failed. You cannot learn that you succeeded.\n"
    )


def show_timing(budget: Budget) -> None:
    console.print("[bold]When the answer arrives, against when it was needed[/bold]\n")
    console.print(f"  [dim]{RFC5321_GIVE_UP}[/dim]\n")

    arrival = _table("signal", "decidability", "why")
    for signal in Signal:
        how, why = signal_arrival(signal, budget.give_up_hours)
        arrival.add_row(signal.value, how.value, why)
    console.print(arrival)

    console.print(f"\n  {budget.summary()}\n")

    spread = _table("deadline", "retry window / deadline", "actionable signal classes", "in trouble?")
    for deadline, ratio, actionable, inside in budget_table(give_up_hours=budget.give_up_hours):
        spread.add_row(
            f"{deadline:g}h",
            f"{ratio:.1f}x",
            f"{actionable} of 4",
            "[red]yes[/red]" if inside else "[green]no[/green]",
        )
    console.print(spread)
    console.print(
        "\n  A recall deadline is set in hours. The spec's retry window is set in days. So the\n"
        "  mechanism recommended for delivery confidence reports after the deadline it is\n"
        "  meant to protect -- which makes it a post-mortem tool, not a recall tool.\n"
    )


def show_compose(rendered: Rendered) -> None:
    console.print("[bold]A multipart/alternative message is two documents[/bold]\n")
    table = _table("part", "facts missing")
    table.add_row("text/html", ", ".join(rendered.missing_from_html) or "[green]none[/green]")
    table.add_row("text/plain", ", ".join(rendered.missing_from_text) or "[green]none[/green]")
    console.print(table)
    console.print(f"\n  {rendered.summary()}\n")


def show_report(report: CampaignReport) -> None:
    console.print("[bold]What this campaign can honestly claim[/bold]\n")

    counts = _table("", "count")
    counts.add_row("addresses supplied", str(report.supplied))
    counts.add_row("delivery attempted", str(report.attempted))
    counts.add_row("suppressed as duplicates", str(len(report.suppressed)))
    counts.add_row("[red]no mailbox found[/red]", f"[red]{len(report.undeliverable)}[/red]")
    counts.add_row("[red]recipients invented[/red]", f"[red]{len(report.invented)}[/red]")
    counts.add_row("parsers disagreed", str(len(report.disagreements)))
    console.print(counts)

    console.print("\n[bold]Were they informed?[/bold]\n")
    bounds = _table("", "recipients", "note")
    bounds.add_row(
        "confirmed NOT informed",
        str(report.bounds.floor),
        "a signal said so. This is a FLOOR, not a total",
    )
    bounds.add_row(
        "[red]never decidable[/red]",
        f"[red]{report.bounds.silent}[/red]",
        "accepted, then silence. No signal is ever coming",
    )
    bounds.add_row(
        "decidable, but late",
        str(report.bounds.pending),
        "a signal is coming, after the deadline",
    )
    bounds.add_row(
        "most that could have been informed",
        str(report.informed_ceiling),
        "a CEILING. Not a count of people reached",
    )
    console.print(bounds)
    console.print(f"\n  {report.bounds.summary()}\n")

    known = sum(1 for r in report.rows if r.verdict and r.verdict.known_by_deadline)
    console.print(
        f"  [bold]{known} of {report.attempted}[/bold] outcomes were knowable by the "
        f"{report.budget.deadline_hours:g}h deadline.\n"
    )

    interesting = [
        r
        for r in report.rows
        if r.parsed.fidelity.value in {"dropped", "invented", "normalised"} or r.suppressed
    ]
    if interesting:
        console.print("[bold]Rows worth a human's attention[/bold]\n")
        rows = _table("supplied", "delivered to", "what happened")
        for row in interesting:
            rows.add_row(
                row.raw,
                row.parsed.mailbox or "[red]nothing[/red]",
                "suppressed as a duplicate" if row.suppressed else row.parsed.detail[:96],
            )
        console.print(rows)


def show_check(report: CampaignReport, failures: list[str], reported: list[str]) -> None:
    console.print("[bold]check[/bold]\n")
    if failures:
        console.print("[red]Fixable at source, so this fails:[/red]")
        for line in failures:
            console.print(f"  [red]x[/red] {line}")
    else:
        console.print("[green]Nothing fixable at source.[/green]")

    console.print("\n[dim]Reported and NOT failed on -- these are properties of email, not[/dim]")
    console.print("[dim]defects anyone can fix, and a gate that fires on them gets[/dim]")
    console.print("[dim]switched off inside a week:[/dim]")
    for line in reported:
        console.print(f"  [yellow]-[/yellow] {line}")
    console.print()
    console.print("[green]PASS[/green]" if not failures else "[red]FAIL[/red]")


def show_explain(report: CampaignReport, raw: str) -> None:
    row = next((r for r in report.rows if r.raw == raw), None)
    if row is None:
        console.print(f"[red]no row supplied as {raw!r}[/red]")
        return

    console.print(f"[bold]{raw}[/bold]\n")
    table = _table("", "")
    table.add_row("parsed as", row.parsed.mailbox or "[red]nothing[/red]")
    table.add_row("fidelity", row.parsed.fidelity.value)
    table.add_row("parsers agreed", "no" if row.parsed.disagreement else "yes")
    if row.identity_key:
        table.add_row("identity key", row.identity_key)
    table.add_row("suppressed", "yes" if row.suppressed else "no")
    if row.attempt:
        table.add_row("signal", row.attempt.signal.value)
        table.add_row("smtp", str(row.attempt.smtp_code or "-"))
        table.add_row("arrived at", f"{row.attempt.elapsed_hours:g}h")
    console.print(table)
    # Printed as prose rather than as a table cell, because Rich folds an over-long cell
    # mid-word and turns a sentence into something the reader has to reassemble.
    console.print(f"\n  {row.parsed.detail}")

    if row.verdict:
        console.print("\n[bold]What is known about this recipient[/bold]\n")
        states = _table("outcome still possible", "would that mean failure?")
        for state in row.verdict.consistent_states:
            states.add_row(
                state.value,
                "[red]yes[/red]" if state in FAILURE_STATES else "[green]no[/green]",
            )
        console.print(states)
        console.print(f"\n  {row.verdict.detail}")
        console.print(
            f"  known by deadline: "
            f"{'[green]yes[/green]' if row.verdict.known_by_deadline else '[red]no[/red]'}\n"
        )
