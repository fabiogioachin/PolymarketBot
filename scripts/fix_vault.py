"""Fix vault notes: remove empty sections, replace Dataview with real links."""

import json
import os
import re
import urllib.parse
import urllib.request

with open(os.path.expanduser("~/.claude/settings.json")) as f:
    data = json.load(f)
    KEY = data["mcpServers"]["obsidian"]["env"]["OBSIDIAN_API_KEY"]

BASE = "http://127.0.0.1:27123"


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


def list_dir(path: str) -> list[str]:
    encoded = urllib.parse.quote(path, safe="/")
    req = urllib.request.Request(
        f"{BASE}/vault/{encoded}",
        headers={"Authorization": f"Bearer {KEY}"},
    )
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        return json.loads(resp.read().decode()).get("files", [])
    except Exception:
        return []


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 1. Fix MOC — replace empty sections with real content
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print("=== Fixing MOC ===")

put_note("Projects/PolymarketBot/PolymarketBot.md", """\
---
type: project
status: active
repo: "https://github.com/fabiogioachin/PolymarketBot"
stack: [Python 3.11, FastAPI, Pydantic v2, httpx, aiosqlite, structlog]
created: 2026-04-04
---

# PolymarketBot

Bot autonomo di intelligence e trading su Polymarket. Il core e il [[Value Assessment]] Engine: stima fair value, rileva mispricing, esegue trades con simulazione realistica.

## Stato attuale
- 604 test, dashboard SSE real-time, Docker deploy
- 7 strategie, simulazione CLOB realistica con slippage
- Capitale: 150 EUR simulato, risk controls con limiti % equity
- Review completata 2026-04-05: 11 bug corretti, simulazione riscritta

## Architettura
Intelligence ([[GDELT]] + RSS + KG) alimenta il [[Value Assessment]] Engine (8 segnali pesati). L'engine produce edge = fair_value - market_price. Le [[Strategie Polymarket]] generano Signal. Il [[Position Sizing]] dimensiona. Il [[Circuit Breaker Pattern]] protegge.

## Decisioni
- [[Value Engine as Core]] — architettura centrata sul value engine
- [[Multi-leg Arbitrage]] — protocollo Signal list per trade multi-leg
- [[Daily Reset Architecture]] — reset automatico a mezzanotte UTC
- [[Realistic Dry-Run Simulation]] — simulazione che rispecchia la realta
- [[SSE Real-Time Dashboard]] — push unidirezionale vs polling
- [[Equity-Relative Risk Limits]] — limiti rischio in % dell'equity
- [[Accesso Polymarket da Italia]] — restrizioni geo e workaround
- [[Scelta Polymarket come Mercato]] — perche prediction markets

## Issues
- [[Review Bug Batch 2026-04-05]] — 11 bug critici trovati e corretti

## Tools
- [[Polymarket API]] — Gamma API + CLOB API

## Collegato a
- [[Strategie Polymarket]] — le 7 strategie di trading
- [[Value Assessment]] — il motore di valutazione (core)
- [[Prediction Markets]] — il mercato sottostante
- [[Circuit Breaker Pattern]] — protezione da drawdown
- [[Position Sizing]] — dimensionamento posizioni
- [[Token Bucket Rate Limiting]] — rate limiting API
- [[GDELT]] — intelligence pipeline
- [[Prediction Market Simulation]] — meccanica di simulazione realistica
""")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 2. Scan ALL notes for empty sections and fix
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print("\n=== Scanning for empty sections ===")

all_notes = []
def scan(path):
    items = list_dir(path)
    for item in items:
        full = path + item
        if item.endswith("/"):
            scan(full)
        elif item.endswith(".md"):
            all_notes.append(full)

scan("Projects/PolymarketBot/")
scan("Knowledge/Trading/")
scan("Knowledge/Tech/")

empty_section_notes = []
for path in all_notes:
    content = read_note(path)
    if not content:
        continue
    # Find ## headers followed immediately by another ## header or end of file
    lines = content.split("\n")
    for i, line in enumerate(lines):
        if line.startswith("## "):
            # Check if next non-empty line is another header or end
            j = i + 1
            while j < len(lines) and lines[j].strip() == "":
                j += 1
            if j >= len(lines) or lines[j].startswith("## ") or lines[j].startswith("---"):
                empty_section_notes.append((path, line.strip()))

if empty_section_notes:
    print(f"Found {len(empty_section_notes)} empty sections:")
    for path, section in empty_section_notes:
        name = path.rsplit("/", 1)[-1]
        print(f"  {name}: {section}")
else:
    print("No empty sections found.")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 3. Verify all links are bidirectional
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print("\n=== Checking bidirectional links ===")

name_to_path = {}
name_to_links = {}
for path in all_notes:
    name = path.rsplit("/", 1)[-1].replace(".md", "")
    name_to_path[name] = path
    content = read_note(path) or ""
    links = set(re.findall(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]", content))
    name_to_links[name] = links

missing_backlinks = []
for name, links in name_to_links.items():
    for target in links:
        if target in name_to_links:
            if name not in name_to_links[target]:
                missing_backlinks.append((name, target))

if missing_backlinks:
    print(f"Missing backlinks: {len(missing_backlinks)}")
    for src, tgt in missing_backlinks:
        print(f"  {src} -> [[{tgt}]] but {tgt} doesn't link back")
else:
    print("All links are bidirectional.")

print("\nDone!")
