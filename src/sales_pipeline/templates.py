"""Email templates: loaded from templates.txt (or TEMPLATES_FILE) and rendered
with the customer's details. Missing placeholders render as empty text."""
from __future__ import annotations

import re
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

HEADER = re.compile(r"^===\s*(?P<key>[\w-]+)\s*(?:\|\s*(?P<label>.*?))?\s*===\s*$")
PLACEHOLDER_REPLY = "[write your reply here]"
FOLLOWUP_STAGES = 4


@dataclass
class Template:
    key: str
    label: str
    body: str


class _Blank(dict):
    def __missing__(self, key):
        return ""


def parse(text: str) -> dict[str, Template]:
    out: dict[str, Template] = {}
    key = label = None
    lines: list[str] = []

    def flush():
        if key:
            out[key] = Template(key, label or key, "\n".join(lines).strip("\n") + "\n")

    for raw in text.splitlines():
        m = HEADER.match(raw)
        if m:
            flush()
            key, label, lines = m.group("key"), m.group("label"), []
        elif key is not None:
            lines.append(raw)
        # lines before the first header (and '#' comments there) are ignored
    flush()
    return out


def load(path: str = "") -> dict[str, Template]:
    if path and Path(path).exists():
        text = Path(path).read_text(encoding="utf-8")
    else:
        text = resources.files(__package__).joinpath("templates.txt").read_text(encoding="utf-8")
    return parse(text)


def followup_variants(templates: dict[str, Template], n: int, quote_sent: bool) -> list[Template]:
    """All versions of follow-up n, the default first."""
    found = [t for k, t in templates.items() if re.fullmatch(rf"followup_{n}(?:[_a-z][_a-z0-9]*)?", k)]
    if n == 3:
        # The quote version only makes sense when a quote went out.
        found.sort(key=lambda t: (("quote" in t.key) != quote_sent, list(templates).index(t.key)))
    return found


def render(t: Template, **values) -> str:
    text = t.body.format_map(_Blank(values))
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + "\n"


def quote_block(previous: dict | None) -> str:
    """Gmail-style quote of the email being followed up."""
    if not previous or not previous.get("body"):
        return ""
    when = previous.get("date_label") or previous.get("date", "")
    who = previous.get("sender", "")
    quoted = "\n".join("> " + line if line else ">" for line in previous["body"].rstrip().splitlines())
    return f"\n\nOn {when}, {who} wrote:\n{quoted}\n"
