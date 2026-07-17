#!/usr/bin/env python3
"""Confluence Cloud helper for the confluence-review skill. Stdlib only.

Credentials resolve through agent-skills' shared chain (dedicated store first,
Pegasus profile fallback) and are NEVER printed.

Key precedence:
  base url: PEI_CONFLUENCE_BASE_URL -> PEI_JIRA_BASE_URL (required; no default)
  email:    PEI_CONFLUENCE_USER_EMAIL -> PEI_JIRA_USER_EMAIL
  token:    PEI_CONFLUENCE_API_TOKEN -> PEI_JIRA_API_TOKEN

Subcommands:
  search "<text or CQL>" [--limit N]
  get <page-url-or-id>
  comments <page-url-or-id>
  post-comment <page-url-or-id> --report FILE [--reviewed-version N]
               [--allow-stale] [--repost]
  cleanup <page-id>
"""

import argparse
import base64
import hashlib
import html
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

_LIB = Path(__file__).resolve().parents[4] / "lib"
sys.path.insert(0, str(_LIB))
try:
    import env_resolve
except ImportError:  # pragma: no cover
    sys.exit(f"error: cannot import env_resolve from {_LIB}; "
             "is the skill symlinked from the agent-skills repo?")

WORK_ROOT = Path.home() / ".codex" / "tmp" / "confluence-review"
MARKER_PREFIX = "confluence-review"


def die(message, code=1):
    print(f"error: {message}", file=sys.stderr)
    sys.exit(code)


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class Confluence:
    def __init__(self):
        values, _ = env_resolve.resolve_all()
        base = (values.get("PEI_CONFLUENCE_BASE_URL")
                or values.get("PEI_JIRA_BASE_URL") or "").rstrip("/")
        if not base:
            die("no Atlassian base URL resolves; set PEI_CONFLUENCE_BASE_URL "
                "or PEI_JIRA_BASE_URL in the secrets store")
        if base.endswith("/wiki"):
            base = base[: -len("/wiki")]
        self.base = base
        email = (values.get("PEI_CONFLUENCE_USER_EMAIL")
                 or values.get("PEI_JIRA_USER_EMAIL"))
        token = (values.get("PEI_CONFLUENCE_API_TOKEN")
                 or values.get("PEI_JIRA_API_TOKEN"))
        if not email or not token:
            die("no Confluence credentials resolve "
                "(need PEI_CONFLUENCE_* or PEI_JIRA_* email+token); "
                "run 'bash doctor.sh' in the agent-skills repo")
        self._auth = base64.b64encode(f"{email}:{token}".encode()).decode()

    def request(self, method, path, payload=None):
        url = path if path.startswith("http") else f"{self.base}{path}"
        data = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(url, data=data, method=method)
        request.add_header("Authorization", f"Basic {self._auth}")
        request.add_header("Accept", "application/json")
        if data is not None:
            request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                body = response.read().decode("utf-8", "replace")
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as err:
            detail = err.read().decode("utf-8", "replace")[:400]
            die(f"HTTP {err.code} for {method} {url.split('?')[0]}: {detail}")
        except (urllib.error.URLError, OSError) as err:
            die(f"cannot reach Confluence: {getattr(err, 'reason', err)}")

    def get(self, path):
        return self.request("GET", path)

    def paged(self, path, key="results", cap=250):
        """Follow v2 cursor pagination via _links.next."""
        results, url = [], path
        while url and len(results) < cap:
            data = self.get(url)
            results.extend(data.get(key, []))
            nxt = (data.get("_links") or {}).get("next")
            url = nxt if nxt else None
        return results[:cap]


def parse_page_id(ref):
    ref = ref.strip()
    if ref.isdigit():
        return ref
    for pattern in (r"/pages/(\d+)", r"pageId=(\d+)"):
        match = re.search(pattern, ref)
        if match:
            return match.group(1)
    die(f"cannot extract a page id from {ref!r}; pass a numeric id or a "
        "/wiki/spaces/<SPACE>/pages/<id>/... URL, or use 'search' first")


# ---------------------------------------------------------------------------
# Storage XHTML -> Markdown
# ---------------------------------------------------------------------------

