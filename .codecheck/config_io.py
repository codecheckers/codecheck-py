"""
Writing fields of `codecheck.yml` while keeping its comments, order, quotes and indentation (`ruamel.yaml`)
"""

import io
import re
from typing import Dict, Optional, Tuple

import yaml

INDENT_CANDIDATES = ((2, 0), (2, 2), (4, 0), (4, 2), (4, 4))  # (mapping indent, offset of the `-` of list items)


def _guess_indent(text: str) -> Tuple[int, int]:
    """
    (mapping indent, offset of the `-` of list items) of a YAML file, from the first nested mapping and list; default
    (2, 0). `ruamel.yaml.util.load_yaml_guess_indent` looks at the first nested block only and mixes both.
    """
    mapping = offset = None
    parent = None  # indentation of the last `key:` without value
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "%")) or stripped == "---":
            continue
        indent = len(line) - len(line.lstrip(" "))
        if parent is not None and indent > parent:
            if stripped.startswith("- ") and offset is None:
                offset = indent - parent
            elif not stripped.startswith("- ") and mapping is None:
                mapping = indent - parent
        parent = indent if re.match(r"^[^#'\"]*:\s*(#.*)?$", stripped) and not stripped.startswith("- ") else None
        if mapping is not None and offset is not None:
            break
    return mapping or 2, offset or 0


def _yaml(mapping: int, offset: int):
    from ruamel.yaml import YAML

    rt = YAML()  # round-trip, without folding long lines
    rt.preserve_quotes = True
    rt.width = 4096
    rt.indent(mapping=mapping, sequence=offset + 2, offset=offset)
    return rt


def _dump(rt, data) -> str:
    out = io.StringIO()
    rt.dump(data, out)
    return out.getvalue()


def _round_trip(text: str):
    """(YAML instance, data) whose unchanged dump is the text, else for the guessed indentation."""
    guess = _guess_indent(text)
    for indent in (guess,) + tuple(c for c in INDENT_CANDIDATES if c != guess):
        rt = _yaml(*indent)
        data = rt.load(text)
        if data is None or _dump(rt, data) == text:
            return rt, data
    rt = _yaml(*guess)  # no candidate reproduces the file (unusual formatting): it is re-indented
    return rt, rt.load(text)


def write_config_fields(path, updates: Dict, section: Optional[str] = None) -> Dict:
    """
    Set top-level fields (or `<section>.<key>`) in a `codecheck.yml` for the updates, keeping comments, order, quotes
    and indentation, and return the new configuration. Nothing is written if the YAML cannot be processed.
    """
    with open(path) as f:
        text = f.read()
    rt, data = _round_trip(text)
    if data is None:  # empty file
        data = rt.load("{}")
    target = data
    if section:
        if not isinstance(data.get(section), dict):
            data[section] = {}
        target = data[section]
    target.update(updates)
    result = _dump(rt, data)  # fails before the file is touched
    with open(path, "w") as f:
        f.write(result)
    return yaml.safe_load(result)
