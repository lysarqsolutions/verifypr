"""Load prompt templates and build untrusted-data blocks safely.

Public interface: ``load_prompt(name)``, ``render(name, **values)``, ``escape_untrusted``,
``untrusted(tag, text, **attrs)``.

Prompts live in ``verifypr/prompts/*.md`` (versioned in their first line), never inline.
Anything from the repository goes inside ``<untrusted_*>`` tags; any text that could close
or open such a tag is neutralised so it can't break out of the data block.
"""

from __future__ import annotations

import re
from functools import cache
from importlib import resources

_TAG_BREAKOUT = re.compile(r"<(/?)(\s*untrusted)", re.IGNORECASE)
_PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")


@cache
def load_prompt(name: str) -> str:
    return (resources.files("verifypr") / "prompts" / f"{name}.md").read_text(encoding="utf-8")


def render(name: str, **values: str) -> str:
    template = load_prompt(name)

    def fill(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in values:
            raise KeyError(f"prompt {name} needs {{{{{key}}}}}")
        return values[key]

    return _PLACEHOLDER.sub(fill, template)


def escape_untrusted(text: str) -> str:
    """Neutralise anything that looks like an ``untrusted`` tag so data can't close its block."""
    return _TAG_BREAKOUT.sub(lambda m: f"&lt;{m.group(1)}{m.group(2)}", text)


def _attr(value: str) -> str:
    return escape_untrusted(value).replace('"', "&quot;").replace("\n", " ")


def untrusted(tag: str, text: str, **attrs: str) -> str:
    rendered = "".join(f' {k}="{_attr(v)}"' for k, v in attrs.items())
    return f"<untrusted_{tag}{rendered}>\n{escape_untrusted(text)}\n</untrusted_{tag}>"
