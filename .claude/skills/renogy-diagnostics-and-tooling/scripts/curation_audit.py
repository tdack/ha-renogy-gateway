#!/usr/bin/env python3
"""curation_audit.py — side-by-side curation drift report.

Compares the HA integration's curation constants (ha-renogy-gateway,
parsed with the `ast` module — exact) against the canonical sibling's
TypeScript curation (renogy-gateway, parsed with regex heuristics —
approximate). Pure stdlib, Python 3.10+.

Usage:
    python3 curation_audit.py <path-to-ha-renogy-gateway> <path-to-renogy-gateway>

Axes compared:
    force_readonly_leaves      discovery.py _FORCE_READONLY_LEAVES
                               vs core discovery.ts FORCE_READONLY_LEAVES
    force_readonly_suffixes    _FORCE_READONLY_SUFFIXES vs FORCE_READONLY_SUFFIXES
    force_readonly_by_ns       _FORCE_READONLY_LEAVES_BY_NAMESPACE vs FORCE_READONLY_BY_NS
    force_readonly_by_pid      _FORCE_READONLY_LEAVES_BY_PID vs params.ts
                               PARAM_FORCE_READONLY_BY_PID (TS entries are
                               "ns.leaf"; normalised to the bare leaf)
    hide_leaves                const.py HIDE_LEAVES vs params.ts PARAM_HIDE_LEAF
    diagnostic_patterns        const.py _DIAGNOSTIC_PATTERNS vs hass-bridge
                               filter.ts DEFAULT diagnosticPatterns
    skip_namespaces [info]     discovery.py _SKIP_NAMESPACES vs params.ts
                               PARAM_HIDE_NS — informational only: these two
                               sets have intentionally different scopes (HA
                               skips namespaces for the WHOLE entity pipeline;
                               TS hides them only from the Settings list), so
                               drift here does not affect the exit code.

Output is deterministic (sorted) and diff-friendly. Markers:
    =  present on both sides
    <  HA-only (ha-renogy-gateway)
    >  TS-only (renogy-gateway)

Exit codes: 0 = no drift on strict axes, 1 = drift found, 2 = parse failure.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Python side — exact, via ast
# ---------------------------------------------------------------------------


def _strings_in(node: ast.AST) -> set[str]:
    """All string constants anywhere under a node."""
    return {
        n.value
        for n in ast.walk(node)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    }


def _find_assign(tree: ast.Module, name: str) -> ast.AST | None:
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == name:
                    return node.value
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == name:
                return node.value
    return None


def py_set(path: Path, name: str) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    node = _find_assign(tree, name)
    if node is None:
        raise KeyError(f"{name} not found in {path}")
    return _strings_in(node)


def py_dict_of_sets(path: Path, name: str) -> dict[str, set[str]]:
    """Parse `NAME: dict[...] = {"key": frozenset({...}), ...}`."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    node = _find_assign(tree, name)
    if node is None:
        raise KeyError(f"{name} not found in {path}")
    out: dict[str, set[str]] = {}
    if isinstance(node, ast.Dict):
        for k, v in zip(node.keys, node.values):
            if isinstance(k, ast.Constant) and isinstance(k.value, str):
                out[k.value] = _strings_in(v)
    return out


# ---------------------------------------------------------------------------
# TypeScript side — heuristic, via regex + bracket matching
# ---------------------------------------------------------------------------

_QUOTED = re.compile(r"'([^']*)'|\"([^\"]*)\"")


def _quoted_strings(text: str) -> list[str]:
    return [a or b for a, b in _QUOTED.findall(text)]


def _bracket_block(text: str, start: int) -> str:
    """Return the substring from the bracket at `start` to its matching close.

    Heuristic: does not understand brackets inside string literals. Fine for
    the flat literal Sets/arrays/Records this script targets.
    """
    open_ch = text[start]
    close_ch = {"[": "]", "{": "}", "(": ")"}[open_ch]
    depth = 0
    for i in range(start, len(text)):
        if text[i] == open_ch:
            depth += 1
        elif text[i] == close_ch:
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    raise ValueError("unbalanced brackets")


def _const_block(text: str, name: str) -> str:
    m = re.search(rf"\bconst\s+{re.escape(name)}\b[^=]*=\s*", text)
    if not m:
        raise KeyError(f"const {name} not found")
    # Skip a leading constructor like `new Set(` to reach the literal.
    i = m.end()
    while text[i] not in "[{(":
        i += 1
    block = _bracket_block(text, i)
    if text[i] == "(":  # new Set([ ... ]) — recurse into the inner literal
        inner = block.find("[")
        if inner < 0:
            inner = block.find("{")
        block = _bracket_block(block, inner)
    return block


def ts_set(path: Path, name: str) -> set[str]:
    return set(_quoted_strings(_const_block(path.read_text(encoding="utf-8"), name)))


def ts_record_of_sets(path: Path, name: str) -> dict[str, set[str]]:
    """Parse `const NAME: Record<...> = { key: new Set([...]), ... }`."""
    block = _const_block(path.read_text(encoding="utf-8"), name)
    out: dict[str, set[str]] = {}
    for m in re.finditer(r"['\"]?([\w.]+)['\"]?\s*:\s*new Set\(", block):
        start = block.find("[", m.end() - 1)
        out[m.group(1)] = set(_quoted_strings(_bracket_block(block, start)))
    return out


