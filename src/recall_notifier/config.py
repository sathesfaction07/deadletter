"""Configuration. `RN_`-prefixed environment variables or a `.env` file.

No list-typed fields: Pydantic Settings parses those as JSON, so `RN_X=a,b` fails with a
decode error that reads like a bug in the tool rather than a mistake in the value.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .models import Normalisation
from .timing import SPEC_MINIMUM_GIVE_UP_HOURS


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RN_", env_file=".env", extra="ignore")

    recipients: Path = Path("data/recipients.csv")

    #: How long the recall programme has to notify. Hours, because that is the unit these
    #: deadlines come in, and the gap against the retry window is the point.
    deadline_hours: float = Field(default=24.0, gt=0)

    #: RFC 5321 4.5.4.1 says the give-up time "generally needs to be at least 4-5 days".
    #: Defaulting to the LOW end of the spec's own range, so the lag this tool reports is
    #: the smallest one a compliant MTA could produce rather than the most alarming.
    give_up_hours: float = Field(default=SPEC_MINIMUM_GIVE_UP_HOURS, gt=0)

    #: Which addresses count as the same person. Defaults to the reading that follows
    #: RFC 5321 2.4 rather than the one everybody ships, and `identity` shows what the
    #: choice costs either way.
    normalisation: Normalisation = Normalisation.RFC5321

    #: Generate the text part by stripping tags from the HTML part. False by default because
    #: it loses the label-to-value association, which `compose` demonstrates.
    text_from_html: bool = False
