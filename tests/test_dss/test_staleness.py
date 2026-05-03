"""Tests for the DSS staleness state decision function (`getStalenessState`).

The DSS dashboard (`static/dss/dss.js`) is vanilla JS served by nginx, so we can't
import it directly in pytest. Strategy:
  1. Static checks: read the JS source as a string and assert presence of the
     function, the threshold literals, level/color/icon strings, and `window`
     export.
  2. Behavioural checks: if `node` is on PATH, run the JS via `node -e` and
     assert the return values across all five levels and the boundaries
     (355, 360, 599, 600, 1799, 1800).

Spec (5 levels):
    age <  360       -> fresh    / green   / 🟢
    360 <= age < 600 -> aging    / yellow  / 🟡
    600 <= age <1800 -> stale    / orange  / 🟠
    age >= 1800      -> offline  / red     / 🔴
    age is None / negative / NaN -> unknown / gray / ⚪
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DSS_JS = ROOT / "static" / "dss" / "dss.js"


# ───────────────────── Static / source-level checks ─────────────────────


@pytest.fixture(scope="module")
def js_source() -> str:
    assert DSS_JS.is_file(), f"{DSS_JS} not found"
    return DSS_JS.read_text(encoding="utf-8")


def test_dss_js_exists() -> None:
    assert DSS_JS.is_file(), f"{DSS_JS} missing — frontend agent has not delivered yet"


def test_function_getStalenessState_is_defined(js_source: str) -> None:
    """Function must be declared as a plain function or arrow assignment."""
    patterns = [
        r"function\s+getStalenessState\s*\(",
        r"(?:const|let|var)\s+getStalenessState\s*=",
    ]
    assert any(re.search(p, js_source) for p in patterns), (
        "getStalenessState declaration not found in dss.js"
    )


def test_function_exposed_on_window(js_source: str) -> None:
    """Must be reachable as `window.getStalenessState` so external tests / DOM can use it."""
    assert re.search(r"window\.getStalenessState\s*=", js_source), (
        "window.getStalenessState assignment not found"
    )


@pytest.mark.parametrize("threshold", [360, 600, 1800])
def test_threshold_literals_present(js_source: str, threshold: int) -> None:
    """All three boundary thresholds (in seconds) must appear as literal numbers."""
    assert re.search(rf"\b{threshold}\b", js_source), (
        f"Threshold literal {threshold} not found in dss.js"
    )


@pytest.mark.parametrize("level", ["fresh", "aging", "stale", "offline", "unknown"])
def test_level_strings_present(js_source: str, level: int) -> None:
    pat = rf"['\"]{level}['\"]"
    assert re.search(pat, js_source), f"Level string '{level}' not found in dss.js"


@pytest.mark.parametrize("color", ["green", "yellow", "orange", "red", "gray"])
def test_color_strings_present(js_source: str, color: str) -> None:
    pat = rf"['\"]{color}['\"]"
    assert re.search(pat, js_source), f"Color string '{color}' not found in dss.js"


@pytest.mark.parametrize("icon", ["🟢", "🟡", "🟠", "🔴", "⚪"])
def test_icon_unicode_present(js_source: str, icon: str) -> None:
    assert icon in js_source, f"Icon {icon!r} not found in dss.js"


# ───────────────────── Behavioural checks via node ──────────────────────


NODE_RUNNER_TEMPLATE = r"""
{js}

// The IIFE pattern in dss.js may not leak getStalenessState into the global
// scope when evaluated via `node -e`, because `window` doesn't exist in node.
// We provide a `window` shim BEFORE the source is loaded, so the
// `window.getStalenessState = ...` line attaches the function to our shim.
"""


_BROWSER_SHIM = r"""
// Minimal browser-environment shim so dss.js can be evaluated under node.
globalThis.window = globalThis;
globalThis.document = {
  readyState: "complete",
  addEventListener: () => {},
  getElementById: () => null,
  querySelector: () => null,
  querySelectorAll: () => [],
  createElement: () => ({
    appendChild: () => {},
    addEventListener: () => {},
    setAttribute: () => {},
    classList: { add: () => {}, remove: () => {}, toggle: () => {} },
    style: {},
  }),
};
globalThis.localStorage = {
  _d: {},
  getItem(k) { return this._d[k] ?? null; },
  setItem(k, v) { this._d[k] = String(v); },
  removeItem(k) { delete this._d[k]; },
};
// Suppress timers/network — tests only care about getStalenessState.
const _origSetInterval = globalThis.setInterval;
globalThis.setInterval = () => 0;
globalThis.setTimeout = () => 0;
globalThis.fetch = () => Promise.reject(new Error("fetch disabled in test shim"));
globalThis.WebSocket = function () { this.close = () => {}; };
"""


def _build_runner(js: str, body: str) -> str:
    """Wrap the JS source so `window`/`document` exist and we can read window.getStalenessState."""
    return (
        _BROWSER_SHIM
        + "\n"
        + js
        + "\n"
        + "const fn = (typeof window !== 'undefined' && window.getStalenessState)\n"
        + "  || globalThis.getStalenessState;\n"
        + "if (typeof fn !== 'function') {\n"
        + "  console.error('NO_FUNCTION'); process.exit(2);\n"
        + "}\n"
        + body
    )


def _run_node(js: str, body: str) -> str:
    runner = _build_runner(js, body)
    proc = subprocess.run(  # noqa: S603
        ["node", "-e", runner],  # noqa: S607
        capture_output=True,
        text=True,
        timeout=10,
        encoding="utf-8",
    )
    if proc.returncode != 0:
        raise AssertionError(
            f"node exited {proc.returncode}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )
    return proc.stdout.strip()


@pytest.fixture(scope="module")
def node_available() -> bool:
    return shutil.which("node") is not None


def test_getStalenessState_levels_via_node(js_source: str, node_available: bool) -> None:
    """Every level + every boundary returns the expected level string."""
    if not node_available:
        pytest.skip("node not installed — JS unit test skipped")

    body = r"""
