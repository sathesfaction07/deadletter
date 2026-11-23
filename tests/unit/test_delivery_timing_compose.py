"""Delivery epistemics, the deadline arithmetic, the two-part message, and the campaign."""

from __future__ import annotations

import pytest

from recall_notifier.campaign import (
    PLANTED_OUTCOMES,
    CampaignReport,
    load_recipients,
    run_campaign,
)
from recall_notifier.compose import (
    Notice,
    render,
    strip_tags,
)
from recall_notifier.delivery import (
    AMBIGUITY_FLOOR,
    SILENT_STATES,
    collapse_table,
    consistent_states,
    decidability,
    emits_signal,
    failure_bounds,
    verdict,
)
from recall_notifier.models import (
    FAILURE_STATES,
    Attempt,
    Decidability,
    Fidelity,
    Normalisation,
    Signal,
    TrueState,
)
from recall_notifier.timing import (
    SPEC_MINIMUM_GIVE_UP_HOURS,
    Budget,
    budget_table,
    signal_arrival,
)

DEADLINE = 24.0
GIVE_UP = 96.0


def _attempt(signal: Signal, hours: float = 0.0, code: int | None = None) -> Attempt:
    return Attempt(mailbox="a@b.example", signal=signal, elapsed_hours=hours, smtp_code=code)


class TestTheCollapse:
    """Four distinct outcomes emit nothing. That is the whole finding."""

    def test_silence_is_consistent_with_exactly_four_outcomes(self) -> None:
        assert AMBIGUITY_FLOOR == 4
        assert len(SILENT_STATES) == 4

    def test_two_of_the_four_silent_outcomes_are_failures(self) -> None:
        assert sum(1 for s in SILENT_STATES if s in FAILURE_STATES) == 2

    def test_four_outcomes_map_onto_nothing(self) -> None:
        nothing = [s for s in TrueState if emits_signal(s) is Signal.NOTHING]
        assert len(nothing) == 4
        assert set(nothing) == set(SILENT_STATES)

    def test_the_same_outcome_produces_two_different_signals_depending_on_timing(self) -> None:
        """A refusal at RCPT TO and a DSN three days later are the same TrueState."""
        assert emits_signal(TrueState.NEVER_ACCEPTED, discovered_at_handover=True) is Signal.REJECTED
        assert (
            emits_signal(TrueState.NEVER_ACCEPTED, discovered_at_handover=False) is Signal.BOUNCED
        )

    def test_no_signal_bucket_is_empty(self) -> None:
        """The defect this guards: `bounced` had zero states because the forward map took
        only the outcome, so a row sat in the table that could never be populated."""
        for name, count, _, which in collapse_table():
            assert count >= 1, f"{name} is an empty bucket"
            assert which

    def test_the_collapse_table_marks_nothing_as_the_many_to_one_row(self) -> None:
        rows = {name: count for name, count, _, _ in collapse_table()}
        assert rows["nothing"] == 4
        assert rows["rejected"] == rows["bounced"] == rows["deferred"] == 1


class TestConsistentStates:
    def test_a_rejection_settles_the_outcome_exactly(self) -> None:
        assert consistent_states(Signal.REJECTED, False) == (TrueState.NEVER_ACCEPTED,)
        assert consistent_states(Signal.REJECTED, True) == (TrueState.NEVER_ACCEPTED,)

    def test_a_bounce_settles_the_outcome_too_just_later(self) -> None:
        assert consistent_states(Signal.BOUNCED, True) == (TrueState.NEVER_ACCEPTED,)

    def test_silence_with_the_window_open_has_five_candidates(self) -> None:
        assert len(consistent_states(Signal.NOTHING, False)) == 5
        assert TrueState.IN_FLIGHT in consistent_states(Signal.NOTHING, False)

    def test_closing_the_window_removes_exactly_one_candidate(self) -> None:
        before = consistent_states(Signal.NOTHING, False)
        after = consistent_states(Signal.NOTHING, True)
        assert set(before) - set(after) == {TrueState.IN_FLIGHT}
        assert len(after) == AMBIGUITY_FLOOR

    def test_waiting_never_settles_silence(self) -> None:
        """The point: no report run at any later time narrows this."""
        assert len(consistent_states(Signal.NOTHING, True)) > 1

    def test_a_deferral_is_in_flight_while_the_window_is_open(self) -> None:
        assert consistent_states(Signal.DEFERRED, False) == (TrueState.IN_FLIGHT,)

    def test_a_deferral_whose_window_closed_with_no_dsn_falls_back_to_the_silent_four(self) -> None:
        assert consistent_states(Signal.DEFERRED, True) == SILENT_STATES

    @pytest.mark.parametrize("signal", list(Signal))
    def test_no_signal_ever_rules_out_every_outcome(self, signal: Signal) -> None:
        for closed in (False, True):
            assert consistent_states(signal, closed)

    def test_only_the_negative_signals_are_ever_decisive(self) -> None:
        """The inversion. You can learn that you failed; you cannot learn that you
        succeeded."""
        decisive = {
            s for s in Signal if len(consistent_states(s, True)) == 1
        }
        assert decisive == {Signal.REJECTED, Signal.BOUNCED}
        for signal in decisive:
            assert consistent_states(signal, True)[0] in FAILURE_STATES


