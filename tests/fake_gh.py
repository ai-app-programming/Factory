#!/usr/bin/env python3
"""A stand-in for the GitHub CLI, keeping issues in gh-state.json beside this file."""

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

STATE = Path(__file__).resolve().with_name("gh-state.json")
URL = "https://github.com/example/repo/issues/"


def load():
    if STATE.exists():
        return json.loads(STATE.read_text())
    return {"next": 1, "issues": [], "labels": [], "comments": []}


def issue_by_number(state, number):
    return next(i for i in state["issues"] if i["number"] == int(number))


def add_labels(state, issue, names):
    for name in names:
        if name not in state["labels"]:
            sys.exit(f"could not add label: '{name}' not found")
        if name not in [label["name"] for label in issue["labels"]]:
            issue["labels"].append({"name": name})


def api(state, args):
    query = parse_qs(urlparse(args[-1]).query)
    wanted = query.get("labels", [None])[0]
    found = [
        i for i in state["issues"] if i["state"] == query["state"][0]
        and (wanted is None or wanted in [label["name"] for label in i["labels"]])
    ]
    # Split into two arrays, as gh can do across pages.
    print(json.dumps(found[:1]))
    print(json.dumps(found[1:]))


def issue(state, args):
    action, rest = args[0], args[1:]
    parser = argparse.ArgumentParser()
    if action != "create":
        parser.add_argument("number")
    for flag in ("--title", "--body", "--comment", "--reason"):
        parser.add_argument(flag)
    for flag in ("--label", "--add-label", "--remove-label"):
        parser.add_argument(flag, action="append", default=[])
    opts = parser.parse_args(rest)
    if action == "create":
        if not opts.title:
            sys.exit("title required")
        new = {
            "number": state["next"], "title": opts.title, "body": opts.body or "", "state": "open",
            "labels": [], "user": {"login": "owner"}, "author_association": "OWNER",
            "html_url": f"{URL}{state['next']}", "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
        }
        add_labels(state, new, opts.label)
        state["issues"].append(new)
        state["next"] += 1
        print(new["html_url"])
        return
    target = issue_by_number(state, opts.number)
    if action == "edit":
        target["title"] = opts.title or target["title"]
        target["body"] = target["body"] if opts.body is None else opts.body
        add_labels(state, target, opts.add_label)
        target["labels"] = [l for l in target["labels"] if l["name"] not in opts.remove_label]
    elif action == "comment":
        state["comments"].append({"number": target["number"], "body": opts.body})
    elif action == "close":
        target["state"] = "closed"
        state["comments"].append({"number": target["number"], "body": opts.comment})
    else:
        sys.exit(f"unsupported: issue {action}")


def main():
    state = load()
    command, args = sys.argv[1], sys.argv[2:]
    if command == "api":
        api(state, args)
    elif command == "issue":
        issue(state, args)
    elif command == "label" and args[0] == "create":
        if args[1] not in state["labels"]:
            state["labels"].append(args[1])
    else:
        sys.exit(f"unsupported: {command}")
    STATE.write_text(json.dumps(state, indent=2))


if __name__ == "__main__":
    main()