class StorageToMarkdown(HTMLParser):
    """Pragmatic Confluence storage-format -> Markdown converter.

    Imperfect nesting is acceptable — the output is review input, not a
    round-trip format. The raw storage XML is saved alongside for reference.
    """

    HEADINGS = {f"h{i}": i for i in range(1, 7)}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out = []
        self.bufs = [[]]
        self.list_stack = []       # ("ul"|"ol", counter)
        self.quote_depth = 0
        self.macro_stack = []      # {"name":, "params":{}, "body":[]}
        self.param_name = None
        self.href = []
        self.table = None          # {"rows": [...], "row": None}
        self.pre_depth = 0

    # -- buffer plumbing --
    def _buf(self):
        return self.bufs[-1]

    def _emit(self, text):
        self._buf().append(text)

    def _flush(self):
        text = "".join(self._buf()).strip()
        self.bufs[-1] = []
        if not text:
            return
        if self.quote_depth:
            text = "\n".join("> " * self.quote_depth + line
                             for line in text.splitlines())
        self.out.append(text)

    # -- macros --
    def _macro(self):
        return self.macro_stack[-1] if self.macro_stack else None

    def _in_code_macro(self):
        macro = self._macro()
        return macro is not None and macro["name"] in ("code", "noformat")

    # -- parser hooks --
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in self.HEADINGS:
            self._flush()
            self._emit("#" * self.HEADINGS[tag] + " ")
        elif tag == "p":
            if not self.table and not self.list_stack:
                self._flush()
        elif tag == "br":
            self._emit("\n")
        elif tag in ("strong", "b"):
            self._emit("**")
        elif tag in ("em", "i"):
            self._emit("*")
        elif tag in ("s", "del"):
            self._emit("~~")
        elif tag == "code" and not self.pre_depth:
            self._emit("`")
        elif tag == "pre":
            self._flush()
            self.pre_depth += 1
            self._emit("```\n")
        elif tag == "hr":
            self._flush()
            self.out.append("---")
        elif tag == "blockquote":
            self._flush()
            self.quote_depth += 1
        elif tag == "a":
            self.href.append(attrs.get("href", ""))
            self._emit("[")
        elif tag in ("ul", "ol"):
            if not self.list_stack:
                self._flush()
            self.list_stack.append([tag, 0])
        elif tag == "li":
            self._flush()
            depth = max(len(self.list_stack) - 1, 0)
            if self.list_stack and self.list_stack[-1][0] == "ol":
                self.list_stack[-1][1] += 1
                marker = f"{self.list_stack[-1][1]}."
            else:
                marker = "-"
            self._emit("  " * depth + marker + " ")
        elif tag == "table":
            self._flush()
            self.table = {"rows": []}
        elif tag == "tr" and self.table is not None:
            self.table["row"] = []
        elif tag in ("td", "th") and self.table is not None:
            self.bufs.append([])
        elif tag == "time":
            self._emit(attrs.get("datetime", ""))
        elif tag == "ac:structured-macro":
            self.macro_stack.append(
                {"name": attrs.get("ac:name", "?"), "params": {}, "body": []})
        elif tag == "ac:parameter":
            self.param_name = attrs.get("ac:name", "?")
            self.bufs.append([])
        elif tag == "ac:task-list":
            self._flush()
        elif tag == "ac:task":
            self._flush()
        elif tag == "ac:task-status":
            self.bufs.append([])
        elif tag == "ac:link" or tag == "ac:image":
            self.bufs.append([])
        elif tag == "ri:page":
            self._emit(f"[[{attrs.get('ri:content-title', 'page')}]]")
        elif tag == "ri:attachment":
            self._emit(f"(attachment: {attrs.get('ri:filename', '?')})")
        elif tag == "ri:user":
            self._emit("@user")
        elif tag == "ac:emoticon":
            self._emit(attrs.get("ac:emoji-fallback",
                                 attrs.get("ac:name", "")))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag in ("ri:page", "ri:attachment", "ri:user", "ac:emoticon",
                   "br", "hr", "time"):
            return
        self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag in self.HEADINGS or tag == "p":
            if not self.table and not self.list_stack:
                self._flush()
        elif tag in ("strong", "b"):
            self._emit("**")
        elif tag in ("em", "i"):
            self._emit("*")
        elif tag in ("s", "del"):
            self._emit("~~")
        elif tag == "code" and not self.pre_depth:
            self._emit("`")
        elif tag == "pre":
            self._emit("\n```")
            self.pre_depth = max(self.pre_depth - 1, 0)
            self._flush()
        elif tag == "blockquote":
            self._flush()
            self.quote_depth = max(self.quote_depth - 1, 0)
        elif tag == "a":
            href = self.href.pop() if self.href else ""
            self._emit(f"]({href})" if href else "]")
        elif tag in ("ul", "ol"):
            if self.list_stack:
                self.list_stack.pop()
            if not self.list_stack:
                self._flush()
        elif tag == "li":
            self._flush()
        elif tag in ("td", "th") and self.table is not None:
            cell = "".join(self.bufs.pop()).strip().replace("\n", " ")
            row = self.table.get("row")
            if row is not None:
                row.append(cell)
        elif tag == "tr" and self.table is not None:
            row = self.table.pop("row", None)
            if row:
                self.table["rows"].append(row)
        elif tag == "table":
            self._render_table()
        elif tag == "ac:structured-macro":
            self._render_macro(self.macro_stack.pop())
        elif tag == "ac:parameter":
            value = "".join(self.bufs.pop()).strip()
            if self._macro() is not None and self.param_name:
                self._macro()["params"][self.param_name] = value
            self.param_name = None
        elif tag == "ac:task-status":
            status = "".join(self.bufs.pop()).strip()
            self._emit("- [x] " if status == "complete" else "- [ ] ")
        elif tag == "ac:task":
            self._flush()
        elif tag == "ac:link":
            self._emit("".join(self.bufs.pop()).strip() or "[link]")
        elif tag == "ac:image":
            self._emit("!" + ("".join(self.bufs.pop()).strip() or "(image)"))

    def handle_data(self, data):
        macro = self._macro()
        if macro is not None and self._in_code_macro():
            macro["body"].append(data)
        else:
            self._emit(data)

    def unknown_decl(self, data):
        if data.startswith("CDATA["):
            content = data[len("CDATA["):]
            macro = self._macro()
            if macro is not None:
                macro["body"].append(content)
            else:
                self._emit(content)

    # -- renderers --
    def _render_table(self):
        rows = self.table["rows"] if self.table else []
        self.table = None
        if not rows:
            return
        width = max(len(r) for r in rows)
        rows = [r + [""] * (width - len(r)) for r in rows]
        lines = ["| " + " | ".join(rows[0]) + " |",
                 "|" + "---|" * width]
        lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
        self.out.append("\n".join(lines))

    def _render_macro(self, macro):
        name, params = macro["name"], macro["params"]
        body = "".join(macro["body"]).strip("\n")
        if name in ("code", "noformat"):
            lang = params.get("language", "")
            self._flush()
            self.out.append(f"```{lang}\n{body}\n```")
        elif name == "status":
            self._emit(f"[{params.get('title', 'STATUS').upper()}]")
        elif name in ("info", "note", "warning", "tip", "panel", "expand"):
            self._emit(f"\n**[{name}]** ")
        elif name == "toc":
            self._flush()
            self.out.append("*(table of contents macro)*")
        elif name == "jira":
            key = params.get("key", "")
            self._emit(f"[JIRA:{key}]" if key else "[JIRA macro]")
        else:
            self._emit(f" *(macro: {name})* ")

    def result(self):
        self._flush()
        return re.sub(r"\n{3,}", "\n\n", "\n\n".join(self.out)).strip() + "\n"