class TestDecidability:
    def test_a_rejection_is_immediate(self) -> None:
        assert decidability(Signal.REJECTED) is Decidability.IMMEDIATE

    @pytest.mark.parametrize("signal", [Signal.BOUNCED, Signal.DEFERRED])
    def test_asynchronous_signals_are_eventual(self, signal: Signal) -> None:
        assert decidability(signal) is Decidability.EVENTUAL

    def test_silence_is_never_decidable(self) -> None:
        assert decidability(Signal.NOTHING) is Decidability.NEVER

    def test_every_decidability_value_is_produced_by_some_signal(self) -> None:
        assert {decidability(s) for s in Signal} == set(Decidability)


class TestVerdict:
    def test_a_rejection_is_known_at_send_time_and_is_a_no(self) -> None:
        result = verdict(_attempt(Signal.REJECTED, 0.0, 550), DEADLINE, GIVE_UP)
        assert result.known_by_deadline
        assert result.determined
        assert "only unambiguous answer" in result.detail

    def test_a_late_bounce_is_correct_and_useless(self) -> None:
        result = verdict(_attempt(Signal.BOUNCED, 78.0), DEADLINE, GIVE_UP)
        assert result.determined
        assert not result.known_by_deadline
        assert "known too late" in result.detail

    def test_an_early_bounce_is_actionable(self) -> None:
        result = verdict(_attempt(Signal.BOUNCED, 3.0), DEADLINE, GIVE_UP)
        assert result.known_by_deadline
        assert "inside the deadline" in result.detail

    def test_a_bounce_exactly_on_the_deadline_counts_as_in_time(self) -> None:
        assert verdict(_attempt(Signal.BOUNCED, DEADLINE), DEADLINE, GIVE_UP).known_by_deadline

    def test_a_deferral_names_the_window_it_is_waiting_on(self) -> None:
        result = verdict(_attempt(Signal.DEFERRED, 2.0, 451), DEADLINE, GIVE_UP)
        assert not result.known_by_deadline
        assert "give-up" in result.detail

    def test_silence_reports_how_many_outcomes_remain_and_how_many_are_failures(self) -> None:
        result = verdict(_attempt(Signal.NOTHING), DEADLINE, GIVE_UP)
        assert not result.known_by_deadline
        assert "there will not be one" in result.detail
        assert "2 of which" in result.detail


class TestFailureBounds:
    def test_a_mixed_campaign_reports_a_range_not_a_number(self) -> None:
        verdicts = [
            verdict(_attempt(Signal.REJECTED, 0.0, 550), DEADLINE, GIVE_UP),
            verdict(_attempt(Signal.BOUNCED, 78.0), DEADLINE, GIVE_UP),
            verdict(_attempt(Signal.NOTHING), DEADLINE, GIVE_UP),
            verdict(_attempt(Signal.NOTHING), DEADLINE, GIVE_UP),
            verdict(_attempt(Signal.DEFERRED, 2.0, 451), DEADLINE, GIVE_UP),
        ]
        bounds = failure_bounds(verdicts)
        assert bounds.floor == 2
        assert bounds.ceiling == 5
        assert bounds.gap == 3
        assert not bounds.observable

    def test_the_gap_splits_into_never_and_merely_late(self) -> None:
        """The overclaim this guards: an earlier summary called the whole gap permanent,
        which was wrong for the deferred ones."""
        verdicts = [
            verdict(_attempt(Signal.NOTHING), DEADLINE, GIVE_UP),
            verdict(_attempt(Signal.NOTHING), DEADLINE, GIVE_UP),
            verdict(_attempt(Signal.DEFERRED, 2.0, 451), DEADLINE, GIVE_UP),
        ]
        bounds = failure_bounds(verdicts)
        assert bounds.silent == 2
        assert bounds.pending == 1
        assert bounds.silent + bounds.pending == bounds.gap

    def test_the_summary_distinguishes_permanent_from_late(self) -> None:
        bounds = failure_bounds(
            [
                verdict(_attempt(Signal.NOTHING), DEADLINE, GIVE_UP),
                verdict(_attempt(Signal.DEFERRED, 2.0, 451), DEADLINE, GIVE_UP),
            ]
        )
        summary = bounds.summary()
        assert "never produce a signal" in summary
        assert "only after the deadline" in summary

    def test_an_all_determined_campaign_says_the_number_is_exact_and_does_not_generalise(
        self,
    ) -> None:
        bounds = failure_bounds([verdict(_attempt(Signal.REJECTED, 0.0, 550), DEADLINE, GIVE_UP)])
        assert bounds.observable
        assert "is exact" in bounds.summary()
        assert "does not generalise" in bounds.summary()

    def test_an_empty_campaign_is_observable_but_says_nothing(self) -> None:
        bounds = failure_bounds([])
        assert bounds.recipients == 0
        assert bounds.observable


