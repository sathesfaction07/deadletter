"""Addresses, identity, and the models. The claims, tested as claims."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from recall_notifier.addresses import (
    SHIPPED_REGEXES,
    accepted_invalid_addresses,
    demonstrate_non_regularity,
    is_address_literal,
    nested_comment_address,
    parse_address,
    regex_verdicts,
    rejected_valid_addresses,
    stdlib_readings,
    strip_comments,
)
from recall_notifier.identity import (
    FOLDING_DOMAINS,
    asymmetry_note,
    collisions,
    identity_spread,
    normalise,
    normalise_per_domain,
)
from recall_notifier.models import (
    FAILURE_STATES,
    Attempt,
    Decidability,
    Fidelity,
    Normalisation,
    ParsedAddress,
    Recipient,
    Signal,
    TrueState,
    Verdict,
)


class TestNonRegularity:
    """RFC 5322 3.2.2 makes `comment` recursive, so the language is not regular."""

    @pytest.mark.parametrize("depth", [1, 2, 3, 5, 8])
    def test_a_nested_comment_address_is_well_formed_at_any_depth(self, depth: int) -> None:
        address = nested_comment_address(depth)
        assert address.count("(") == depth
        assert address.count(")") == depth
        # Balanced, so strip_comments accepts it and recovers the real mailbox.
        local = address.rpartition("@")[0]
        assert strip_comments(local) == ("user", depth)

    def test_depth_zero_is_rejected_rather_than_returning_a_plain_address(self) -> None:
        with pytest.raises(ValueError, match="at least 1"):
            nested_comment_address(0)

    def test_the_careful_regexes_reject_a_valid_address_and_the_sloppy_one_accepts(self) -> None:
        """The inversion: rigour in the regex costs you the customer."""
        verdicts = regex_verdicts(nested_comment_address(1))
        assert verdicts["the one everyone writes"] is True
        assert verdicts["the careful one"] is False
        assert verdicts['the "RFC-compliant" one'] is False

    @pytest.mark.parametrize("depth", [1, 2, 3, 4, 5])
    def test_no_depth_changes_any_regex_verdict(self, depth: int) -> None:
        """Not a threshold effect. The careful regexes never accept a comment at all, so
        there is no depth at which behaviour flips -- which is what being non-regular in
        this particular way looks like from the outside."""
        assert regex_verdicts(nested_comment_address(depth)) == regex_verdicts(
            nested_comment_address(1)
        )

    def test_demonstrate_returns_a_row_per_depth_with_every_regex(self) -> None:
        rows = demonstrate_non_regularity(4)
        assert len(rows) == 4
        assert all(set(verdicts) == set(SHIPPED_REGEXES) for _, _, verdicts in rows)

    def test_exactly_one_of_three_shipped_regexes_accepts_a_valid_comment(self) -> None:
        for _, _, verdicts in demonstrate_non_regularity(5):
            assert sum(verdicts.values()) == 1


class TestStripComments:
    """The counter-based scan a regex cannot replace."""

    @pytest.mark.parametrize(
        ("local", "expected"),
        [
            ("user", ("user", 0)),
            ("user(x)", ("user", 1)),
            ("user((a))", ("user", 2)),
            ("user(((a)))", ("user", 3)),
            ("a(1)b(2)c", ("abc", 1)),
            ("(lead)user", ("user", 1)),
            ("user(trail)", ("user", 1)),
        ],
    )
    def test_nesting_depth_is_counted(self, local: str, expected: tuple[str, int]) -> None:
        assert strip_comments(local) == expected

    def test_parens_inside_quotes_are_literal_not_comments(self) -> None:
        """RFC 5322 3.2.4: inside a quoted string a paren is just a paren."""
        assert strip_comments('"u(x)"') == ('"u(x)"', 0)

    def test_an_escaped_paren_is_literal(self) -> None:
        assert strip_comments(r"u\(x") == (r"u\(x", 0)

    @pytest.mark.parametrize("bad", ["user(", "user)", "u((x)", "u(x))"])
    def test_unbalanced_comments_raise_rather_than_guessing(self, bad: str) -> None:
        with pytest.raises(ValueError, match="unbalanced"):
            strip_comments(bad)


class TestStdlibDisagreesWithItself:
    """The two entry points return different answers, in both directions."""

    def test_parseaddr_accepts_a_string_with_no_at_sign(self) -> None:
        """It does not signal failure. It hands the string back, so an unguarded caller
        attempts delivery to a surname."""
        single, _ = stdlib_readings("not-an-address")
        assert single == "not-an-address"
        assert "@" not in single

    def test_parseaddr_refuses_an_address_literal_that_rfc5321_permits(self) -> None:
        single, _ = stdlib_readings("user@[192.168.1.1]")
        assert single == ""
        assert is_address_literal("[192.168.1.1]")

    def test_getaddresses_invents_a_recipient_from_a_display_name_comma(self) -> None:
        """One row naming one person becomes two recipients, one of them a surname."""
        single, many = stdlib_readings("Doe, John <john@example.com>")
        assert len(many) == 2
        assert "Doe" in many
        assert single == ""  # and parseaddr drops the whole thing

    def test_the_two_parsers_fail_in_opposite_directions_on_one_input(self) -> None:
        single, many = stdlib_readings("Doe, John <john@example.com>")
        assert single == "" and len(many) > 1, "one drops, the other multiplies"

    def test_parseaddr_strips_comments_before_returning(self) -> None:
        """Which is why parse_address scans the RAW string: scanning parseaddr's output
        would report depth 0 every time and make the reporting branch dead code."""
        for raw in ("user(x)@example.com", "user(a(b)c)@example.com", "us(er)@ex.com"):
            _, out = stdlib_readings(raw)[0], stdlib_readings(raw)[0]
            assert "(" not in out


class TestParseAddress:
    def test_a_plain_address_is_clean_and_unchanged(self) -> None:
        parsed = parse_address("alice@example.com")
        assert parsed.fidelity is Fidelity.CLEAN
        assert parsed.mailbox == "alice@example.com"
        assert parsed.deliverable

    @pytest.mark.parametrize(
        ("raw", "depth"),
        [("quentin(work)@example.com", 1), ("rosa((home))@example.com", 2)],
    )
    def test_a_comment_is_reported_as_a_silent_rewrite(self, raw: str, depth: int) -> None:
        parsed = parse_address(raw)
        assert parsed.fidelity is Fidelity.NORMALISED
        assert parsed.mailbox != raw
        assert f"nested {depth} deep" in parsed.detail
        assert "SILENTLY" in parsed.detail

    def test_the_comment_branch_is_reachable(self) -> None:
        """Guards the defect this code had: the depth scan originally ran on parseaddr's
        output, which has already had comments removed, so the branch never fired."""
        assert any(
            "nested" in parse_address(raw).detail
            for raw in ("quentin(work)@example.com", "(lead)user@example.com")
        )

    def test_a_display_name_comma_is_reported_as_invented(self) -> None:
        parsed = parse_address("Sato, Kenji <k.sato@example.jp>")
        assert parsed.fidelity is Fidelity.INVENTED
        assert parsed.claimed_count == 2
        assert parsed.disagreement

    @pytest.mark.parametrize(
        "raw", ["victor-no-at-sign", "user@", "u.chen@[203.0.113.9]", "(all)@example.com"]
    )
    def test_undeliverable_rows_carry_no_mailbox(self, raw: str) -> None:
        parsed = parse_address(raw)
        assert parsed.fidelity is Fidelity.DROPPED
        assert parsed.mailbox is None
        assert not parsed.deliverable
        assert parsed.claimed_count == 0

    def test_the_two_ways_of_being_dropped_get_different_explanations(self) -> None:
        """They are different failures. `victor-no-at-sign` came BACK from parseaddr and
        would be delivered to; the address literal came back empty and is simply gone.
        One message covering both would be wrong about one of them."""
        handed_back = parse_address("victor-no-at-sign")
        refused = parse_address("u.chen@[203.0.113.9]")
        assert handed_back.fidelity is Fidelity.DROPPED
        assert refused.fidelity is Fidelity.DROPPED
        assert "handed back" in handed_back.detail
        assert "would try to deliver to it" in handed_back.detail
        assert "returned nothing at all" in refused.detail
        assert "dropped in silence" in refused.detail
        assert handed_back.detail != refused.detail

    def test_a_quoted_local_part_with_a_space_survives(self) -> None:
        parsed = parse_address('"tomas nunez"@example.es')
        assert parsed.deliverable
        assert parsed.mailbox == '"tomas nunez"@example.es'

    def test_all_four_fidelities_occur(self) -> None:
        seen = {
            parse_address(raw).fidelity
            for raw in (
                "a@b.com",
                "a(x)@b.com",
                "Doe, John <j@e.com>",
                "nope",
            )
        }
        assert seen == set(Fidelity)

    def test_every_rejected_valid_address_has_a_reason(self) -> None:
        rows = rejected_valid_addresses()
        assert rows and all(why.strip() for _, why in rows)

    def test_every_accepted_invalid_address_has_a_reason(self) -> None:
        rows = accepted_invalid_addresses()
        assert rows and all(why.strip() for _, why in rows)

    def test_leading_and_trailing_whitespace_does_not_change_the_mailbox(self) -> None:
        assert parse_address("  a@b.com  ").mailbox == "a@b.com"


class TestNormalisation:
    def test_rfc5321_lowercases_the_domain_only(self) -> None:
        """RFC 5321 2.4: the local part is case-SENSITIVE."""
        assert normalise("John@Example.COM", Normalisation.RFC5321) == "John@example.com"

    def test_lowercase_flattens_the_local_part_too_which_the_spec_does_not_sanction(self) -> None:
        assert normalise("John@Example.COM", Normalisation.LOWERCASE) == "john@example.com"

    def test_exact_changes_nothing(self) -> None:
        assert normalise("John@Example.COM", Normalisation.EXACT) == "John@Example.COM"

    @pytest.mark.parametrize(
        "address",
        [
            "j.o.h.n@gmail.com",
            "john@gmail.com",
            "john+recall@gmail.com",
            "J.O.H.N+2026@GMAIL.COM",
        ],
    )
    def test_folding_maps_every_gmail_variant_onto_one_key(self, address: str) -> None:
        assert normalise(address, Normalisation.FOLDED) == "john@gmail.com"

    def test_a_string_with_no_at_sign_is_returned_unchanged_by_every_policy(self) -> None:
        for policy in Normalisation:
            assert normalise("no-at-sign", policy) == "no-at-sign"

    def test_per_domain_folds_only_where_folding_is_known_to_happen(self) -> None:
        assert normalise_per_domain("a.b@gmail.com") == "ab@gmail.com"
        assert normalise_per_domain("a.b@example.ph") == "a.b@example.ph"

    def test_per_domain_still_rests_on_a_hardcoded_guess(self) -> None:
        """Stated as a test so the limitation is not only in a docstring."""
        assert "gmail.com" in FOLDING_DOMAINS
        assert normalise_per_domain("a.b@some-unknown-provider.example") == (
            "a.b@some-unknown-provider.example"
        )

    def test_per_domain_leaves_a_bare_string_alone(self) -> None:
        assert normalise_per_domain("no-at-sign") == "no-at-sign"


class TestIdentitySpread:
    def test_the_same_five_addresses_are_between_one_and_five_people(
        self, case_variants: list[str]
    ) -> None:
        """The figure quoted in the docs, asserted rather than remembered."""
        spread = identity_spread(case_variants)
        assert spread.addresses == 5
        assert spread.counts["exact"] == 5
        assert spread.counts["rfc5321"] == 5
        assert spread.counts["lowercase"] == 4
        assert spread.counts["folded"] == 1
        assert (spread.narrowest, spread.widest) == (1, 5)
        assert spread.ambiguous

    def test_the_two_error_magnitudes_are_equal(self, case_variants: list[str]) -> None:
        """Same number, opposite direction. The costs differ; the arithmetic does not."""
        spread = identity_spread(case_variants)
        assert spread.possible_duplicates == spread.possible_silences == 4

    def test_an_unambiguous_list_says_so_and_does_not_generalise(self) -> None:
        spread = identity_spread(["a@x.example", "b@x.example"])
        assert not spread.ambiguous
        note = asymmetry_note(spread)
        assert "nothing is at stake" in note
        assert "not a general result" in note

    def test_the_asymmetry_note_names_the_safety_direction(self, case_variants: list[str]) -> None:
        note = asymmetry_note(identity_spread(case_variants))
        assert "never told" in note
        assert "the brief asks to" in note

    def test_an_empty_list_is_zero_recipients_under_every_policy(self) -> None:
        spread = identity_spread([])
        assert spread.addresses == 0
        assert set(spread.counts.values()) == {0}
        assert not spread.ambiguous


class TestCollisions:
    def test_folding_merges_gmail_variants_and_names_what_keeps_them_apart(self) -> None:
        found = collisions(
            ["a.b@gmail.com", "ab@gmail.com", "ab+tag@gmail.com"], Normalisation.FOLDED
        )
        assert len(found) == 1
        assert found[0].size == 3
        assert set(found[0].separated_by) >= {"exact", "rfc5321"}

    def test_exact_merges_only_byte_identical_strings(self) -> None:
        found = collisions(["a@x.example", "a@x.example", "A@x.example"], Normalisation.EXACT)
        assert len(found) == 1
        assert found[0].members == ("a@x.example", "a@x.example")

    def test_a_list_with_no_duplicates_produces_no_collisions(self) -> None:
        assert collisions(["a@x.example", "b@y.example"], Normalisation.FOLDED) == []

    def test_separated_by_is_empty_when_every_policy_agrees(self) -> None:
        """Two identical strings are one person under all four, so nothing separates them."""
        found = collisions(["a@x.example", "a@x.example"], Normalisation.RFC5321)
        assert found[0].separated_by == ()


class TestModelValidators:
    def test_a_blank_raw_address_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="cannot be blank"):
            Recipient(raw="   ")

    def test_dropped_must_not_carry_a_mailbox(self) -> None:
        with pytest.raises(ValidationError, match="DROPPED must carry no mailbox"):
            ParsedAddress(raw="x", mailbox="a@b.com", fidelity=Fidelity.DROPPED, detail="")

    def test_a_non_dropped_fidelity_requires_a_mailbox(self) -> None:
        with pytest.raises(ValidationError, match="requires a mailbox"):
            ParsedAddress(raw="x", mailbox=None, fidelity=Fidelity.CLEAN, detail="")

    def test_clean_means_the_string_came_back_unchanged(self) -> None:
        with pytest.raises(ValidationError, match="returned the string unchanged"):
            ParsedAddress(raw="A@b.com", mailbox="a@b.com", fidelity=Fidelity.CLEAN, detail="")

    def test_invented_requires_more_than_one_claimed_mailbox(self) -> None:
        with pytest.raises(ValidationError, match="more mailboxes were claimed"):
            ParsedAddress(
                raw="x", mailbox="a@b.com", fidelity=Fidelity.INVENTED, detail="", claimed_count=1
            )

    def test_rejected_requires_a_5xx_code(self) -> None:
        with pytest.raises(ValidationError, match="REJECTED requires a 5xx"):
            Attempt(mailbox="a@b.com", signal=Signal.REJECTED, elapsed_hours=0, smtp_code=451)

    def test_deferred_requires_a_4xx_code(self) -> None:
        with pytest.raises(ValidationError, match="DEFERRED requires a 4xx"):
            Attempt(mailbox="a@b.com", signal=Signal.DEFERRED, elapsed_hours=0, smtp_code=550)

    def test_nothing_has_no_arrival_time_because_it_never_arrived(self) -> None:
        with pytest.raises(ValidationError, match="absence of a signal"):
            Attempt(mailbox="a@b.com", signal=Signal.NOTHING, elapsed_hours=5.0)

    def test_negative_elapsed_hours_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Attempt(mailbox="a@b.com", signal=Signal.BOUNCED, elapsed_hours=-1.0)

    def test_a_verdict_ruling_out_every_state_is_a_bug_not_a_result(self) -> None:
        with pytest.raises(ValidationError, match="bug in the state map"):
            Verdict(
                mailbox="a@b.com",
                signal=Signal.NOTHING,
                consistent_states=(),
                decidability=Decidability.NEVER,
                known_by_deadline=False,
            )


class TestVerdictProperties:
    def _verdict(self, states: tuple[TrueState, ...], how: Decidability) -> Verdict:
        return Verdict(
            mailbox="a@b.com",
            signal=Signal.NOTHING,
            consistent_states=states,
            decidability=how,
            known_by_deadline=False,
        )

    def test_in_flight_alone_is_not_a_settled_outcome(self) -> None:
        """The defect this replaced: `determined` returned True for a deferred message,
        reporting something still being retried as decided."""
        verdict = self._verdict((TrueState.IN_FLIGHT,), Decidability.EVENTUAL)
        assert not verdict.determined
        assert verdict.ambiguous_about_failure

    def test_a_single_real_outcome_is_settled(self) -> None:
        verdict = self._verdict((TrueState.NEVER_ACCEPTED,), Decidability.IMMEDIATE)
        assert verdict.determined
        assert not verdict.ambiguous_about_failure

    def test_the_silent_four_are_ambiguous_about_failure(self) -> None:
        verdict = self._verdict(
            (TrueState.READ, TrueState.IN_INBOX, TrueState.IN_SPAM, TrueState.DISCARDED),
            Decidability.NEVER,
        )
        assert verdict.could_be_failure and verdict.could_be_success
        assert verdict.ambiguous_about_failure

    def test_an_unread_inbox_is_not_counted_as_a_failure(self) -> None:
        """A judgement, stated: delivery is what a sender can be responsible for."""
        assert TrueState.IN_INBOX not in FAILURE_STATES
        assert TrueState.IN_SPAM in FAILURE_STATES