def storage_to_markdown(xhtml):
    parser = StorageToMarkdown()
    parser.feed(xhtml)
    return parser.result()


# ---------------------------------------------------------------------------
# Markdown -> storage XHTML (for posted comments; deliberately minimal)
# ---------------------------------------------------------------------------

def _md_inline(text):
    text = html.escape(text, quote=False)
    text = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)",
                  r'<a href="\2">\1</a>', text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    return text


def markdown_to_storage(markdown):
    blocks, lines = [], markdown.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("```"):
            fence = []
            i += 1
            while i < len(lines) and not lines[i].startswith("```"):
                fence.append(lines[i])
                i += 1
            body = "\n".join(fence)
            blocks.append(
                '<ac:structured-macro ac:name="code">'
                f'<ac:plain-text-body><![CDATA[{body}]]></ac:plain-text-body>'
                "</ac:structured-macro>")
        elif re.match(r"^#{1,6} ", line):
            level = len(line) - len(line.lstrip("#"))
            blocks.append(f"<h{level}>{_md_inline(line[level + 1:])}</h{level}>")
        elif re.match(r"^\s*[-*] ", line):
            items = []
            while i < len(lines) and re.match(r"^\s*[-*] ", lines[i]):
                items.append(f"<li>{_md_inline(lines[i].lstrip()[2:])}</li>")
                i += 1
            blocks.append(f"<ul>{''.join(items)}</ul>")
            continue
        elif re.match(r"^\s*\d+\. ", line):
            items = []
            while i < len(lines) and re.match(r"^\s*\d+\. ", lines[i]):
                items.append(
                    f"<li>{_md_inline(re.sub(r'^\\s*\\d+\\. ', '', lines[i]))}</li>")
                i += 1
            blocks.append(f"<ol>{''.join(items)}</ol>")
            continue
        elif line.strip() in ("---", "***"):
            blocks.append("<hr />")
        elif line.strip():
            para = [line]
            while i + 1 < len(lines) and lines[i + 1].strip() and \
                    not re.match(r"^(#{1,6} |```|\s*[-*] |\s*\d+\. |---$)", lines[i + 1]):
                i += 1
                para.append(lines[i])
            blocks.append(f"<p>{_md_inline(' '.join(para))}</p>")
        i += 1
    return "".join(blocks)


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