class TestTimingArithmetic:
    def test_the_spec_minimum_is_four_days(self) -> None:
        assert SPEC_MINIMUM_GIVE_UP_HOURS == 96.0

    def test_a_one_day_deadline_against_the_spec_minimum_lags_by_four(self) -> None:
        budget = Budget(deadline_hours=24.0, give_up_hours=96.0)
        assert budget.lag_ratio == 4.0
        assert budget.deadline_inside_window

    def test_only_the_rejection_is_actionable_inside_the_window(self) -> None:
        budget = Budget(deadline_hours=24.0, give_up_hours=96.0)
        decidable = budget.decidable_by_deadline()
        assert decidable["rejected"] is True
        assert decidable["bounced"] is False
        assert decidable["deferred"] is False
        assert decidable["nothing"] is False
        assert budget.actionable_classes == 1

    def test_silence_is_never_actionable_at_any_deadline(self) -> None:
        for deadline in (1.0, 24.0, 240.0, 10_000.0):
            budget = Budget(deadline_hours=deadline, give_up_hours=96.0)
            assert budget.decidable_by_deadline()["nothing"] is False

    def test_a_deadline_past_the_window_is_the_comfortable_case(self) -> None:
        budget = Budget(deadline_hours=200.0, give_up_hours=96.0)
        assert not budget.deadline_inside_window
        assert budget.actionable_classes == 3
        assert "not the one recalls are in" in budget.summary()

    def test_the_summary_names_the_ratio_and_that_the_usable_signal_is_a_no(self) -> None:
        summary = Budget(deadline_hours=24.0, give_up_hours=96.0).summary()
        assert "4.0x" in summary
        assert "says NO" in summary

    @pytest.mark.parametrize("bad", [0.0, -1.0])
    def test_a_non_positive_budget_is_rejected(self, bad: float) -> None:
        with pytest.raises(Exception, match="greater than 0"):
            Budget(deadline_hours=bad, give_up_hours=96.0)

    def test_the_budget_table_covers_both_sides_of_the_window(self) -> None:
        rows = budget_table()
        assert any(inside for *_, inside in rows)
        assert any(not inside for *_, inside in rows)

    def test_the_24h_row_leaves_one_actionable_class(self) -> None:
        row = next(r for r in budget_table() if r[0] == 24.0)
        assert row[2] == 1

    @pytest.mark.parametrize("signal", list(Signal))
    def test_every_signal_has_an_arrival_story(self, signal: Signal) -> None:
        how, why = signal_arrival(signal, 96.0)
        assert isinstance(how, Decidability)
        assert why.strip()

    def test_silence_arrival_says_no_signal_is_emitted(self) -> None:
        _, why = signal_arrival(Signal.NOTHING, 96.0)
        assert "no signal is emitted" in why


