#!/usr/bin/env python3
"""Post a review to GitLab without interpolating report text into a shell command.

Two modes:
  post    the whole report as one MR note.
  inline  one discussion per finding, anchored to its line in the MR diff
          (GitLab "DiffNote"). A finding whose line is not in the diff, or that
          has no line, becomes a general MR discussion that names the line.
"""

import argparse
import json
import re
import subprocess
from pathlib import Path
from urllib.parse import quote

from review_common import die, ensure_current_head, ensure_current_head_metadata

HUNK_RE = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")
PER_PAGE = 100


def glab_api(args, payload=None, timeout=60):
    command = ["glab", "api", *args]
    if payload is not None:
        command += ["-X", "POST", "-H", "Content-Type: application/json", "--input", "-"]
    try:
        result = subprocess.run(
            command,
            input=json.dumps(payload) if payload is not None else None,
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        die("glab is not installed")
    except subprocess.TimeoutExpired:
        die(f"timed out calling glab api {args[0]}")
    except subprocess.CalledProcessError as error:
        detail = (error.stderr or error.stdout or "unknown glab error").strip()[:1000]
        raise RuntimeError(detail) from None
    return json.loads(result.stdout) if result.stdout.strip() else None


def paged(path):
    items, page = [], 1
    joiner = "&" if "?" in path else "?"
    while True:
        try:
            batch = glab_api([f"{path}{joiner}per_page={PER_PAGE}&page={page}"])
        except RuntimeError as error:
            die(f"glab api {path} failed: {error}")
        items.extend(batch or [])
        if not batch or len(batch) < PER_PAGE:
            return items
        page += 1


def diff_line_map(diff_text):
    """Map each new-file line that appears in the diff to its old line.

    Added lines map to None; context lines map to their old line number.
    Removed lines are returned separately (old line -> True).
    """
    new_lines, removed = {}, set()
    old_no = new_no = 0
    for raw in diff_text.splitlines():
        hunk = HUNK_RE.match(raw)
        if hunk:
            old_no, new_no = int(hunk.group(1)), int(hunk.group(2))
            continue
        if not old_no and not new_no:
            continue
        if raw.startswith("+"):
            new_lines[new_no] = None
            new_no += 1
        elif raw.startswith("-"):
            removed.add(old_no)
            old_no += 1
        elif raw.startswith("\\"):
            continue
        else:
            new_lines[new_no] = old_no
            old_no += 1
            new_no += 1
    return new_lines, removed


def load_comments(path):
    file_path = Path(path)
    if not file_path.is_file():
        die(f"comments file does not exist: {file_path}")
    try:
        comments = json.loads(file_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        die(f"comments file is not valid JSON: {error}")
    if not isinstance(comments, list) or not comments:
        die("comments file must be a non-empty JSON list")
    for index, item in enumerate(comments):
        if not isinstance(item, dict) or not str(item.get("body", "")).strip():
            die(f"comment {index} needs a non-empty 'body'")
        if item.get("line") is not None and not item.get("path"):
            die(f"comment {index} has a 'line' but no 'path'")
    return comments


def post_inline(args):
    comments = load_comments(args.comments)
    project, iid, current, metadata = ensure_current_head_metadata(
        args.mr_url, args.head_sha, allow_stale=args.allow_stale
    )
    refs = metadata.get("diff_refs") or {}
    if not all(refs.get(key) for key in ("base_sha", "start_sha", "head_sha")):
        die("MR metadata has no diff_refs; cannot anchor inline comments")
    api_root = f"projects/{quote(project, safe='')}/merge_requests/{iid}"
    host = re.match(r"^(https?://[^/]+)/", args.mr_url).group(1)
    mr_web = args.mr_url.split("#")[0].rstrip("/")

    diffs = {d["new_path"]: d for d in paged(f"{api_root}/diffs")}
    existing = set()
    if not args.repost:
        for discussion in paged(f"{api_root}/discussions"):
            for note in discussion.get("notes", []):
                position = note.get("position") or {}
                existing.add(
                    (position.get("new_path"), position.get("new_line"), note.get("body", "").strip())
                )

    print(f"MR_IID={iid}")
    print(f"CURRENT_MR_HEAD={current}")
    for item in comments:
        path, line, body = item.get("path"), item.get("line"), item["body"].strip()
        payload = {"body": body}
        where = f"{path}:{line}" if path else "general"
        diff = diffs.get(path) if path else None
        anchored = False
        if diff and line is not None:
            new_lines, _ = diff_line_map(diff.get("diff", ""))
            line = int(line)
            if line in new_lines:
                position = {
                    "position_type": "text",
                    "base_sha": refs["base_sha"],
                    "start_sha": refs["start_sha"],
                    "head_sha": refs["head_sha"],
                    "new_path": path,
                    "old_path": diff.get("old_path") or path,
                    "new_line": line,
                }
                if new_lines[line] is not None:
                    position["old_line"] = new_lines[line]
                payload["position"] = position
                anchored = True
        if not anchored and path:
            blob = f"{host}/{project}/-/blob/{refs['head_sha']}/{quote(path)}"
            link = f"{blob}#L{line}" if line is not None else blob
            label = f"{path}:{line}" if line is not None else path
            payload["body"] = f"[`{label}`]({link})\n\n{body}"

        key = (path if anchored else None, line if anchored else None, payload["body"])
        if key in existing:
            print(f"SKIPPED_DUPLICATE {where}")
            continue
        if args.dry_run:
            mode = "INLINE" if anchored else "GENERAL"
            print(f"DRY_RUN {mode} {where} {json.dumps(payload.get('position', {}))}")
            continue
        try:
            result = glab_api([f"{api_root}/discussions"], payload=payload)
        except RuntimeError as error:
            if not anchored:
                die(f"could not post the comment for {where}: {error}")
            # GitLab rejects some positions (e.g. a renamed file it diffed
            # differently). Keep the finding: post it as a general discussion.
            payload.pop("position", None)
            blob = f"{host}/{project}/-/blob/{refs['head_sha']}/{quote(path)}#L{line}"
            payload["body"] = f"[`{path}:{line}`]({blob})\n\n{body}"
            try:
                result = glab_api([f"{api_root}/discussions"], payload=payload)
            except RuntimeError as second:
                die(f"could not post the comment for {where}: {second}")
            anchored = False
            print(f"INLINE_REJECTED {where}: {str(error)[:200]}")
        note_id = ((result or {}).get("notes") or [{}])[0].get("id")
        url = f"{mr_web}#note_{note_id}" if note_id else mr_web
        print(f"{'INLINE_POSTED' if anchored else 'GENERAL_POSTED'} {where} {url}")


def post_note(args):
    report_path = Path(args.report)
    if not report_path.is_file():
        die(f"report file does not exist: {report_path}")
    report = report_path.read_text(encoding="utf-8")
    if not report.strip():
        die("report file is empty")

    project, iid, current = ensure_current_head(
        args.mr_url, args.head_sha, allow_stale=args.allow_stale
    )
    command = ["glab", "mr", "note", "create", iid, "-R", project]
    if not args.repost:
        command.append("--unique")
    try:
        result = subprocess.run(
            command, input=report, check=True, capture_output=True, text=True, timeout=30
        )
    except FileNotFoundError:
        die("glab is not installed; cannot post the GitLab review")
    except subprocess.TimeoutExpired:
        die("timed out while posting the GitLab review")
    except subprocess.CalledProcessError as error:
        detail = (error.stderr or error.stdout or "unknown glab error").strip()[:1000]
        die(f"glab could not post the review to MR !{iid} in {project}: {detail}")

    print(f"MR_IID={iid}")
    print(f"CURRENT_MR_HEAD={current}")
    print("POSTED_GITLAB_NOTE=true")
    output = result.stdout.strip()
    note_url = next(
        (word for word in output.split() if word.startswith("http") and "#note_" in word),
        "",
    )
    if note_url:
        print(f"NOTE_URL={note_url}")
    if output:
        print(output)


def main():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    post_parser = subparsers.add_parser("post", help="post a review as one MR note")
    post_parser.add_argument("--mr-url", required=True)
    post_parser.add_argument("--report", required=True)
    post_parser.add_argument("--head-sha", required=True)
    post_parser.add_argument("--repost", action="store_true")
    post_parser.add_argument("--allow-stale", action="store_true")

    inline_parser = subparsers.add_parser(
        "inline", help="post one discussion per finding, on its diff line"
    )
    inline_parser.add_argument("--mr-url", required=True)
    inline_parser.add_argument(
        "--comments",
        required=True,
        help='JSON list of {"path": ..., "line": <new-file line>, "body": ...}; '
        "omit path/line for a general comment",
    )
    inline_parser.add_argument("--head-sha", required=True)
    inline_parser.add_argument("--repost", action="store_true")
    inline_parser.add_argument("--allow-stale", action="store_true")
    inline_parser.add_argument("--dry-run", action="store_true")

    args = parser.parse_args()
    if args.command == "inline":
        post_inline(args)
    else:
        post_note(args)


if __name__ == "__main__":
    main()
