"""Fix missing backlinks in PolymarketBot hub notes."""

import json
import os
import re
import urllib.parse
import urllib.request

with open(os.path.expanduser("~/.claude/settings.json")) as f:
    data = json.load(f)
    KEY = data["mcpServers"]["obsidian"]["env"]["OBSIDIAN_API_KEY"]

BASE = "http://127.0.0.1:27123"


def read_note(path: str) -> str | None:
    encoded = urllib.parse.quote(path, safe="/")
    req = urllib.request.Request(
        f"{BASE}/vault/{encoded}",
        headers={"Authorization": f"Bearer {KEY}", "Accept": "text/markdown"},
    )
    try:
        return urllib.request.urlopen(req, timeout=10).read().decode()
    except Exception:
        return None


def put_note(path: str, content: str) -> None:
    encoded = urllib.parse.quote(path, safe="/")
    req = urllib.request.Request(
        f"{BASE}/vault/{encoded}",
        data=content.encode("utf-8"),
        method="PUT",
        headers={"Authorization": f"Bearer {KEY}", "Content-Type": "text/markdown"},
    )
    try:
        urllib.request.urlopen(req, timeout=10)
        print(f"  OK: {path}")
    except Exception as e:
        print(f"  FAIL: {path} -> {e}")


def add_backlinks(path: str, new_links: list[tuple[str, str]]) -> None:
    """Add missing links to Collegato a section. new_links = [(target, reason)]"""
    content = read_note(path)
    if not content:
        print(f"  SKIP (not found): {path}")
        return

    existing = set(re.findall(r"\[\[([^\]|]+)\]\]", content))
    to_add = [(t, r) for t, r in new_links if t not in existing]
    if not to_add:
        print(f"  SKIP (already linked): {path}")
        return

    lines = []
    for target, reason in to_add:
        lines.append(f"- [[{target}]] -- {reason}")

    addition = "\n".join(lines)

    if "## Collegato a" in content:
        content = content.rstrip() + "\n" + addition + "\n"
    else:
        content = content.rstrip() + "\n\n## Collegato a\n\n" + addition + "\n"

    put_note(path, content)


# ── Fix hub notes ────────────────────────────────────────

print("=== Fixing Value Assessment backlinks ===")
add_backlinks("Knowledge/Trading/Value Assessment.md", [
    ("GDELT", "alimenta il segnale event_signal"),
    ("Circuit Breaker Pattern", "il breaker reagisce ai risultati del value engine"),
    ("Multi-leg Arbitrage", "decisione architetturale che dipende dal value engine"),
    ("Realistic Dry-Run Simulation", "la simulazione usa l'output del value engine"),
    ("Review Bug Batch 2026-04-05", "bug trovati nel consumo dei risultati"),
    ("Value Engine as Core", "decisione di mettere il value engine al centro"),
])

print("\n=== Fixing Prediction Markets backlinks ===")
add_backlinks("Knowledge/Trading/Prediction Markets.md", [
    ("Polymarket API", "API di accesso al mercato"),
    ("Prediction Market Simulation", "come simulare prediction markets"),
    ("Realistic Dry-Run Simulation", "simulazione che rispecchia la meccanica reale"),
    ("Token Bucket Rate Limiting", "rate limiting sulle API del mercato"),
    ("GDELT", "intelligence che influenza i mercati"),
])

print("\n=== Fixing Position Sizing backlinks ===")
add_backlinks("Knowledge/Trading/Position Sizing.md", [
    ("PolymarketBot", "progetto che implementa questi algoritmi"),
    ("Daily Reset Architecture", "il daily reset azzera il P&L usato nel sizing"),
    ("Equity-Relative Risk Limits", "limiti in % dell'equity"),
    ("Prediction Market Simulation", "il sizing tiene conto dello slippage"),
    ("Realistic Dry-Run Simulation", "la simulazione usa il position sizing"),
])

print("\n=== Fixing Strategie Polymarket backlinks ===")
add_backlinks("Knowledge/Trading/Strategie Polymarket.md", [
    ("Multi-leg Arbitrage", "decisione per l'esecuzione two-legged"),
    ("Value Engine as Core", "il value engine alimenta tutte le strategie"),
    ("Scelta Polymarket come Mercato", "perche Polymarket rispetto ad alternative"),
])

print("\n=== Fixing Circuit Breaker Pattern backlinks ===")
add_backlinks("Knowledge/Tech/Circuit Breaker Pattern.md", [
    ("Daily Reset Architecture", "il breaker si resetta a mezzanotte"),
    ("Equity-Relative Risk Limits", "limiti complementari al circuit breaker"),
    ("Value Assessment", "il breaker non valuta edge, solo P&L"),
])

print("\n=== Fixing Token Bucket Rate Limiting backlinks ===")
add_backlinks("Knowledge/Tech/Token Bucket Rate Limiting.md", [
    ("Polymarket API", "rate limiting applicato alle API Polymarket"),
])

print("\n=== Fixing Scelta Polymarket backlinks ===")
add_backlinks("Projects/PolymarketBot/Decisions/Scelta Polymarket come Mercato.md", [
    ("Accesso Polymarket da Italia", "restrizioni geografiche"),
])

print("\nDone!")
