#!/usr/bin/env python3
"""Read a Jira issue or post an MR review comment without exposing credentials."""

import argparse
import base64
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from review_common import ensure_current_head


KEY_RE = re.compile(r"^[A-Z][A-Z0-9]+-\d+$")


def die(message):
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def _find_lib():
    """The repo's lib/ sits a few levels above this script when the skill is
    symlinked or installed with the whole repo; a copied-in skill has none."""
    for parent in Path(__file__).resolve().parents:
        if (parent / "lib" / "env_resolve.py").is_file():
            return parent / "lib"
    return None


def _clean_secret(name, value):
    if name.endswith(("_API_KEY", "_TOKEN", "_SECRET", "_KEY")):
        cleaned = value.encode("ascii", errors="ignore").decode("ascii")
        if cleaned != value:
            print(f"Warning: stripped non-ASCII characters from {name}", file=sys.stderr)
        return cleaned
    return value


def load_dotenv():
    """Resolve credentials through the agent-skills chain (secrets store,
    overlay fallbacks and aliases). $JIRA_ENV_FILE, when set, is loaded first
    and wins. A standalone copy without lib/ uses the process environment."""
    loaded = []
    configured = os.environ.get("JIRA_ENV_FILE")
    lib = _find_lib()
    if lib:
        sys.path.insert(0, str(lib))
        import env_resolve
        if configured:
            os.environ["AGENT_SECRETS_FILE"] = str(Path(configured).expanduser())
        values, provenance = env_resolve.resolve_all()
        for name, value in values.items():
            if provenance.get(name) != "process-env":
                os.environ[name] = _clean_secret(name, value)
        loaded = sorted({label for label in provenance.values() if label != "process-env"})
    return loaded


def first_env(*names):
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return None


class JiraClient:
    def __init__(self):
        self.env_file = load_dotenv()
        base_url = first_env("JIRA_BASE_URL", "JIRA_URL", "ATLASSIAN_BASE_URL")
        if not base_url:
            die("no Jira base URL resolves; set JIRA_BASE_URL in the secrets store")
        self.base_url = base_url.rstrip("/")
        token = first_env("JIRA_API_TOKEN", "JIRA_API_KEY", "ATLASSIAN_API_TOKEN")
        bearer = first_env("JIRA_BEARER_TOKEN", "ATLASSIAN_BEARER_TOKEN")
        email = first_env("JIRA_USER_EMAIL", "JIRA_EMAIL", "JIRA_USERNAME", "ATLASSIAN_EMAIL")

        if bearer:
            self.authorization = f"Bearer {bearer}"
            self.auth_mode = "bearer"
            self.secrets = (bearer,)
        elif token and email:
            encoded = base64.b64encode(f"{email}:{token}".encode()).decode()
            self.authorization = f"Basic {encoded}"
            self.auth_mode = "basic"
            self.secrets = (token, encoded)
        elif token:
            die("JIRA API token found, but no account email is configured; set JIRA_USER_EMAIL")
        else:
            die("set JIRA_USER_EMAIL and JIRA_API_TOKEN (or alias your own key names in the overlay's secrets.conf)")

    def request(self, method, path, payload=None):
        body = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=body,
            method=method,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Authorization": self.authorization,
                "User-Agent": "codex-mr-review/1.0",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                data = response.read()
                return json.loads(data) if data else {}
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")[:1000]
            for secret in self.secrets:
                detail = detail.replace(secret, "[REDACTED]")
            die(f"JIRA API returned HTTP {error.code} for {method} {path}: {detail}")
        except urllib.error.URLError as error:
            die(f"could not reach JIRA at {self.base_url}: {error.reason}")

    def issue(self, key):
        quoted = urllib.parse.quote(key, safe="")
        return self.request("GET", f"/rest/api/3/issue/{quoted}?fields=summary")

    def comments(self, key):
        quoted = urllib.parse.quote(key, safe="")
        start = 0
        comments = []
        while True:
            page = self.request(
                "GET",
                f"/rest/api/3/issue/{quoted}/comment?startAt={start}&maxResults=100",
            )
            values = page.get("comments", [])
            comments.extend(values)
            start += len(values)
            if not values or start >= page.get("total", start):
                return comments

    def add_comment(self, key, document):
        quoted = urllib.parse.quote(key, safe="")
        return self.request("POST", f"/rest/api/3/issue/{quoted}/comment", {"body": document})


