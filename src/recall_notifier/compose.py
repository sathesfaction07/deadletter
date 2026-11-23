"""Building the notice, and checking that its two halves say the same thing.

A `multipart/alternative` message carries an HTML part and a plain-text part. The client
picks one and the recipient never sees the other. So a recall notice is TWO documents, and
whether they make the same claims is nobody's job.

That matters here because the facts in a recall notice are the point: which lot, which
hazard, what to do. If the text part is generated from the HTML by stripping tags, a fact
that lived in a table can vanish -- which is Shoehorn's finding about markdown,
arriving again through a different door. The difference is that here BOTH documents ship,
and only one is read.

So `compose` renders both parts from the same structured facts, then checks the rendered
output for the facts it was given. Rendering from one source does not by itself guarantee
agreement -- a template can simply omit a field -- so the check is on the output, not on
the intent.
"""

from __future__ import annotations

import re

from jinja2 import Environment, StrictUndefined
from pydantic import BaseModel, ConfigDict, Field, field_validator

#: StrictUndefined so a template referencing a fact that does not exist fails loudly.
#: The default silently renders an empty string, which for a recall notice means shipping a
#: message with a blank hazard description and no error anywhere.
_ENV = Environment(undefined=StrictUndefined, autoescape=True)

HTML_TEMPLATE = """\
<html><body>
<h1>Safety recall: {{ product }}</h1>
<p>{{ hazard }}</p>
<table>
  <tr><th>Lot</th><th>Sold between</th></tr>
  <tr><td>{{ lot }}</td><td>{{ sold_between }}</td></tr>
</table>
<p>What to do: {{ remedy }}</p>
<p>Reference {{ reference }}</p>
</body></html>
"""

TEXT_TEMPLATE = """\
SAFETY RECALL: {{ product }}

{{ hazard }}

Lot: {{ lot }}
Sold between: {{ sold_between }}

What to do: {{ remedy }}

Reference {{ reference }}
"""


class Notice(BaseModel):
    """The facts a recall notice must carry, as data rather than as prose.

    Every field is required. A recall notice missing its lot number is not a recall notice,
    and defaulting one to an empty string would let it ship.
    """

    model_config = ConfigDict(frozen=True)

    product: str = Field(min_length=1)
    hazard: str = Field(min_length=1)
    lot: str = Field(min_length=1)
    sold_between: str = Field(min_length=1)
    remedy: str = Field(min_length=1)
    reference: str = Field(min_length=1)

    @field_validator("*")
    @classmethod
    def _not_whitespace(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("a recall notice field cannot be blank")
        return v

    @property
    def facts(self) -> dict[str, str]:
        return self.model_dump()


class Rendered(BaseModel):
    """Both parts of the message, plus which facts each one actually contains."""

    model_config = ConfigDict(frozen=True)

    html: str
    text: str
    missing_from_html: tuple[str, ...]
    missing_from_text: tuple[str, ...]

    @property
    def agree(self) -> bool:
        return not self.missing_from_html and not self.missing_from_text

    @property
    def divergent_facts(self) -> tuple[str, ...]:
        return tuple(sorted(set(self.missing_from_html) | set(self.missing_from_text)))

    def summary(self) -> str:
        if self.agree:
            return "both parts carry every fact, so whichever one the client shows is complete"
        return (
            f"the two parts of this ONE message disagree on {len(self.divergent_facts)} fact(s): "
            f"{', '.join(self.divergent_facts)}. Which version a recipient sees is decided by "
            f"their mail client, so some customers get the fact and some do not"
        )


def strip_tags(html: str) -> str:
    """The obvious way to make a text part from an HTML part, and the reason not to.

    Tags come out, text stays. Table STRUCTURE is what carries the association between "Lot"
    and its value, and structure is exactly what this removes -- so the values survive as
    bare tokens with nothing saying what they mean.
    """
    without_tags = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", without_tags).strip()


def render(notice: Notice, *, text_from_html: bool = False) -> Rendered:
    """Render both parts and report which facts are missing from each.

    `text_from_html=True` reproduces the shortcut of generating the text part by stripping
    tags. The facts survive that as tokens; what does not survive is the labelling, so the
    check below looks for `label: value` adjacency rather than for the value alone.
    """
    facts = notice.facts
    html = _ENV.from_string(HTML_TEMPLATE).render(**facts)
    text = strip_tags(html) if text_from_html else _ENV.from_string(TEXT_TEMPLATE).render(**facts)

    return Rendered(
        html=html,
        text=text,
        missing_from_html=_missing(html, notice),
        missing_from_text=_missing(text, notice),
    )


#: The two facts that live in a table in the HTML part, with the label each one hangs off.
#: These are the only ones where "is the value present" is the wrong question -- a bare
#: `LOT-4471` with nothing saying it is a lot number is not the fact.
_LABELLED: dict[str, str] = {"lot": "Lot", "sold_between": "Sold between"}


def _html_associates(body: str, label: str, value: str) -> bool:
    """Is `value` in a table cell under the header carrying `label`?

    Checked STRUCTURALLY -- header column index against cell column index -- because in HTML
    that is what association means. An earlier version measured raw character distance with
    a 40-character window, and the correctly-rendered template failed it at 42: the gap is
    made of markup, not of separation. A threshold artifact reporting a good message as
    divergent is worse than no check at all.
    """
    rows = re.findall(r"<tr>(.*?)</tr>", body, flags=re.S)
    for index, row in enumerate(rows):
        headers = [h.strip() for h in re.findall(r"<th[^>]*>(.*?)</th>", row, flags=re.S)]
        if label not in headers:
            continue
        column = headers.index(label)
        for later in rows[index + 1 :]:
            cells = [c.strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", later, flags=re.S)]
            if column < len(cells) and cells[column] == value:
                return True
    return False


def _text_associates(body: str, label: str, value: str) -> bool:
    """Does `value` directly follow `label`, separated by nothing but a colon or spaces?

    Plain text has no structure to carry the association, so the only thing that can carry
    it is adjacency. An earlier version asked whether the two appeared on the same LINE,
    which the tag-stripping shortcut satisfies vacuously -- it collapses the whole document
    onto one line, so everything is on the same line as everything else and the check could
    not fail. That is the `all([])` trap wearing different clothes.
    """
    pattern = re.escape(label) + r"\s*:?\s*" + re.escape(value)
    return re.search(pattern, body) is not None


def _missing(body: str, notice: Notice) -> tuple[str, ...]:
    """Which facts are not recoverable from a rendered body.

    A value that appears with no indication of what it means does not count as present, and
    what counts as "with" differs by format -- column alignment in HTML, adjacency in text. The
    two are checked differently on purpose, rather than by one heuristic that suits neither.
    """
    is_html = "<html" in body.lower()
    missing = []
    for field, value in notice.facts.items():
        if value not in body:
            missing.append(field)
            continue
        if field in _LABELLED:
            label = _LABELLED[field]
            associated = (
                _html_associates(body, label, value)
                if is_html
                else _text_associates(body, label, value)
            )
            if not associated:
                missing.append(field)
    return tuple(missing)
