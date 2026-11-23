"""Shared fixtures. The corpus is loaded once and the campaign run once."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from recall_notifier.campaign import CampaignReport, load_recipients, run_campaign
from recall_notifier.compose import Notice
from recall_notifier.models import Normalisation, Recipient

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

sys.path.insert(0, str(DATA))

DEADLINE = 24.0
GIVE_UP = 96.0


@pytest.fixture(scope="session")
def data_dir() -> Path:
    return DATA


@pytest.fixture(scope="session")
def notice() -> Notice:
    return Notice(
        product="Toddler Sleep Sack, model TS-200",
        hazard="The zipper pull can detach and become a choking hazard.",
        lot="LOT-4471",
        sold_between="March 2025 and August 2026",
        remedy="Stop using it immediately and return it for a full refund.",
        reference="RC-2026-0918",
    )


@pytest.fixture(scope="session")
def recipients() -> list[Recipient]:
    return load_recipients(DATA / "recipients.csv")


@pytest.fixture(scope="session")
def campaign(recipients: list[Recipient], notice: Notice) -> CampaignReport:
    report, _ = run_campaign(
        recipients,
        notice,
        deadline_hours=DEADLINE,
        give_up_hours=GIVE_UP,
        policy=Normalisation.RFC5321,
    )
    return report


@pytest.fixture(scope="session")
def case_variants() -> list[str]:
    """The five addresses from the original probe, kept because the 1-to-5 spread is quoted."""
    return [
        "John.Doe@Example.COM",
        "john.doe@example.com",
        "j.o.h.n.d.o.e@example.com",
        "johndoe+recall@example.com",
        "JOHNDOE@EXAMPLE.COM",
    ]