def cmd_search(client, query, limit):
    if re.search(r"[=~]", query):
        cql = query
    else:
        safe = query.replace('"', '\\"')
        cql = f'type = page AND (title ~ "{safe}" OR text ~ "{safe}")'
    data = client.get("/wiki/rest/api/search?"
                      + urllib.parse.urlencode({"cql": cql, "limit": limit}))
    results = data.get("results", [])
    if not results:
        print("NO_RESULTS")
        return
    for item in results:
        content = item.get("content") or {}
        space = (item.get("resultGlobalContainer") or {}).get("title", "?")
        url = client.base + "/wiki" + (item.get("url") or "")
        print(f"{content.get('id', '?')} | {content.get('title', item.get('title', '?'))} "
              f"| space={space} | modified={item.get('friendlyLastModified', '?')}")
        print(f"  {url}")


def fetch_page(client, page_id):
    return client.get(f"/wiki/api/v2/pages/{page_id}?body-format=storage")


def cmd_get(client, ref):
    page_id = parse_page_id(ref)
    page = fetch_page(client, page_id)
    version = page.get("version") or {}
    storage = ((page.get("body") or {}).get("storage") or {}).get("value", "")
    links = page.get("_links") or {}
    url = (links.get("base") or client.base + "/wiki") + (links.get("webui") or "")

    work = WORK_ROOT / page_id
    work.mkdir(parents=True, exist_ok=True)
    (work / "page.storage.xml").write_text(storage, encoding="utf-8")
    markdown = storage_to_markdown(storage)
    (work / "page.md").write_text(
        f"# {page.get('title', '?')}\n\n{markdown}", encoding="utf-8")

    children = client.paged(f"/wiki/api/v2/pages/{page_id}/children?limit=100")
    attachments = client.paged(f"/wiki/api/v2/pages/{page_id}/attachments?limit=100")

    meta = {
        "id": page_id,
        "title": page.get("title"),
        "space_id": page.get("spaceId"),
        "status": page.get("status"),
        "version": version.get("number"),
        "version_created_at": version.get("createdAt"),
        "url": url,
        "markdown_file": str(work / "page.md"),
        "storage_file": str(work / "page.storage.xml"),
        "children": [{"id": c.get("id"), "title": c.get("title")} for c in children],
        "attachments": [{"title": a.get("title"), "mediaType": a.get("mediaType")}
                        for a in attachments],
    }
    (work / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    print(f"PAGE_ID={page_id}")
    print(f"TITLE={meta['title']}")
    print(f"VERSION={meta['version']}")
    print(f"LAST_MODIFIED={meta['version_created_at']}")
    print(f"URL={url}")
    print(f"MARKDOWN_FILE={meta['markdown_file']}")
    print(f"STORAGE_FILE={meta['storage_file']}")
    print(f"META_FILE={work / 'meta.json'}")
    print(f"REPORT_FILE={WORK_ROOT / (page_id + '.review.md')}")
    print(f"CHILD_PAGES={len(children)}")
    for child in meta["children"][:25]:
        print(f"  child: {child['id']} | {child['title']}")
    print(f"ATTACHMENTS={len(attachments)}")
    for attachment in meta["attachments"][:25]:
        print(f"  attachment: {attachment['title']} ({attachment['mediaType']})")


def _iter_comments(client, page_id):
    for kind, path in (
        ("footer", f"/wiki/api/v2/pages/{page_id}/footer-comments"
                   "?body-format=storage&limit=100"),
        ("inline", f"/wiki/api/v2/pages/{page_id}/inline-comments"
                   "?body-format=storage&limit=100"),
    ):
        for comment in client.paged(path):
            yield kind, comment


def cmd_comments(client, ref):
    page_id = parse_page_id(ref)
    count = 0
    for kind, comment in _iter_comments(client, page_id):
        count += 1
        storage = ((comment.get("body") or {}).get("storage") or {}).get("value", "")
        created = (comment.get("version") or {}).get("createdAt", "?")
        selection = comment.get("properties", {}).get("inline-original-selection")
        print(f"--- {kind} comment {comment.get('id')} | created {created} "
              f"| status {comment.get('status', '?')}")
        if selection:
            print(f'    anchored to: "{selection}"')
        body = storage_to_markdown(storage).strip()
        print("    " + body.replace("\n", "\n    ") if body else "    (empty)")
    print(f"TOTAL_COMMENTS={count}")


def cmd_post_comment(client, ref, report_path, reviewed_version,
                     allow_stale, repost):
    page_id = parse_page_id(ref)
    report_file = Path(report_path)
    if not report_file.is_file():
        die(f"report file not found: {report_file}")
    report = report_file.read_text(encoding="utf-8").strip()
    if not report:
        die("report file is empty")

    if reviewed_version is None:
        meta_file = WORK_ROOT / page_id / "meta.json"
        if meta_file.is_file():
            reviewed_version = json.loads(
                meta_file.read_text(encoding="utf-8")).get("version")
    if reviewed_version is None and not allow_stale:
        die("cannot determine the reviewed page version; pass "
            "--reviewed-version N (from meta.json) or --allow-stale")

    live = fetch_page(client, page_id)
    live_version = (live.get("version") or {}).get("number")
    if reviewed_version is not None and live_version != reviewed_version:
        if not allow_stale:
            print(f"STALE_REVIEW reviewed_version={reviewed_version} "
                  f"live_version={live_version}")
            sys.exit(3)
        print(f"warning: posting stale review (reviewed v{reviewed_version}, "
              f"live v{live_version})", file=sys.stderr)

    digest = hashlib.sha256(report.encode()).hexdigest()[:8]
    marker = f"{MARKER_PREFIX} · page v{reviewed_version or '?'} · {digest}"
    if not repost:
        for _, comment in _iter_comments(client, page_id):
            storage = ((comment.get("body") or {}).get("storage") or {}).get("value", "")
            if marker in storage:
                print(f"SKIPPED_DUPLICATE comment_id={comment.get('id')}")
                return
    body = markdown_to_storage(report) + f"<p><em>{html.escape(marker)}</em></p>"
    created = client.request("POST", "/wiki/api/v2/footer-comments",
                             {"pageId": page_id,
                              "body": {"representation": "storage", "value": body}})
    print(f"POSTED_COMMENT_ID={created.get('id')}")


def cmd_cleanup(page_id):
    work = WORK_ROOT / page_id
    if work.is_dir():
        for path in sorted(work.rglob("*"), reverse=True):
            path.unlink() if path.is_file() else path.rmdir()
        work.rmdir()
        print(f"removed {work}")
    else:
        print(f"nothing to clean at {work}")
    review = WORK_ROOT / f"{page_id}.review.md"
    if review.is_file():
        print(f"kept review artifact {review}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("search")
    p.add_argument("query")
    p.add_argument("--limit", type=int, default=10)

    p = sub.add_parser("get")
    p.add_argument("ref")

    p = sub.add_parser("comments")
    p.add_argument("ref")

    p = sub.add_parser("post-comment")
    p.add_argument("ref")
    p.add_argument("--report", required=True)
    p.add_argument("--reviewed-version", type=int, default=None)
    p.add_argument("--allow-stale", action="store_true")
    p.add_argument("--repost", action="store_true")

    p = sub.add_parser("cleanup")
    p.add_argument("page_id")

    args = parser.parse_args()
    if args.command == "cleanup":
        cmd_cleanup(args.page_id)
        return
    client = Confluence()
    if args.command == "search":
        cmd_search(client, args.query, args.limit)
    elif args.command == "get":
        cmd_get(client, args.ref)
    elif args.command == "comments":
        cmd_comments(client, args.ref)
    elif args.command == "post-comment":
        cmd_post_comment(client, args.ref, args.report,
                         args.reviewed_version, args.allow_stale, args.repost)


if __name__ == "__main__":
    main()
