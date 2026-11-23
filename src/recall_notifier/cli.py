"""The command line. Every command prints its reasoning, not just its result."""

from __future__ import annotations

import json
from pathlib import Path

import click

from . import render
from .addresses import SHIPPED_REGEXES
from .campaign import CampaignReport, load_recipients, run_campaign
from .compose import Notice
from .config import Settings
from .delivery import AMBIGUITY_FLOOR
from .identity import FOLDING_DOMAINS, collisions, identity_spread
from .models import Fidelity, Normalisation
from .timing import Budget

#: The example recall. Real enough to have facts worth losing, invented entirely.
NOTICE = Notice(
    product="Toddler Sleep Sack, model TS-200",
    hazard="The zipper pull can detach and become a choking hazard for children under three.",
    lot="LOT-4471",
    sold_between="March 2025 and August 2026",
    remedy="Stop using it immediately and return it to any store for a full refund.",
    reference="RC-2026-0918",
)


def _load(settings: Settings) -> tuple[CampaignReport, object]:
    recipients = load_recipients(settings.recipients)
    return run_campaign(
        recipients,
        NOTICE,
        deadline_hours=settings.deadline_hours,
        give_up_hours=settings.give_up_hours,
        policy=settings.normalisation,
        text_from_html=settings.text_from_html,
    )


@click.group()
def cli() -> None:
    """Send recall notices, then report what a delivery report cannot tell you."""


@cli.command()
def doctor() -> None:
    """Configuration, and which claims here rest on something weaker than a spec."""
    settings = Settings()
    render.console.print("[bold]configuration[/bold]")
    for key, value in settings.model_dump().items():
        render.console.print(f"  RN_{key.upper():16} {value}")

    exists = settings.recipients.exists()
    render.console.print(
        f"\n  recipient list     {'[green]found[/green]' if exists else '[red]missing[/red]'}"
        f" at {settings.recipients}"
    )
    render.console.print("  network            [green]none used, ever[/green]")
    render.console.print("  SMTP client        [yellow]none -- outcomes come from a fixture[/yellow]")

    render.console.print("\n[bold]claims grounded in a specification[/bold]")
    render.console.print("  - comments nest, so the address set is not regular   (RFC 5322 3.2.2)")
    render.console.print("  - the local part is case-SENSITIVE                   (RFC 5321 2.4)")
    render.console.print("  - give-up time is at least 4-5 days                  (RFC 5321 4.5.4.1)")
    render.console.print("  - an address literal is a legal domain               (RFC 5321 4.1.3)")

    render.console.print("\n[bold]claims resting on IMPLEMENTATION behaviour[/bold]")
    render.console.print("  [dim]verified here, but a library change could invalidate them[/dim]")
    render.console.print("  - parseaddr returns a string with no @ unchanged")
    render.console.print("  - parseaddr refuses an address literal")
    render.console.print("  - getaddresses splits a display-name comma into two recipients")
    render.console.print("  - parseaddr strips comments before returning")

    render.console.print("\n[bold]claims that are GUESSES, and go stale[/bold]")
    render.console.print(
        f"  [yellow]- which domains fold dots and +tags: {sorted(FOLDING_DOMAINS)};"
        " hardcoded, not discoverable from an address, and provider-specific[/yellow]"
    )
    render.console.print(
        "  [yellow]- the delivery outcome mix in the fixture is invented, not measured[/yellow]"
    )
    render.console.print(
        "  [yellow]- whether IN_SPAM counts as a failure is a judgement, not a fact[/yellow]"
    )
    render.console.print(f"\n  {len(SHIPPED_REGEXES)} shipped regexes are compared, by provenance.")


@cli.command()
@click.option("--max-depth", default=3, show_default=True, help="Nesting depth to demonstrate.")
def addresses(max_depth: int) -> None:
    """Why no regex validates an address, and how the stdlib disagrees with itself."""
    render.show_non_regularity(max_depth)