def ts_array_field(path: Path, field: str) -> set[str]:
    """Parse `field: [ ...strings... ]` inside an object literal, unescaping
    TS string-literal backslashes so patterns compare 1:1 with Python raw
    strings ('\\\\.online$' in TS source == r'\\.online$' in Python)."""
    text = path.read_text(encoding="utf-8")
    m = re.search(rf"\b{re.escape(field)}\s*:\s*\[", text)
    if not m:
        raise KeyError(f"{field}: [...] not found in {path}")
    block = _bracket_block(text, m.end() - 1)
    return {s.replace("\\\\", "\\") for s in _quoted_strings(block)}


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def _pairs(d: dict[str, set[str]]) -> set[str]:
    return {f"{k}.{leaf.lower()}" for k, vs in d.items() for leaf in vs}


def _pid_pairs(d: dict[str, set[str]], strip_ns: bool) -> set[str]:
    out = set()
    for pid, leaves in d.items():
        for leaf in leaves:
            if strip_ns:
                leaf = leaf.rsplit(".", 1)[-1]
            out.add(f"{pid}:{leaf.lower()}")
    return out


def compare(title: str, ha: set[str], ts: set[str], info_only: bool = False) -> int:
    tag = " [informational]" if info_only else ""
    print(f"== {title}{tag} ==")
    both = sorted(ha & ts)
    ha_only = sorted(ha - ts)
    ts_only = sorted(ts - ha)
    for v in both:
        print(f"  = {v}")
    for v in ha_only:
        print(f"  < {v}   (HA only)")
    for v in ts_only:
        print(f"  > {v}   (TS only)")
    drift = len(ha_only) + len(ts_only)
    print(f"  -- both={len(both)} ha_only={len(ha_only)} ts_only={len(ts_only)}")
    print()
    return 0 if info_only else drift


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    ha_root = Path(sys.argv[1])
    ts_root = Path(sys.argv[2])

    ha_disc = ha_root / "custom_components/renogy_gateway/api/discovery.py"
    ha_const = ha_root / "custom_components/renogy_gateway/const.py"
    ts_disc = ts_root / "packages/core/src/discovery.ts"
    ts_params = ts_root / "packages/core/src/params.ts"
    ts_filter = ts_root / "apps/hass-bridge/src/filter.ts"

    for p in (ha_disc, ha_const, ts_disc, ts_params, ts_filter):
        if not p.is_file():
            print(f"ERROR: missing {p}", file=sys.stderr)
            return 2

    print("# Renogy curation drift report (HA integration vs canonical TS sibling)")
    print(f"# HA: {ha_root}")
    print(f"# TS: {ts_root}")
    print("# markers: '=' both, '<' HA-only, '>' TS-only")
    print()

    drift = 0
    try:
        drift += compare(
            "force_readonly_leaves (discovery.py vs core discovery.ts)",
            {s.lower() for s in py_set(ha_disc, "_FORCE_READONLY_LEAVES")},
            {s.lower() for s in ts_set(ts_disc, "FORCE_READONLY_LEAVES")},
        )
        drift += compare(
            "force_readonly_suffixes",
            {s.lower() for s in py_set(ha_disc, "_FORCE_READONLY_SUFFIXES")},
            {s.lower() for s in ts_set(ts_disc, "FORCE_READONLY_SUFFIXES")},
        )
        drift += compare(
            "force_readonly_by_namespace (ns.leaf pairs)",
            _pairs(py_dict_of_sets(ha_disc, "_FORCE_READONLY_LEAVES_BY_NAMESPACE")),
            _pairs(ts_record_of_sets(ts_disc, "FORCE_READONLY_BY_NS")),
        )
        drift += compare(
            "force_readonly_by_pid (pid:leaf pairs; TS 'ns.leaf' normalised to leaf)",
            _pid_pairs(
                py_dict_of_sets(ha_disc, "_FORCE_READONLY_LEAVES_BY_PID"), False
            ),
            _pid_pairs(
                ts_record_of_sets(ts_params, "PARAM_FORCE_READONLY_BY_PID"), True
            ),
        )
        drift += compare(
            "hide_leaves (const.py HIDE_LEAVES vs params.ts PARAM_HIDE_LEAF)",
            py_set(ha_const, "HIDE_LEAVES"),
            ts_set(ts_params, "PARAM_HIDE_LEAF"),
        )
        drift += compare(
            "diagnostic_patterns (const.py vs hass-bridge filter.ts defaults)",
            py_set(ha_const, "_DIAGNOSTIC_PATTERNS"),
            ts_array_field(ts_filter, "diagnosticPatterns"),
        )
        compare(
            "skip_namespaces (discovery.py _SKIP_NAMESPACES vs params.ts PARAM_HIDE_NS)",
            py_set(ha_disc, "_SKIP_NAMESPACES"),
            ts_set(ts_params, "PARAM_HIDE_NS"),
            info_only=True,
        )
    except (KeyError, ValueError, SyntaxError) as err:
        print(f"ERROR: {err}", file=sys.stderr)
        return 2

    print(f"TOTAL DRIFT (strict axes): {drift} entr{'y' if drift == 1 else 'ies'}")
    return 1 if drift else 0


if __name__ == "__main__":
    sys.exit(main())
