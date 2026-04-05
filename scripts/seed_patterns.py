"""Generate seed pattern files for the Obsidian Knowledge Graph.

Usage:
    python scripts/seed_patterns.py [--vault-path PATH]
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.knowledge.pattern_templates import get_seed_patterns, render_pattern_markdown

DEFAULT_VAULT = "C:/Users/fgioa/OneDrive - SYNESIS CONSORTIUM/Desktop/PRO/_ObsidianKnowledge"


def seed_patterns(vault_path: str) -> int:
    """Write seed pattern Markdown files into the vault. Returns count of files written."""
    vault = Path(vault_path)
    patterns_dir = vault / "Projects/PolymarketBot/patterns"

    patterns = get_seed_patterns()
    count = 0

    for template in patterns:
        # Determine subdirectory by domain
        domain_dir = template.domain.capitalize()
        target_dir = patterns_dir / domain_dir
        target_dir.mkdir(parents=True, exist_ok=True)

        # Filename from pattern name
        safe_name = template.name.replace(" ", "_").replace("/", "-").replace(":", "")
        file_path = target_dir / f"{safe_name}.md"

        content = render_pattern_markdown(template)
        file_path.write_text(content, encoding="utf-8")
        count += 1
        print(f"  [{template.domain}] {template.name}")

    print(f"\nSeeded {count} patterns to {patterns_dir}")
    return count


def main() -> None:
    """Entry point for seed patterns script."""
    parser = argparse.ArgumentParser(description="Seed pattern files")
    parser.add_argument("--vault-path", type=str, default=DEFAULT_VAULT)
    args = parser.parse_args()
    seed_patterns(args.vault_path)


if __name__ == "__main__":
    main()
