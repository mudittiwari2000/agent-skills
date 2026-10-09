"""Markdown -> Confluence storage XHTML, plus a few page conventions (author panel, mention, live Jira macro).

usage: md2cf.py <in.md> <out.html> <author_panel_text> [diagram1.png,diagram2.png,...]
  The optional list names PNG attachments (render them with render_mermaid.mjs) that replace
  the mermaid blocks in order; each block's source is kept in a collapsed "Diagram source" expand.
Tokens in the markdown:
  @@AUTHOR_PANEL@@  -> an info panel carrying the author mention + note
  @@MENTION@@       -> an @-mention of the author
  @@JIRA:KEY@@      -> a live Jira issue macro (status updates as the ticket moves lanes)
Environment (read only when the matching token is used):
  CONFLUENCE_AUTHOR_ACCOUNT_ID  Atlassian account id of the real author (@@MENTION@@, @@AUTHOR_PANEL@@)
  CONFLUENCE_JIRA_SERVER        Jira macro "server" parameter, the Jira application link name (@@JIRA:KEY@@)
  CONFLUENCE_JIRA_SERVER_ID     Jira macro "serverId" parameter, the application link id (@@JIRA:KEY@@)
  Copy the last two from an existing page's Jira macro (GET the page with expand=body.storage).
"""
import html
import os
import re
import subprocess
import sys

def _env(name, why):
    value = os.environ.get(name, "").strip()
    if not value:
        sys.exit(f"md2cf: set {name} ({why}).")
    return value

def _mention():
    account_id = _env("CONFLUENCE_AUTHOR_ACCOUNT_ID", "the author's Atlassian account id, needed for @@MENTION@@ / @@AUTHOR_PANEL@@")
    return f'<ac:link><ri:user ri:account-id="{account_id}" /></ac:link>'

src, out, panel_text = sys.argv[1], sys.argv[2], sys.argv[3]
diagram_pngs = [x for x in (sys.argv[4].split(",") if len(sys.argv) > 4 else []) if x]
# Markdown converters drop "<word>" text as HTML (a published page once read "Resolved on , fix released in ").
# Refuse angle-bracket placeholders outside code; write them as [date] / TBD instead.
_md = open(src).read()
_prose = re.sub(r"```.*?```", "", _md, flags=re.S)
_prose = re.sub(r"`[^`\n]*`", "", _prose)
_bad = sorted(set(re.findall(r"<[A-Za-z][^<>\n]{0,40}>", _prose)))
if _bad:
    sys.exit(f"md2cf: angle-bracket text outside code would be dropped by the converter: {_bad}. Use [placeholder] or backticks.")

body = subprocess.run(
    ["markdown_py", "-x", "tables", "-x", "fenced_code", src],
    check=True, capture_output=True, text=True,
).stdout

# Fenced code -> Confluence code macro (mermaid kept as source text).
def code_macro(m):
    lang = m.group(1) or "text"
    code = html.unescape(m.group(2))
    return (
        '<ac:structured-macro ac:name="code">'
        f'<ac:parameter ac:name="language">{"text" if lang == "mermaid" else lang}</ac:parameter>'
        f'<ac:parameter ac:name="title">{lang}</ac:parameter>'
        f"<ac:plain-text-body><![CDATA[{code}]]></ac:plain-text-body>"
        "</ac:structured-macro>"
    )
body = re.sub(r'<pre><code(?: class="language-([\w-]+)")?>(.*?)</code></pre>', code_macro, body, flags=re.S)

# Mermaid blocks -> attached PNG + collapsed source (Confluence has no Mermaid macro).
_pngs = iter(diagram_pngs)
def _diagram(m):
    png = next(_pngs, None)
    if png is None:
        return m.group(0)
    return (f'<p><ac:image ac:width="1000"><ri:attachment ri:filename="{png}" /></ac:image></p>'
            '<ac:structured-macro ac:name="expand"><ac:parameter ac:name="title">Diagram source (Mermaid)</ac:parameter>'
            f'<ac:rich-text-body>{m.group(0)}</ac:rich-text-body></ac:structured-macro>')
body = re.sub(r'<ac:structured-macro ac:name="code"><ac:parameter ac:name="language">text</ac:parameter>'
              r'<ac:parameter ac:name="title">mermaid</ac:parameter>.*?</ac:structured-macro>', _diagram, body, flags=re.S)

# "- [ ] item" lists -> Confluence task lists.
task_id = [0]
def task_list(m):
    items = re.findall(r"<li>\[ \]\s*(.*?)</li>", m.group(0), flags=re.S)
    tasks = []
    for it in items:
        task_id[0] += 1
        tasks.append(
            f"<ac:task><ac:task-id>{task_id[0]}</ac:task-id><ac:task-status>incomplete</ac:task-status>"
            f"<ac:task-body>{it.strip()}</ac:task-body></ac:task>"
        )
    return "<ac:task-list>" + "".join(tasks) + "</ac:task-list>"
body = re.sub(r"<ul>\s*(?:<li>\[ \].*?</li>\s*)+</ul>", task_list, body, flags=re.S)

# @@JIRA:KEY@@ -> live Jira issue macro (shows the ticket's current status on the page).
if "@@JIRA:" in body:
    server = _env("CONFLUENCE_JIRA_SERVER", "the Jira macro server name, needed for @@JIRA:KEY@@")
    server_id = _env("CONFLUENCE_JIRA_SERVER_ID", "the Jira macro server id, needed for @@JIRA:KEY@@")
    body = re.sub(
        r"@@JIRA:([A-Z][A-Z0-9]+-\d+)@@",
        lambda m: ('<ac:structured-macro ac:name="jira" ac:schema-version="1">'
                   f'<ac:parameter ac:name="server">{server}</ac:parameter>'
                   f'<ac:parameter ac:name="serverId">{server_id}</ac:parameter>'
                   f'<ac:parameter ac:name="key">{m.group(1)}</ac:parameter></ac:structured-macro>'),
        body,
    )

if "<p>@@AUTHOR_PANEL@@</p>" in body or "@@MENTION@@" in body:
    MENTION = _mention()
    panel = (
        '<ac:structured-macro ac:name="info"><ac:rich-text-body>'
        f"<p>{panel_text.replace('@@MENTION@@', MENTION)}</p>"
        "</ac:rich-text-body></ac:structured-macro>"
    )
    body = body.replace("<p>@@AUTHOR_PANEL@@</p>", panel).replace("@@MENTION@@", MENTION)
assert "@@" not in body, "unreplaced token"
open(out, "w").write(body)
print(f"wrote {out}: {len(body)} chars, {task_id[0]} tasks, {body.count('ac:name=\"code\"')} code macros")
