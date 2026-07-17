#!/usr/bin/env python3
"""Shared secrets resolution for agent-skills.

Resolution chain (first file wins per key, later files only fill gaps):
  1. $AGENT_SECRETS_FILE            (explicit override, loaded with override)
  2. ~/.config/agent-secrets/.env   (canonical dedicated store, loaded with override)
  3. ~/.hermes/profiles/pegasus/.env (per-key fallback, fills missing only)
  4. ~/.hermes/.env                  (per-key fallback, fills missing only)

Secret VALUES are never printed by anything in this module.

CLI:
  python3 env_resolve.py bootstrap            # create/fill the dedicated store from fallbacks
  python3 env_resolve.py doctor               # check every skill manifest + API reachability
  python3 env_resolve.py check KEY [KEY...]   # report PRESENT/MISSING (+source) for keys
"""

import base64
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEDICATED_ENV = Path.home() / ".config" / "agent-secrets" / ".env"
ENV_EXAMPLE = REPO_ROOT / "secrets" / ".env.example"
FALLBACK_ENV_FILES = (
    Path.home() / ".hermes" / "profiles" / "pegasus" / ".env",
    Path.home() / ".hermes" / ".env",
)

_LINE_RE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$")


def _parse_env_file(path):
    """Return {key: value} from a dotenv file. Tolerates comments/blank lines."""
    entries = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return entries
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = _LINE_RE.match(line)
        if not match:
            continue
        key, value = match.group(1), match.group(2).strip()
        if value and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        entries[key] = value
    return entries


def resolution_sources():
    """Ordered (label, path) pairs for the resolution chain."""
    sources = []
    configured = os.environ.get("AGENT_SECRETS_FILE")
    if configured:
        sources.append(("override:AGENT_SECRETS_FILE", Path(configured).expanduser()))
    sources.append(("dedicated", DEDICATED_ENV))
    sources.extend(
        (f"fallback:{p}", p) for p in FALLBACK_ENV_FILES
    )
    return sources


def resolve_all():
    """Resolve the full environment. Returns (values, provenance).

    values:     {key: value} with the chain's precedence applied
    provenance: {key: source_label}
    Existing os.environ values are treated as lowest-precedence defaults for
    keys no file defines, so shell exports still work.
    """
    values = {}
    provenance = {}
    for label, path in resolution_sources():
        if not path.is_file():
            continue
        for key, value in _parse_env_file(path).items():
            if not value:
                continue
            if key not in values:
                values[key] = value
                provenance[key] = label
    for key, value in os.environ.items():
        if key not in values and value:
            values[key] = value
            provenance[key] = "process-env"
    return values, provenance


def load_into_environ():
    """Apply the resolved chain to os.environ (files win over stale shell values
    for keys they define; shell-only keys are left untouched)."""
    values, provenance = resolve_all()
    for key, value in values.items():
        if provenance[key] != "process-env":
            os.environ[key] = value
    return values, provenance


def first_env(*names):
    values, _ = resolve_all()
    for name in names:
        value = values.get(name)
        if value:
            return value
    return None


# ---------------------------------------------------------------------------
# Manifest handling (restricted YAML subset — see codex/skills/*/manifest.yaml)
# ---------------------------------------------------------------------------

def parse_manifest(path):
    """Parse the restricted manifest schema:

        name: confluence-review
        secrets:
          required:
            - any_of: [A, B]
            - PLAIN_KEY
          optional: [C, D]

    Returns {"name": str, "required": [ [alternatives...] ], "optional": [keys]}.
    """
    required, optional = [], []
    name = path.parent.name
    section = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("name:"):
            name = stripped.split(":", 1)[1].strip()
        elif stripped.startswith("required:"):
            section = "required"
            inline = stripped.split(":", 1)[1].strip()
            if inline.startswith("["):
                required.extend([k] for k in _parse_inline_list(inline))
        elif stripped.startswith("optional:"):
            section = "optional"
            inline = stripped.split(":", 1)[1].strip()
            if inline.startswith("["):
                optional.extend(_parse_inline_list(inline))
        elif stripped.startswith("- any_of:") and section == "required":
            required.append(_parse_inline_list(stripped.split(":", 1)[1].strip()))
        elif stripped.startswith("- ") and section == "required":
            required.append([stripped[2:].strip()])
        elif stripped.startswith("- ") and section == "optional":
            optional.append(stripped[2:].strip())
    return {"name": name, "required": required, "optional": optional}


def _parse_inline_list(text):
    return [item.strip() for item in text.strip("[]").split(",") if item.strip()]


def skill_manifests():
    return sorted(REPO_ROOT.glob("codex/skills/*/manifest.yaml"))


# ---------------------------------------------------------------------------
# CLI subcommands
# ---------------------------------------------------------------------------

def _report_key(key, values, provenance):
    if values.get(key):
        return f"PRESENT (source: {provenance[key]})"
    return "MISSING"


def cmd_check(keys):
    values, provenance = resolve_all()
    ok = True
    for key in keys:
        status = _report_key(key, values, provenance)
        print(f"  {key}: {status}")
        ok = ok and status != "MISSING"
    return 0 if ok else 1


