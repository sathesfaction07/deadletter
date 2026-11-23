"""The CLI. Every command, every exit-code reason, and the sentences that carry the argument."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner
from rich.console import Console

from recall_notifier import render as render_module
from recall_notifier.cli import cli

DATA = Path(__file__).resolve().parents[2] / "data"


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture(autouse=True)
def _point_at_the_corpus(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RN_RECIPIENTS", str(DATA / "recipients.csv"))
    monkeypatch.setenv("RN_DEADLINE_HOURS", "24")
    monkeypatch.setenv("RN_GIVE_UP_HOURS", "96")
    monkeypatch.setenv("RN_NORMALISATION", "rfc5321")
    # Rich wraps to the terminal width, which splits the sentences these tests assert on.
    # The Console is built at import time, so widening it has to happen by replacement.
    monkeypatch.setattr(render_module, "console", Console(width=200, no_color=True))


def flat(text: str) -> str:
    """Collapse whitespace, for assertions on text that crosses a table cell boundary."""
    return " ".join(text.split())


class TestDoctor:
    def test_it_runs_with_no_network_and_no_credentials(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["doctor"])
        assert result.exit_code == 0

    def test_it_says_no_network_is_used(self, runner: CliRunner) -> None:
        assert "none used, ever" in runner.invoke(cli, ["doctor"]).output

    def test_it_admits_there_is_no_smtp_client(self, runner: CliRunner) -> None:
        assert "outcomes come from a fixture" in runner.invoke(cli, ["doctor"]).output

    def test_it_separates_spec_claims_from_implementation_claims(self, runner: CliRunner) -> None:
        output = runner.invoke(cli, ["doctor"]).output
        assert "grounded in a specification" in output
        assert "resting on IMPLEMENTATION behaviour" in output

    def test_it_names_the_claims_that_are_guesses(self, runner: CliRunner) -> None:
        output = runner.invoke(cli, ["doctor"]).output
        assert "GUESSES, and go stale" in output
        assert "invented, not measured" in output
        assert "is a judgement, not a fact" in output

    def test_it_cites_the_rfc_sections(self, runner: CliRunner) -> None:
        output = runner.invoke(cli, ["doctor"]).output
        for section in ("RFC 5322 3.2.2", "RFC 5321 2.4", "RFC 5321 4.5.4.1", "RFC 5321 4.1.3"):
            assert section in output


class TestAddresses:
    def test_it_quotes_the_recursive_grammar(self, runner: CliRunner) -> None:
        output = runner.invoke(cli, ["addresses"]).output
        assert "comment contains itself" in output

    def test_it_states_the_conclusion_as_a_grammar_fact(self, runner: CliRunner) -> None:
        output = runner.invoke(cli, ["addresses"]).output
        assert "NOT A REGULAR LANGUAGE" in output
        assert "not a" in output and "judgement about anyone" in output

    def test_it_shows_the_careful_regexes_rejecting_a_valid_address(
        self, runner: CliRunner
    ) -> None:
        output = runner.invoke(cli, ["addresses"]).output
        assert "REJECT" in output
        assert "least rigorous" in output

    def test_it_names_the_asymmetric_cost(self, runner: CliRunner) -> None:
        output = runner.invoke(cli, ["addresses"]).output
        assert "never told the product is dangerous" in output
        assert "costs one bounce" in output

    def test_it_shows_the_stdlib_disagreeing_with_itself(self, runner: CliRunner) -> None:
        output = runner.invoke(cli, ["addresses"]).output
        assert "disagrees with itself" in output
        assert "INVENTS a recipient, the other DROPS it" in output

    def test_max_depth_controls_the_table(self, runner: CliRunner) -> None:
        short = runner.invoke(cli, ["addresses", "--max-depth", "1"]).output
        longer = runner.invoke(cli, ["addresses", "--max-depth", "5"]).output
        assert len(longer) > len(short)

    def test_it_exits_zero(self, runner: CliRunner) -> None:
        assert runner.invoke(cli, ["addresses"]).exit_code == 0


class TestIdentity:
    def test_it_cites_the_case_sensitivity_rule(self, runner: CliRunner) -> None:
        output = runner.invoke(cli, ["identity"]).output
        assert "case sensitive" in output
        assert "RFC 5321 2.4" in output

    def test_it_lists_every_policy_with_a_count(self, runner: CliRunner) -> None:
        output = runner.invoke(cli, ["identity"]).output
        for policy in ("exact", "rfc5321", "lowercase", "folded"):
            assert policy in output

    def test_it_marks_the_per_domain_list_as_a_guess_that_goes_stale(
        self, runner: CliRunner
    ) -> None:
        assert "goes stale" in runner.invoke(cli, ["identity"]).output

    def test_it_names_the_safety_asymmetry(self, runner: CliRunner) -> None:
        output = runner.invoke(cli, ["identity"]).output
        assert "never told their product is dangerous" in output
        assert "the brief asks to" in output

    def test_it_exits_zero(self, runner: CliRunner) -> None:
        assert runner.invoke(cli, ["identity"]).exit_code == 0


class TestMerges:
    @pytest.mark.parametrize("policy", ["exact", "rfc5321", "lowercase", "folded"])
    def test_every_policy_runs(self, runner: CliRunner, policy: str) -> None:
        result = runner.invoke(cli, ["merges", "--policy", policy])
        assert result.exit_code == 0

    def test_folding_merges_more_than_the_spec_reading(self, runner: CliRunner) -> None:
        folded = runner.invoke(cli, ["merges", "--policy", "folded"]).output
        assert "gmail" in folded
        assert "kept apart by" in folded

    def test_an_unknown_policy_is_rejected(self, runner: CliRunner) -> None:
        assert runner.invoke(cli, ["merges", "--policy", "nonsense"]).exit_code != 0


class TestStates:
    def test_it_shows_four_outcomes_collapsing_onto_silence(self, runner: CliRunner) -> None:
        output = runner.invoke(cli, ["states"]).output
        assert "read, in_inbox, in_spam, discarded" in output

    def test_it_explains_that_rejected_and_bounced_are_one_outcome(self, runner: CliRunner) -> None:
        output = runner.invoke(cli, ["states"]).output
        assert "carry the same outcome" in output
        assert "difference is WHEN" in output

    def test_it_answers_whether_waiting_helps(self, runner: CliRunner) -> None:
        output = runner.invoke(cli, ["states"]).output
        assert "Does waiting help?" in output
        assert "from 5 to 4. Never to one" in output

    def test_it_states_the_inversion(self, runner: CliRunner) -> None:
        output = runner.invoke(cli, ["states"]).output
        assert "You can learn that you failed" in output
        assert "cannot learn that you succeeded" in output

    def test_it_exits_zero(self, runner: CliRunner) -> None:
        assert runner.invoke(cli, ["states"]).exit_code == 0


class TestTiming:
    def test_it_quotes_the_give_up_window(self, runner: CliRunner) -> None:
        output = runner.invoke(cli, ["timing"]).output
        assert "at least 4-5 days" in output
        assert "RFC 5321 4.5.4.1" in output

    def test_it_reports_the_lag_ratio(self, runner: CliRunner) -> None:
        assert "4.0x" in runner.invoke(cli, ["timing"]).output

    def test_it_says_only_the_no_is_actionable(self, runner: CliRunner) -> None:
        assert "says NO" in runner.invoke(cli, ["timing"]).output

    def test_it_calls_bounce_tracking_a_post_mortem_tool(self, runner: CliRunner) -> None:
        output = runner.invoke(cli, ["timing"]).output
        assert "post-mortem tool, not a recall tool" in output

    def test_a_longer_deadline_changes_the_verdict(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("RN_DEADLINE_HOURS", "200")
        output = runner.invoke(cli, ["timing"]).output
        assert "not the one recalls are in" in output


class TestCompose:
    def test_the_default_render_agrees(self, runner: CliRunner) -> None:
        output = runner.invoke(cli, ["compose"]).output
        assert "both parts carry every fact" in output

    def test_the_shortcut_loses_facts_and_says_which(self, runner: CliRunner) -> None:
        output = runner.invoke(cli, ["compose", "--text-from-html"]).output
        assert "disagree on 2 fact(s)" in output
        assert "lot" in output

    def test_the_shortcut_output_is_shown_so_the_damage_is_visible(
        self, runner: CliRunner
    ) -> None:
        output = runner.invoke(cli, ["compose", "--text-from-html"]).output
        assert "the text part this produced" in output

    def test_it_exits_zero_either_way(self, runner: CliRunner) -> None:
        assert runner.invoke(cli, ["compose"]).exit_code == 0
        assert runner.invoke(cli, ["compose", "--text-from-html"]).exit_code == 0


class TestReport:
    def test_it_exits_one_because_the_corpus_has_fixable_defects(self, runner: CliRunner) -> None:
        assert runner.invoke(cli, ["report"]).exit_code == 1

    def test_it_labels_the_failure_count_as_a_floor(self, runner: CliRunner) -> None:
        output = runner.invoke(cli, ["report"]).output
        assert "This is a FLOOR, not a total" in output

    def test_it_labels_the_informed_count_as_a_ceiling(self, runner: CliRunner) -> None:
        output = runner.invoke(cli, ["report"]).output
        assert "Not a count of people reached" in output

    def test_it_says_no_later_report_narrows_the_range(self, runner: CliRunner) -> None:
        output = runner.invoke(cli, ["report"]).output
        assert "never produce a signal at all" in output

    def test_it_reports_how_few_outcomes_were_knowable_in_time(self, runner: CliRunner) -> None:
        output = runner.invoke(cli, ["report"]).output
        assert "outcomes were knowable by the" in output

    def test_it_writes_json_when_asked(self, runner: CliRunner, tmp_path: Path) -> None:
        result = runner.invoke(cli, ["report", "-o", str(tmp_path)])
        assert result.exit_code == 1  # the corpus still has defects
        payload = json.loads((tmp_path / "report.json").read_text())
        assert payload["supplied"] == 29
        assert payload["attempted"] == 26
        assert payload["failures_floor"] == 5
        assert payload["failures_ceiling"] == 26
        assert payload["never_decidable"] == 18
        assert payload["decidable_late"] == 3
        assert payload["lag_ratio"] == 4.0
        assert payload["undeliverable"] == ["u.chen@[203.0.113.9]", "victor-no-at-sign"]
        assert payload["invented"] == ["Sato, Kenji <k.sato@example.jp>"]
        assert payload["suppressed"] == ["alice.tan@example.com"]
        assert payload["rendered_agree"] is True

    def test_the_json_identity_counts_show_the_spread(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        runner.invoke(cli, ["report", "-o", str(tmp_path)])
        counts = json.loads((tmp_path / "report.json").read_text())["identity_counts"]
        assert counts["folded"] < counts["rfc5321"]
        assert len(set(counts.values())) > 1


class TestCheck:
    def test_it_fails_on_the_shipped_corpus_because_the_list_has_fixable_rows(
        self, runner: CliRunner
    ) -> None:
        result = runner.invoke(cli, ["check"])
        assert result.exit_code == 1
        assert "FAIL" in result.output

    def test_it_names_the_rows_a_human_can_fix(self, runner: CliRunner) -> None:
        output = runner.invoke(cli, ["check"]).output
        assert "no mailbox found for 2 row(s)" in output
        assert "victor-no-at-sign" in output
        assert "more recipients than they named" in output

    def test_it_does_not_gate_on_things_nobody_can_fix(self, runner: CliRunner) -> None:
        output = runner.invoke(cli, ["check"]).output
        assert "Reported and NOT failed on" in output
        assert "switched off inside a week" in output

    def test_the_reported_section_carries_the_undecidability_figures(
        self, runner: CliRunner
    ) -> None:
        output = runner.invoke(cli, ["check"]).output
        assert "never-decidable outcomes" in output
        assert "silence is consistent with 4 outcomes, 2 of them failures" in output

    def test_a_clean_list_passes(self, runner: CliRunner, tmp_path: Path) -> None:
        """Undecidable delivery on every row, and it still passes -- because nobody can fix
        that, and a gate firing on it would be switched off."""
        path = tmp_path / "clean.csv"
        path.write_text(
            "address,name,lot\na@example.com,A,L\nb@example.com,B,L\n", encoding="utf-8"
        )
        result = runner.invoke(cli, ["check"], env={"RN_RECIPIENTS": str(path)})
        assert result.exit_code == 0
        assert "PASS" in result.output
        assert "Nothing fixable at source" in result.output

    def test_a_clean_list_still_reports_the_ambiguity(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        path = tmp_path / "clean.csv"
        path.write_text("address,name,lot\na@example.com,A,L\n", encoding="utf-8")
        output = runner.invoke(cli, ["check"], env={"RN_RECIPIENTS": str(path)}).output
        assert "never-decidable outcomes" in output

    def test_a_divergent_message_fails(
        self, runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path = tmp_path / "clean.csv"
        path.write_text("address,name,lot\na@example.com,A,L\n", encoding="utf-8")
        monkeypatch.setenv("RN_RECIPIENTS", str(path))
        monkeypatch.setenv("RN_TEXT_FROM_HTML", "true")
        result = runner.invoke(cli, ["check"])
        assert result.exit_code == 1
        assert "the two parts of the message disagree on" in result.output


class TestExplain:
    def test_it_explains_a_row_that_was_dropped(self, runner: CliRunner) -> None:
        output = flat(runner.invoke(cli, ["explain", "victor-no-at-sign"]).output)
        assert "no mailbox here" in output
        assert "would try to deliver to it" in output

    def test_it_explains_a_row_whose_address_was_rewritten(self, runner: CliRunner) -> None:
        output = runner.invoke(cli, ["explain", "quentin(work)@example.com"]).output
        assert "SILENTLY removed it" in output

    def test_it_explains_a_row_where_a_recipient_was_invented(self, runner: CliRunner) -> None:
        output = flat(runner.invoke(cli, ["explain", "Sato, Kenji <k.sato@example.jp>"]).output)
        assert "invented" in output
        assert "separator to the parser and a surname to the author" in output

    def test_it_lists_every_outcome_still_possible_for_a_silent_row(
        self, runner: CliRunner
    ) -> None:
        output = runner.invoke(cli, ["explain", "alice.tan@example.com"]).output
        assert "outcome still possible" in output
        assert "in_spam" in output
        assert "discarded" in output

    def test_it_shows_the_planted_rejection_as_known_in_time(self, runner: CliRunner) -> None:
        output = runner.invoke(cli, ["explain", "bmehta@example.net"]).output
        assert "known by deadline" in output
        assert "only unambiguous answer" in output

    def test_it_shows_the_late_bounce_as_correct_and_too_late(self, runner: CliRunner) -> None:
        output = runner.invoke(cli, ["explain", "dlindqvist@example.se"]).output
        assert "known too late to act on" in output

    def test_an_unknown_address_says_so_rather_than_guessing(self, runner: CliRunner) -> None:
        output = runner.invoke(cli, ["explain", "nobody@nowhere.example"]).output
        assert "no row supplied as" in output

    def test_it_exits_zero_even_for_an_unknown_address(self, runner: CliRunner) -> None:
        assert runner.invoke(cli, ["explain", "nobody@nowhere.example"]).exit_code == 0


class TestGroup:
    def test_help_lists_every_command(self, runner: CliRunner) -> None:
        output = runner.invoke(cli, ["--help"]).output
        for command in (
            "doctor",
            "addresses",
            "identity",
            "merges",
            "states",
            "timing",
            "compose",
            "report",
            "check",
            "explain",
        ):
            assert command in output

    def test_the_group_help_states_the_premise(self, runner: CliRunner) -> None:
        assert "cannot tell you" in runner.invoke(cli, ["--help"]).output
