"""Tests for the DSS staleness CSS classes (`static/dss/dss.css`).

The decisore staleness pipeline drives a banner with five visual states. Each
state has a dedicated CSS class — `.banner-{level}` — and the `offline`
state must pulse red, which requires a `@keyframes pulse-red` animation.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DSS_CSS = ROOT / "static" / "dss" / "dss.css"


@pytest.fixture(scope="module")
def css_source() -> str:
    assert DSS_CSS.is_file(), f"{DSS_CSS} not found"
    return DSS_CSS.read_text(encoding="utf-8")


def test_dss_css_exists() -> None:
    assert DSS_CSS.is_file(), f"{DSS_CSS} missing — frontend agent has not delivered yet"


@pytest.mark.parametrize(
    "level", ["fresh", "aging", "stale", "offline", "unknown"]
)
def test_banner_class_present(css_source: str, level: str) -> None:
    """All five `.banner-{level}` selectors must be defined."""
    pat = rf"\.banner-{level}\b"
    assert re.search(pat, css_source), f".banner-{level} class not found in dss.css"


def test_keyframes_pulse_red_defined(css_source: str) -> None:
    """The `offline` banner must pulse red — requires a `@keyframes pulse-red` animation."""
    # Allow vendor prefix or whitespace variations.
    pat = r"@(?:-webkit-)?keyframes\s+pulse-red\b"
    assert re.search(pat, css_source), (
        "@keyframes pulse-red not found in dss.css — required for offline banner pulse"
    )


def test_offline_banner_uses_pulse_red(css_source: str) -> None:
    """The `.banner-offline` rule should reference the `pulse-red` animation."""
    # Find the .banner-offline block (rough match — non-nested CSS).
    block_match = re.search(
        r"\.banner-offline\b[^{]*\{([^}]*)\}", css_source, flags=re.DOTALL
    )
    assert block_match, ".banner-offline rule body not found"
    body = block_match.group(1)
    assert "pulse-red" in body, (
        ".banner-offline must reference the pulse-red animation "
        f"(found block body: {body!r})"
    )