def normalize_key(raw):
    key = raw.upper()
    if not KEY_RE.fullmatch(key):
        die(f"invalid JIRA issue key: {raw}")
    return key


def adf_text(value):
    if isinstance(value, dict):
        own = value.get("text", "")
        return own + "".join(adf_text(child) for child in value.get("content", []))
    if isinstance(value, list):
        return "".join(adf_text(item) for item in value)
    return ""


def text_node(text):
    return {"type": "text", "text": text}


def markdown_to_adf(markdown, title, mr_url, head_sha):
    content = []
    bullet_items = []

    def flush_bullets():
        if bullet_items:
            content.append({"type": "bulletList", "content": list(bullet_items)})
            bullet_items.clear()

    for raw_line in markdown.splitlines():
        line = raw_line.rstrip()
        if not line:
            flush_bullets()
            continue
        heading = re.match(r"^(#{1,6})\s+(.+)$", line)
        if heading:
            flush_bullets()
            content.append({
                "type": "heading",
                "attrs": {"level": min(len(heading.group(1)), 6)},
                "content": [text_node(heading.group(2))],
            })
        elif line.startswith("- "):
            bullet_items.append({
                "type": "listItem",
                "content": [{"type": "paragraph", "content": [text_node(line[2:])]}],
            })
        else:
            flush_bullets()
            content.append({"type": "paragraph", "content": [text_node(line)]})
    flush_bullets()

    if not content or content[0].get("type") != "heading":
        content.insert(0, {
            "type": "heading",
            "attrs": {"level": 2},
            "content": [text_node(f"MR Review — {title}")],
        })
    content[1:1] = [
        {"type": "paragraph", "content": [text_node(f"MR: {mr_url}")]},
        {"type": "paragraph", "content": [text_node(f"Head: {head_sha}")]},
    ]
    return {"type": "doc", "version": 1, "content": content}


def print_issue(client, key, issue):
    print(f"JIRA_KEY={key}")
    print(f"JIRA_SUMMARY={issue.get('fields', {}).get('summary', '')}")
    print(f"JIRA_URL={client.base_url}/browse/{key}")


def main():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    issue_parser = subparsers.add_parser("issue", help="verify an issue and print non-secret metadata")
    issue_parser.add_argument("key")
    post_parser = subparsers.add_parser("post", help="post a review report as an issue comment")
    post_parser.add_argument("key")
    post_parser.add_argument("--report", required=True)
    post_parser.add_argument("--mr-title", required=True)
    post_parser.add_argument("--mr-url", required=True)
    post_parser.add_argument("--head-sha", required=True)
    post_parser.add_argument("--repost", action="store_true")
    post_parser.add_argument("--allow-stale", action="store_true")
    args = parser.parse_args()

    key = normalize_key(args.key)
    report = None
    current_head = None
    if args.command == "post":
        report_path = Path(args.report)
        if not report_path.is_file():
            die(f"report file does not exist: {report_path}")
        report = report_path.read_text(encoding="utf-8")
        if not report.strip():
            die("report file is empty")
        _, _, current_head = ensure_current_head(
            args.mr_url, args.head_sha, allow_stale=args.allow_stale
        )

    client = JiraClient()
    issue = client.issue(key)
    print_issue(client, key, issue)
    if args.command == "issue":
        return

    short_sha = args.head_sha[:12]
    print(f"CURRENT_MR_HEAD={current_head}")
    if not args.repost:
        for comment in client.comments(key):
            existing = adf_text(comment.get("body", {}))
            if args.mr_url in existing and short_sha in existing:
                print(f"SKIPPED_DUPLICATE=comment:{comment.get('id', '')}")
                return

    document = markdown_to_adf(report, args.mr_title, args.mr_url, short_sha)
    comment = client.add_comment(key, document)
    print(f"POSTED_COMMENT_ID={comment.get('id', '')}")


if __name__ == "__main__":
    main()
