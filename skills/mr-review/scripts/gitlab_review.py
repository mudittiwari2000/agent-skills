#!/usr/bin/env python3
"""Post a review to GitLab without interpolating report text into a shell command."""

import argparse
import subprocess
from pathlib import Path

from review_common import die, ensure_current_head


def main():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    post_parser = subparsers.add_parser("post", help="post a review as an MR note")
    post_parser.add_argument("--mr-url", required=True)
    post_parser.add_argument("--report", required=True)
    post_parser.add_argument("--head-sha", required=True)
    post_parser.add_argument("--repost", action="store_true")
    post_parser.add_argument("--allow-stale", action="store_true")
    args = parser.parse_args()

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
    if result.stdout.strip():
        print(result.stdout.strip())


if __name__ == "__main__":
    main()
