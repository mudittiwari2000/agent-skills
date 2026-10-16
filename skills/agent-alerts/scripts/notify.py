#!/usr/bin/env python3
"""Post an agent alert (a monitor-dev-ci, monitor-stage-ci or mr-review-request report) to a Slack incoming webhook.

The webhook URL is read from the NOTIFY_WEBHOOK_URL environment variable and is
never printed. Everything else comes from arguments, so the message shape lives
in one place instead of being rebuilt by hand on every run.

Usage (dev report with an optional announcement call to action):

    NOTIFY_WEBHOOK_URL="$U" python3 notify.py \
        --skill monitor-dev-ci --repo my-monorepo \
        --status ok --headline "my-app deployed to dev" \
        --line "Tag: `my-app-v1.2.3`  Merge commit: <https://...|abc1234>" \
        --link "New tag page — prefilled=https://..." --link "Pipeline=https://..." \
        --code "Tag message" "Plain-language tag message" \
        --announce-text "@here\nInitiating stage deployment for my-app-v1.2.3\nCommit ID: <https://...|abc1234>" \
        --announce-channel-name "#team-channel" \
        --announce-channel-url "https://<workspace>.slack.com/archives/C123"

Prints `posted` on success, or `failed: <status> <body>` and exits 1.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

STATUS_EMOJI = {
    "ok": ":white_check_mark:",
    "failed": ":x:",
    "waiting": ":hourglass:",
    "blocked": ":warning:",
}


def build_payload(args: argparse.Namespace) -> dict:
    emoji = STATUS_EMOJI[args.status]
    header = f"*{args.skill}* · {args.repo}\n{emoji} *{args.headline}*"
    blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": header}}]

    if args.line:
        blocks.append(
            {"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(args.line)}}
        )
    if args.link:
        links = []
        for item in args.link:
            label, _, url = item.partition("=")
            links.append(f"<{url}|{label}>")
        blocks.append(
            {"type": "section", "text": {"type": "mrkdwn", "text": "  ·  ".join(links)}}
        )
    for title, body in args.code or []:
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"{title.rstrip(':')}:\n```{body}```"},
            }
        )

    if args.copy:
        items = "  ·  ".join(f"{i}. {label}" for i, (label, _) in enumerate(args.copy, 1))
        blocks.append(
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"*Ready to copy* (one message each, below; long-press to copy on mobile): {items}",
                    }
                ],
            }
        )

    if args.announce_text:
        blocks.append({"type": "divider"})
        blocks.append(
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": args.announce_note
                        or (
                            f"*Next:* copy the message below into {args.announce_channel_name} "
                            "when you start the stage deployment"
                        ),
                    }
                ],
            }
        )
        # Plain mrkdwn rather than a code block, so links keep their labels
        # (e.g. a short commit hash linked to the commit) when copied.
        blocks.append(
            {"type": "section", "text": {"type": "mrkdwn", "text": args.announce_text}}
        )
    if args.announce_channel_url:
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": args.announce_button
                            or f"Open {args.announce_channel_name}",
                        },
                        "url": args.announce_channel_url,
                        "action_id": "open_announce_channel",
                    }
                ],
            }
        )
    # verbatim: Slack must not parse the text. Unparsed, a literal "@here" or
    # "@Name" stays plain text (no ping in the alerts channel) and a "#channel"
    # is not auto-linked. Explicit <url|label> links still render.
    for block in blocks:
        for obj in [block.get("text")] + list(block.get("elements") or []):
            if isinstance(obj, dict) and obj.get("type") == "mrkdwn":
                obj["verbatim"] = True

    # Plain-text fallback for notifications and clients that do not render blocks.
    return {"text": f"{args.skill} · {args.repo}: {args.headline}", "blocks": blocks}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--skill", required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--status", required=True, choices=sorted(STATUS_EMOJI))
    parser.add_argument("--headline", required=True)
    parser.add_argument("--line", action="append", help="mrkdwn line; repeatable")
    parser.add_argument("--link", action="append", help="label=url; repeatable")
    parser.add_argument("--code", nargs=2, action="append", metavar=("TITLE", "BODY"))
    parser.add_argument("--announce-text")
    parser.add_argument("--announce-channel-name", default="the team channel")
    parser.add_argument("--announce-channel-url")
    parser.add_argument("--announce-note", help="mrkdwn line above the copyable text (default: the stage-deployment note)")
    parser.add_argument("--announce-button", help="button label (default: 'Open <channel name>')")
    parser.add_argument(
        "--copy", nargs=2, action="append", metavar=("LABEL", "TEXT"),
        help="text the user will paste elsewhere; posted as its own message after the alert "
        "(so it can be copied whole, e.g. on mobile); repeatable, posted in order",
    )
    parser.add_argument("--dry-run", action="store_true", help="print the payload, do not post")
    args = parser.parse_args()

    # Let callers pass literal "\n" in shell arguments.
    if args.announce_text:
        args.announce_text = args.announce_text.replace("\\n", "\n")
    if args.code:
        args.code = [(title, body.replace("\\n", "\n")) for title, body in args.code]
    if args.copy:
        args.copy = [(label, text.replace("\\n", "\n")) for label, text in args.copy]

    payloads = [build_payload(args)] + [copy_payload(text) for _, text in args.copy or []]
    if args.dry_run:
        print(json.dumps(payloads if len(payloads) > 1 else payloads[0], indent=2))
        return 0

    url = os.environ.get("NOTIFY_WEBHOOK_URL", "")
    if not url.startswith("https://hooks.slack.com/services/"):
        print("failed: NOTIFY_WEBHOOK_URL is missing or not a Slack webhook URL")
        return 1

    for number, payload in enumerate(payloads):
        result = post(url, payload)
        if result != "ok":
            what = "alert" if number == 0 else f"copy message {number}"
            print(f"failed ({what}): {result}")
            return 1
    print("posted" if len(payloads) == 1 else f"posted (alert + {len(payloads) - 1} copy messages)")
    return 0


def copy_payload(text: str) -> dict:
    """A message holding only the text to copy: no label, no formatting around it."""
    return {
        "text": text,
        "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": text, "verbatim": True}}],
    }


def post(url: str, payload: dict) -> str:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            body = response.read().decode(errors="replace")
            if response.status == 200 and body.strip() == "ok":
                return "ok"
            return f"{response.status} {body[:200]}"
    except urllib.error.HTTPError as error:
        return f"{error.code} {error.read().decode(errors='replace')[:200]}"
    except urllib.error.URLError as error:
        return str(error.reason)


if __name__ == "__main__":
    sys.exit(main())
