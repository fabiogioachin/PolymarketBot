"""Set up Obsidian vault structure for PolymarketBot knowledge graph.

Usage:
    python scripts/setup_vault.py [--vault-path PATH]
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

DEFAULT_VAULT = "C:/Users/fgioa/OneDrive - SYNESIS CONSORTIUM/Desktop/PRO/_ObsidianKnowledge"

DIRECTORIES = [
    "Projects/PolymarketBot",
    "Projects/PolymarketBot/patterns",
    "Projects/PolymarketBot/patterns/Geopolitics",
    "Projects/PolymarketBot/patterns/Politics",
    "Projects/PolymarketBot/patterns/Economics",
    "Projects/PolymarketBot/patterns/Crypto",
    "Projects/PolymarketBot/patterns/Sports",
    "Projects/PolymarketBot/patterns/StandBy",
    "Projects/PolymarketBot/Markets",
    "Projects/PolymarketBot/Events",
    "Knowledge/Patterns/Geopolitics",
    "Knowledge/Patterns/Politics",
    "Knowledge/Patterns/Economics",
    "Knowledge/Patterns/Crypto",
    "Knowledge/Patterns/Sports",
    "Knowledge/Patterns/StandBy",
]


def setup_vault(vault_path: str) -> None:
    """Create the vault directory structure for PolymarketBot."""
    vault = Path(vault_path)

    for dir_path in DIRECTORIES:
        full_path = vault / dir_path
        full_path.mkdir(parents=True, exist_ok=True)
        print(f"  Created: {dir_path}/")

    # Create MOC (Map of Content)
    moc_path = vault / "Projects/PolymarketBot/PolymarketBot.md"
    if not moc_path.exists():
        moc_content = """---
type: project
status: active
---

# PolymarketBot

Autonomous intelligence + value assessment system for Polymarket prediction markets.

## Structure
- [[patterns/]] — Trading patterns by domain
- [[Markets/]] — Per-market analysis notes
- [[Events/]] — Significant events log

## Domains
- [[patterns/Geopolitics/]] — Geopolitical patterns
- [[patterns/Politics/]] — Political patterns
- [[patterns/Economics/]] — Economic patterns
- [[patterns/Crypto/]] — Cryptocurrency patterns
- [[patterns/Sports/]] — Sports patterns

## Links
- Architecture: Value Assessment Engine → Strategy Layer → Execution
- Risk: Fixed fraction 5%, max exposure 50%, circuit breaker
"""
        moc_path.write_text(moc_content, encoding="utf-8")
        print("  Created: PolymarketBot.md (MOC)")

    print(f"\nVault structure ready at: {vault_path}")


def main() -> None:
    """Entry point for vault setup script."""
    parser = argparse.ArgumentParser(description="Set up Obsidian vault structure")
    parser.add_argument("--vault-path", type=str, default=DEFAULT_VAULT)
    args = parser.parse_args()
    setup_vault(args.vault_path)


if __name__ == "__main__":
    main()