class TestCompose:
    def test_both_parts_carry_every_fact_when_each_is_rendered_properly(
        self, notice: Notice
    ) -> None:
        rendered = render(notice)
        assert rendered.agree
        assert rendered.missing_from_html == ()
        assert rendered.missing_from_text == ()

    def test_a_correct_message_is_not_reported_divergent(self, notice: Notice) -> None:
        """Guards a threshold artifact: an earlier check measured raw character distance
        with a 40-char window, and the correct HTML failed it at 42."""
        assert render(notice).agree

    def test_stripping_tags_loses_the_label_to_value_association(self, notice: Notice) -> None:
        rendered = render(notice, text_from_html=True)
        assert not rendered.agree
        assert set(rendered.missing_from_text) == {"lot", "sold_between"}
        assert rendered.missing_from_html == ()

    def test_the_values_survive_stripping_but_the_meaning_does_not(self, notice: Notice) -> None:
        """Which is why a value-presence check passes and says nothing."""
        rendered = render(notice, text_from_html=True)
        assert notice.lot in rendered.text
        assert "lot" in rendered.missing_from_text

    def test_a_one_line_document_does_not_satisfy_the_check_vacuously(self, notice: Notice) -> None:
        """Guards the `all([])` trap: an earlier check asked whether label and value were on
        the same LINE, which tag-stripping satisfies by collapsing everything onto one."""
        rendered = render(notice, text_from_html=True)
        assert rendered.text.count("\n") == 0
        assert rendered.missing_from_text

    def test_the_divergence_summary_says_the_client_decides(self, notice: Notice) -> None:
        summary = render(notice, text_from_html=True).summary()
        assert "mail client" in summary
        assert "some customers get the fact and some do not" in summary

    def test_agreement_summary_says_either_part_is_complete(self, notice: Notice) -> None:
        assert "whichever one the client shows" in render(notice).summary()

    def test_strip_tags_removes_markup_and_collapses_whitespace(self) -> None:
        assert strip_tags("<p>a</p>\n<p>b</p>") == "a b"

    @pytest.mark.parametrize("field", ["product", "hazard", "lot", "sold_between", "remedy"])
    def test_a_blank_required_fact_cannot_ship(self, field: str) -> None:
        facts = {
            "product": "p",
            "hazard": "h",
            "lot": "l",
            "sold_between": "s",
            "remedy": "r",
            "reference": "ref",
        }
        facts[field] = "   "
        with pytest.raises(Exception, match="cannot be blank|at least 1"):
            Notice(**facts)

    def test_the_divergent_facts_list_is_the_union_of_both_parts(self, notice: Notice) -> None:
        rendered = render(notice, text_from_html=True)
        assert set(rendered.divergent_facts) == set(rendered.missing_from_text) | set(
            rendered.missing_from_html
        )