@cli.command()
def identity() -> None:
    """How many people a recipient list contains, under each policy."""
    settings = Settings()
    report, _ = _load(settings)
    mailboxes = [r.parsed.mailbox for r in report.rows if r.parsed.deliverable]
    render.show_identity(
        identity_spread(mailboxes),
        collisions(mailboxes, settings.normalisation),
        settings.normalisation.value,
    )


@cli.command()
@click.option("--policy", type=click.Choice([p.value for p in Normalisation]), default=None)
def merges(policy: str | None) -> None:
    """Which addresses one policy calls the same person, and which policies disagree."""
    settings = Settings()
    chosen = Normalisation(policy) if policy else settings.normalisation
    report, _ = _load(settings)
    mailboxes = [r.parsed.mailbox for r in report.rows if r.parsed.deliverable]
    render.show_identity(identity_spread(mailboxes), collisions(mailboxes, chosen), chosen.value)


@cli.command()
def states() -> None:
    """What a signal tells you about what happened, and what it cannot."""
    render.show_states()


@cli.command()
def timing() -> None:
    """When the answer arrives, against when the recall needed it."""
    settings = Settings()
    render.show_timing(
        Budget(deadline_hours=settings.deadline_hours, give_up_hours=settings.give_up_hours)
    )


@cli.command()
@click.option(
    "--text-from-html",
    is_flag=True,
    help="Generate the text part by stripping tags, and see what that costs.",
)
def compose(text_from_html: bool) -> None:
    """Render the notice and check that its two parts say the same thing."""
    from .compose import render as render_notice

    rendered = render_notice(NOTICE, text_from_html=text_from_html)
    render.show_compose(rendered)
    if text_from_html:
        render.console.print("[dim]the text part this produced:[/dim]")
        render.console.print(f"  {rendered.text[:220]}\n")


@cli.command()
@click.option("-o", "--out", type=click.Path(path_type=Path), default=None, help="Write JSON here.")
def report(out: Path | None) -> None:
    """Run the campaign and report only what is supportable."""
    settings = Settings()
    campaign, _ = _load(settings)
    render.show_report(campaign)

    if out:
        out.mkdir(parents=True, exist_ok=True)
        target = out / "report.json"
        target.write_text(json.dumps(campaign.as_dict(), indent=2), encoding="utf-8")
        render.console.print(f"[dim]wrote {target}[/dim]")

    if campaign.undeliverable or campaign.invented:
        raise SystemExit(1)


@cli.command()
def check() -> None:
    """Fail only on what someone can fix in the recipient list or the template."""
    settings = Settings()
    campaign, rendered = _load(settings)

    failures: list[str] = []
    if campaign.undeliverable:
        failures.append(
            f"no mailbox found for {len(campaign.undeliverable)} row(s): "
            f"{', '.join(r.raw for r in campaign.undeliverable)}"
        )
    if campaign.invented:
        failures.append(
            f"{len(campaign.invented)} row(s) produced more recipients than they named: "
            f"{', '.join(r.raw for r in campaign.invented)}"
        )
    if not campaign.rendered_agree:
        failures.append(
            f"the two parts of the message disagree on: {', '.join(campaign.divergent_facts)}"
        )

    normalised = sum(1 for r in campaign.rows if r.parsed.fidelity is Fidelity.NORMALISED)
    reported = [
        f"never-decidable outcomes:   {campaign.bounds.silent}",
        f"decidable but late:         {campaign.bounds.pending}",
        f"addresses silently rewritten: {normalised}",
        f"identity spread across policies: {campaign.spread.narrowest}-{campaign.spread.widest}",
        f"silence is consistent with {AMBIGUITY_FLOOR} outcomes, 2 of them failures",
    ]
    render.show_check(campaign, failures, reported)
    if failures:
        raise SystemExit(1)


@cli.command()
@click.argument("address")
def explain(address: str) -> None:
    """Everything known about one supplied address, and everything not known."""
    settings = Settings()
    campaign, _ = _load(settings)
    render.show_explain(campaign, address)


if __name__ == "__main__":
    cli()
