"""Generate the recipient list. Deterministic, so every figure in the docs is reproducible.

Each planted row exists because some claim in this project needs a case to be true of. The
manifest at the bottom is asserted against by a test, so a row cannot quietly stop doing its
job.
"""

from __future__ import annotations

import csv
from pathlib import Path

OUT = Path(__file__).parent / "recipients.csv"

#: (address, name, lot, why this row is here)
ROWS: list[tuple[str, str, str, str]] = [
    # -- ordinary rows, so the awkward ones are a minority as they would be in real life --
    ("alice.tan@example.com", "Alice Tan", "LOT-4471", "plain"),
    ("bmehta@example.net", "Bhavna Mehta", "LOT-4471", "plain"),
    ("c.okafor@example.org", "Chidi Okafor", "LOT-4471", "plain"),
    ("dlindqvist@example.se", "Dag Lindqvist", "LOT-4472", "plain"),
    ("e.rossi@example.it", "Elena Rossi", "LOT-4471", "plain"),
    ("f.dubois@example.fr", "Francois Dubois", "LOT-4472", "plain"),
    ("g.nakamura@example.jp", "Goro Nakamura", "LOT-4471", "plain"),
    ("hsingh@example.in", "Harpreet Singh", "LOT-4472", "plain"),
    ("i.kovacs@example.hu", "Ilona Kovacs", "LOT-4471", "plain"),
    ("jwalsh@example.ie", "Jim Walsh", "LOT-4471", "plain"),
    ("k.mueller@example.de", "Klaus Mueller", "LOT-4472", "plain"),
    ("lmorales@example.mx", "Lucia Morales", "LOT-4471", "plain"),
    # -- case variants: RFC 5321 2.4 says the local part is case-SENSITIVE, so whether
    #    these are one person or two is a policy decision and not a fact --
    ("Nadia.Farouk@example.com", "Nadia Farouk", "LOT-4471", "case variant A"),
    ("nadia.farouk@example.com", "Nadia Farouk", "LOT-4471", "case variant B"),
    ("NADIA.FAROUK@EXAMPLE.COM", "N Farouk", "LOT-4471", "case variant C, domain too"),
    # -- gmail dot and +tag folding: provider behaviour, no RFC sanction, invisible in the
    #    string. All four of these reach one mailbox --
    ("o.brien.sean@gmail.com", "Sean O'Brien", "LOT-4472", "gmail dots"),
    ("obriensean@gmail.com", "Sean O'Brien", "LOT-4472", "gmail no dots, same mailbox"),
    ("obriensean+recall@gmail.com", "S O'Brien", "LOT-4472", "gmail +tag, same mailbox"),
    ("o.brien.sean+2026@gmail.com", "Sean OB", "LOT-4472", "gmail dots AND +tag"),
    # -- a non-folding domain with the same shape, where those dots ARE significant --
    ("p.reyes@example.ph", "Paolo Reyes", "LOT-4471", "dots on a non-folding domain"),
    ("preyes@example.ph", "Priya Reyes", "LOT-4471", "different person, same folded key"),
    # -- comments: valid RFC 5322, semantically transparent, and parseaddr silently strips
    #    them so the mailbox delivered to is not the string supplied --
    ("quentin(work)@example.com", "Quentin Blake", "LOT-4472", "comment, depth 1"),
    ("rosa((home))@example.com", "Rosa Diaz", "LOT-4471", "comment, depth 2"),
    # -- the getaddresses bomb: one row, one person, TWO recipients out, one of them a
    #    surname. parseaddr returns nothing at all for the same string --
    ("Sato, Kenji <k.sato@example.jp>", "Kenji Sato", "LOT-4471", "comma in display name"),
    # -- valid addresses that shipped validators refuse. Each one is a customer who would
    #    not be told --
    ('"tomas nunez"@example.es', "Tomas Nunez", "LOT-4472", "quoted local part with a space"),
    ("u.chen@[203.0.113.9]", "Uma Chen", "LOT-4471", "RFC 5321 4.1.3 address literal"),
    # -- a string that is not an address at all, which parseaddr hands back unchanged --
    ("victor-no-at-sign", "Victor Hugo", "LOT-4472", "no @ anywhere"),
    # -- an exact duplicate, so suppression has something to suppress under every policy --
    ("alice.tan@example.com", "Alice Tan", "LOT-4471", "exact duplicate of row 1"),
    # -- role addresses: one mailbox, many readers, and nothing says so --
    ("safety@example.coop", "Safety Desk", "LOT-4471", "role address, unknown readership"),
]

#: What each row is here to prove. Asserted against by the corpus test so that a row cannot
#: stop exercising its case without something failing.
PLANTED: dict[str, str] = {
    "Nadia.Farouk@example.com": "case variant",
    "o.brien.sean@gmail.com": "gmail folding",
    "quentin(work)@example.com": "comment depth 1",
    "rosa((home))@example.com": "comment depth 2",
    "Sato, Kenji <k.sato@example.jp>": "getaddresses invents a recipient",
    '"tomas nunez"@example.es': "quoted local part",
    "u.chen@[203.0.113.9]": "address literal, dropped by parseaddr",
    "victor-no-at-sign": "no @, accepted by parseaddr anyway",
    "safety@example.coop": "role address",
}


def main() -> None:
    with OUT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["address", "name", "lot", "note"])
        for address, name, lot, note in ROWS:
            writer.writerow([address, name, lot, note])
    print(f"wrote {len(ROWS)} rows to {OUT}")


if __name__ == "__main__":
    main()