class TestCampaign:
    def test_the_corpus_loads_and_preserves_the_raw_strings(self, recipients: list) -> None:
        assert len(recipients) == 29
        assert any(r.raw == "victor-no-at-sign" for r in recipients)
        assert any(r.raw == "Sato, Kenji <k.sato@example.jp>" for r in recipients)

    def test_every_planted_row_is_present_on_disk(self, data_dir) -> None:
        from generate import PLANTED, ROWS

        on_disk = {row[0] for row in ROWS}
        missing = set(PLANTED) - on_disk
        assert not missing, f"planted rows no longer in the corpus: {missing}"

    def test_the_generator_output_matches_the_shipped_file(self, recipients: list) -> None:
        from generate import ROWS

        assert len(recipients) == len(ROWS)

    def test_every_signal_occurs_in_the_shipped_campaign(self, campaign: CampaignReport) -> None:
        """Without this the tests below would be asserting about branches nothing reaches."""
        seen = {r.attempt.signal for r in campaign.rows if r.attempt}
        assert seen == set(Signal)

    def test_every_decidability_occurs(self, campaign: CampaignReport) -> None:
        seen = {r.verdict.decidability for r in campaign.rows if r.verdict}
        assert seen == set(Decidability)

    def test_both_sides_of_the_deadline_occur(self, campaign: CampaignReport) -> None:
        seen = {r.verdict.known_by_deadline for r in campaign.rows if r.verdict}
        assert seen == {True, False}

    def test_every_fidelity_occurs(self, campaign: CampaignReport) -> None:
        seen = {r.parsed.fidelity for r in campaign.rows}
        assert seen == set(Fidelity)

    def test_the_planted_outcomes_are_the_reason_a_rejection_exists(
        self, campaign: CampaignReport
    ) -> None:
        """Named explicitly so nobody thinks the hash happened to produce one."""
        rejected = [r for r in campaign.rows if r.attempt and r.attempt.signal is Signal.REJECTED]
        assert rejected
        assert any(r.attempt.mailbox in PLANTED_OUTCOMES for r in rejected)

    def test_undeliverable_rows_are_reported_and_not_attempted(
        self, campaign: CampaignReport
    ) -> None:
        assert len(campaign.undeliverable) == 2
        raws = {r.raw for r in campaign.undeliverable}
        assert raws == {"u.chen@[203.0.113.9]", "victor-no-at-sign"}
        assert all(not r.attempted for r in campaign.undeliverable)

    def test_the_display_name_comma_row_is_flagged_as_inventing_a_recipient(
        self, campaign: CampaignReport
    ) -> None:
        assert len(campaign.invented) == 1
        assert campaign.invented[0].raw == "Sato, Kenji <k.sato@example.jp>"

    def test_the_exact_duplicate_is_suppressed(self, campaign: CampaignReport) -> None:
        assert len(campaign.suppressed) == 1
        assert campaign.suppressed[0].raw == "alice.tan@example.com"

    def test_the_identity_spread_is_wide_on_the_shipped_list(
        self, campaign: CampaignReport
    ) -> None:
        assert campaign.spread.ambiguous
        assert campaign.spread.counts["folded"] < campaign.spread.counts["rfc5321"]

    def test_the_failure_count_is_a_range_and_the_gap_is_mostly_permanent(
        self, campaign: CampaignReport
    ) -> None:
        assert not campaign.bounds.observable
        assert campaign.bounds.silent > campaign.bounds.pending

    def test_informed_is_reported_as_a_ceiling_not_a_count(self, campaign: CampaignReport) -> None:
        assert campaign.informed_ceiling == campaign.attempted - campaign.bounds.floor
        assert campaign.informed_ceiling < campaign.attempted

    def test_hardly_any_outcome_is_knowable_by_the_deadline(self, campaign: CampaignReport) -> None:
        known = sum(1 for r in campaign.rows if r.verdict and r.verdict.known_by_deadline)
        assert known == 2
        assert known < campaign.attempted / 4

    def test_the_report_dict_carries_the_range_rather_than_one_number(
        self, campaign: CampaignReport
    ) -> None:
        payload = campaign.as_dict()
        assert payload["failures_floor"] < payload["failures_ceiling"]
        assert payload["never_decidable"] > 0
        assert payload["lag_ratio"] == 4.0

    def test_changing_only_the_policy_changes_who_gets_suppressed(
        self, recipients: list, notice: Notice
    ) -> None:
        """The dedup decision is visible in the output, not buried in a config value."""
        strict, _ = run_campaign(
            recipients,
            notice,
            deadline_hours=DEADLINE,
            give_up_hours=GIVE_UP,
            policy=Normalisation.EXACT,
        )
        folded, _ = run_campaign(
            recipients,
            notice,
            deadline_hours=DEADLINE,
            give_up_hours=GIVE_UP,
            policy=Normalisation.FOLDED,
        )
        assert len(folded.suppressed) > len(strict.suppressed)
        assert folded.attempted < strict.attempted

    def test_a_stricter_policy_never_suppresses_more_than_a_looser_one(
        self, recipients: list, notice: Notice
    ) -> None:
        counts = {}
        for policy in Normalisation:
            report, _ = run_campaign(
                recipients,
                notice,
                deadline_hours=DEADLINE,
                give_up_hours=GIVE_UP,
                policy=policy,
            )
            counts[policy] = len(report.suppressed)
        assert counts[Normalisation.EXACT] <= counts[Normalisation.LOWERCASE]
        assert counts[Normalisation.LOWERCASE] <= counts[Normalisation.FOLDED]

    def test_the_campaign_is_deterministic(self, recipients: list, notice: Notice) -> None:
        first, _ = run_campaign(
            recipients,
            notice,
            deadline_hours=DEADLINE,
            give_up_hours=GIVE_UP,
            policy=Normalisation.RFC5321,
        )
        second, _ = run_campaign(
            recipients,
            notice,
            deadline_hours=DEADLINE,
            give_up_hours=GIVE_UP,
            policy=Normalisation.RFC5321,
        )
        assert first.as_dict() == second.as_dict()

    def test_an_empty_recipient_list_produces_an_empty_report(self, notice: Notice) -> None:
        report, _ = run_campaign(
            [],
            notice,
            deadline_hours=DEADLINE,
            give_up_hours=GIVE_UP,
            policy=Normalisation.RFC5321,
        )
        assert report.supplied == 0
        assert report.attempted == 0
        assert report.bounds.recipients == 0

    def test_blank_csv_rows_are_skipped_rather_than_becoming_recipients(self, tmp_path) -> None:
        path = tmp_path / "r.csv"
        path.write_text("address,name,lot\na@b.example,A,L\n,,\n  ,,\n", encoding="utf-8")
        assert len(load_recipients(path)) == 1
