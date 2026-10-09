#!/usr/bin/env python3
"""Shared safeguards for posting an MR review externally."""

import json
import re
import subprocess
import sys


MR_URL_RE = re.compile(
    r"^https?://[^/]+/(?P<project>.+)/-/merge_requests/(?P<iid>\d+)(?:[/?#].*)?$"
)
SHA_RE = re.compile(r"^[0-9a-fA-F]{7,64}$")


def die(message):
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def parse_mr_url(mr_url):
    match = MR_URL_RE.fullmatch(mr_url.strip())
    if not match:
        die(f"invalid GitLab merge-request URL: {mr_url}")
    return match.group("project"), match.group("iid")


def current_mr_metadata(mr_url):
    project, iid = parse_mr_url(mr_url)
    command = ["glab", "mr", "view", iid, "-R", project, "-F", "json"]
    try:
        result = subprocess.run(
            command, check=True, capture_output=True, text=True, timeout=30
        )
    except FileNotFoundError:
        die("glab is not installed; cannot verify the MR head")
    except subprocess.TimeoutExpired:
        die("timed out while verifying the current MR head with glab")
    except subprocess.CalledProcessError as error:
        detail = (error.stderr or error.stdout or "unknown glab error").strip()[:1000]
        die(f"glab could not verify MR !{iid} in {project}: {detail}")
    try:
        metadata = json.loads(result.stdout)
    except json.JSONDecodeError:
        die("glab returned invalid JSON while verifying the MR head")
    return project, iid, metadata


def ensure_current_head(mr_url, reviewed_head, allow_stale=False):
    reviewed_head = reviewed_head.strip().lower()
    if not SHA_RE.fullmatch(reviewed_head):
        die(f"invalid reviewed head SHA: {reviewed_head}")
    project, iid, metadata = current_mr_metadata(mr_url)
    diff_refs = metadata.get("diff_refs") or {}
    current = metadata.get("sha") or diff_refs.get("head_sha")
    if not current or not SHA_RE.fullmatch(str(current)):
        die("glab response did not include a valid current MR head SHA")
    current = str(current).lower()
    same_commit = current.startswith(reviewed_head) or reviewed_head.startswith(current)
    if not same_commit and not allow_stale:
        die(
            "STALE_REVIEW: reviewed head "
            f"{reviewed_head[:12]} no longer matches current MR head {current[:12]}; "
            "fetch and review the MR again before posting"
        )
    return project, iid, current