const cases = {
  fresh_low:    fn(0).level,
  fresh_mid:    fn(60).level,
  fresh_b_hi:   fn(355).level,
  fresh_b_359:  fn(359).level,
  aging_b_lo:   fn(360).level,
  aging_mid:    fn(500).level,
  aging_b_hi:   fn(599).level,
  stale_b_lo:   fn(600).level,
  stale_mid:    fn(1200).level,
  stale_b_hi:   fn(1799).level,
  offline_b_lo: fn(1800).level,
  offline_far:  fn(99999).level,
  unknown_null: fn(null).level,
  unknown_undef:fn(undefined).level,
  unknown_neg:  fn(-5).level,
};
// NaN is not in the spec — implementations may map it to either 'unknown'
// (treat as missing) or 'offline' (treat as ancient). We don't assert on it.

console.log(JSON.stringify(cases));
"""
    out = _run_node(js_source, body)
    last = out.splitlines()[-1]
    res = json.loads(last)

    assert res["fresh_low"] == "fresh"
    assert res["fresh_mid"] == "fresh"
    assert res["fresh_b_hi"] == "fresh"
    assert res["fresh_b_359"] == "fresh"
    assert res["aging_b_lo"] == "aging"
    assert res["aging_mid"] == "aging"
    assert res["aging_b_hi"] == "aging"
    assert res["stale_b_lo"] == "stale"
    assert res["stale_mid"] == "stale"
    assert res["stale_b_hi"] == "stale"
    assert res["offline_b_lo"] == "offline"
    assert res["offline_far"] == "offline"
    assert res["unknown_null"] == "unknown"
    assert res["unknown_undef"] == "unknown"
    assert res["unknown_neg"] == "unknown"


def test_getStalenessState_colors_via_node(js_source: str, node_available: bool) -> None:
    if not node_available:
        pytest.skip("node not installed — JS unit test skipped")

    body = r"""
console.log(JSON.stringify({
  fresh:   fn(60).color,
  aging:   fn(360).color,
  stale:   fn(600).color,
  offline: fn(1800).color,
  unknown: fn(null).color,
}));
"""
    out = _run_node(js_source, body)
    res = json.loads(out.splitlines()[-1])
    assert res["fresh"] == "green"
    assert res["aging"] == "yellow"
    assert res["stale"] == "orange"
    assert res["offline"] == "red"
    assert res["unknown"] == "gray"


def test_getStalenessState_icons_via_node(js_source: str, node_available: bool) -> None:
    if not node_available:
        pytest.skip("node not installed — JS unit test skipped")

    body = r"""
console.log(JSON.stringify({
  fresh:   fn(60).icon,
  aging:   fn(360).icon,
  stale:   fn(600).icon,
  offline: fn(1800).icon,
  unknown: fn(null).icon,
}));
"""
    out = _run_node(js_source, body)
    res = json.loads(out.splitlines()[-1])
    assert res["fresh"] == "🟢"
    assert res["aging"] == "🟡"
    assert res["stale"] == "🟠"
    assert res["offline"] == "🔴"
    assert res["unknown"] == "⚪"


def test_getStalenessState_returns_label_with_age(
    js_source: str, node_available: bool
) -> None:
    """Label must be a non-empty string; for known levels it should mention the age."""
    if not node_available:
        pytest.skip("node not installed — JS unit test skipped")

    body = r"""
console.log(JSON.stringify({
  fresh:   fn(60).label,
  aging:   fn(360).label,
  stale:   fn(600).label,
  offline: fn(1800).label,
  unknown: fn(null).label,
}));
"""
    out = _run_node(js_source, body)
    res = json.loads(out.splitlines()[-1])
    for key, label in res.items():
        assert isinstance(label, str) and label, f"label for {key} is not a non-empty string"
    # Non-unknown labels should contain at least one digit (the age)
    for key in ("fresh", "aging", "stale", "offline"):
        assert re.search(r"\d", res[key]), (
            f"label for {key} should include a numeric age, got: {res[key]!r}"
        )


def test_getStalenessState_return_shape_via_node(
    js_source: str, node_available: bool
) -> None:
    """Return object MUST have keys: level, label, color, icon."""
    if not node_available:
        pytest.skip("node not installed — JS unit test skipped")

    body = r"""
const r = fn(60);
console.log(JSON.stringify({
  keys: Object.keys(r).sort(),
  types: {
    level: typeof r.level,
    label: typeof r.label,
    color: typeof r.color,
    icon:  typeof r.icon,
  }
}));
"""
    out = _run_node(js_source, body)
    res = json.loads(out.splitlines()[-1])
    assert set(res["keys"]) >= {"color", "icon", "label", "level"}, (
        f"return shape missing required keys: got {res['keys']}"
    )
    assert res["types"] == {
        "level": "string",
        "label": "string",
        "color": "string",
        "icon": "string",
    }
