#!/usr/bin/env python3
"""Keep .claude-plugin/marketplace.json's skill list equal to skills/*/SKILL.md.

  python3 scripts/sync-marketplace.py          # rewrite the list
  python3 scripts/sync-marketplace.py --check  # exit 1 if it is stale (CI)
"""
import json
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
manifest_path = root / ".claude-plugin" / "marketplace.json"
manifest = json.loads(manifest_path.read_text())
wanted = [f"./skills/{p.parent.name}" for p in sorted(root.glob("skills/*/SKILL.md"))]
plugin = manifest["plugins"][0]
if plugin.get("skills") == wanted:
    print("marketplace skills list: up to date")
    sys.exit(0)
if "--check" in sys.argv:
    print("marketplace skills list is stale; run python3 scripts/sync-marketplace.py", file=sys.stderr)
    sys.exit(1)
plugin["skills"] = wanted
manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
print(f"marketplace skills list: updated ({len(wanted)} skills)")