def cmd_bootstrap():
    """Create the dedicated store from .env.example, then fill empty keys from
    the fallback files. Only keys listed in .env.example are ever copied."""
    if not ENV_EXAMPLE.is_file():
        print(f"error: missing {ENV_EXAMPLE}", file=sys.stderr)
        return 1
    example_keys = list(_parse_env_file(ENV_EXAMPLE))
    # .env.example keys typically have empty values; capture key ORDER from the
    # raw file so the bootstrap output keeps the documented layout.
    ordered_keys = []
    for raw in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        match = _LINE_RE.match(raw.strip())
        if match and match.group(1) not in ordered_keys:
            ordered_keys.append(match.group(1))
    for key in example_keys:
        if key not in ordered_keys:
            ordered_keys.append(key)

    DEDICATED_ENV.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(DEDICATED_ENV.parent, 0o700)
    current = _parse_env_file(DEDICATED_ENV) if DEDICATED_ENV.is_file() else {}

    fallback = {}
    for path in FALLBACK_ENV_FILES:
        if path.is_file():
            for key, value in _parse_env_file(path).items():
                fallback.setdefault(key, value)

    copied, kept, empty = [], [], []
    lines = ["# agent-skills dedicated secrets store (chmod 600, never committed)",
             "# Bootstrapped from ~/.hermes/profiles/pegasus/.env; edit values freely.",
             ""]
    for key in ordered_keys:
        if current.get(key):
            lines.append(f"{key}={current[key]}")
            kept.append(key)
        elif fallback.get(key):
            lines.append(f"{key}={fallback[key]}")
            copied.append(key)
        else:
            lines.append(f"{key}=")
            empty.append(key)
    # Preserve any extra keys the user added to the dedicated file themselves.
    for key, value in current.items():
        if key not in ordered_keys and value:
            lines.append(f"{key}={value}")
            kept.append(key)

    DEDICATED_ENV.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.chmod(DEDICATED_ENV, 0o600)
    print(f"dedicated store: {DEDICATED_ENV}")
    print(f"  copied from fallback: {', '.join(copied) if copied else '(none)'}")
    print(f"  kept existing:        {', '.join(kept) if kept else '(none)'}")
    print(f"  still empty:          {', '.join(empty) if empty else '(none)'}")
    return 0


def _ping(url, email, token):
    request = urllib.request.Request(url)
    auth = base64.b64encode(f"{email}:{token}".encode()).decode()
    request.add_header("Authorization", f"Basic {auth}")
    request.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status
    except urllib.error.HTTPError as err:
        return err.code
    except (urllib.error.URLError, OSError) as err:
        return f"unreachable ({getattr(err, 'reason', err)})"


def cmd_doctor():
    values, provenance = resolve_all()
    failures = 0

    print("== secrets files ==")
    for label, path in resolution_sources():
        state = "found" if path.is_file() else "absent"
        print(f"  {label}: {path} [{state}]")

    print("== skill manifests ==")
    manifests = skill_manifests()
    if not manifests:
        print("  (no manifests found)")
    for manifest_path in manifests:
        manifest = parse_manifest(manifest_path)
        print(f"  [{manifest['name']}]")
        for group in manifest["required"]:
            satisfied = next((k for k in group if values.get(k)), None)
            if satisfied:
                print(f"    required {' | '.join(group)}: PRESENT via {satisfied} "
                      f"(source: {provenance[satisfied]})")
            else:
                print(f"    required {' | '.join(group)}: MISSING")
                failures += 1
        for key in manifest["optional"]:
            print(f"    optional {key}: {_report_key(key, values, provenance)}")

    print("== API reachability (status codes only) ==")
    email = values.get("PEI_CONFLUENCE_USER_EMAIL") or values.get("PEI_JIRA_USER_EMAIL")
    token = values.get("PEI_CONFLUENCE_API_TOKEN") or values.get("PEI_JIRA_API_TOKEN")
    base = (values.get("PEI_CONFLUENCE_BASE_URL") or values.get("PEI_JIRA_BASE_URL")
            or "https://peimedia.atlassian.net").rstrip("/")
    if email and token:
        status = _ping(f"{base}/wiki/api/v2/spaces?limit=1", email, token)
        print(f"  confluence {base}/wiki -> {status}")
        if status != 200:
            failures += 1
        status = _ping(f"{base}/rest/api/3/myself", email, token)
        print(f"  jira       {base} -> {status}")
        if status != 200:
            failures += 1
    else:
        print("  skipped: no Atlassian credentials resolve")
        failures += 1

    print(f"== result: {'OK' if not failures else f'{failures} problem(s)'} ==")
    return 0 if not failures else 1


def main(argv):
    if len(argv) >= 1 and argv[0] == "bootstrap":
        return cmd_bootstrap()
    if len(argv) >= 1 and argv[0] == "doctor":
        return cmd_doctor()
    if len(argv) >= 2 and argv[0] == "check":
        return cmd_check(argv[1:])
    print(__doc__.strip(), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
