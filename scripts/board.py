#!/usr/bin/env python3
"""Task board for the factory skill: GitHub issues as tasks, plus an HTML kanban dashboard."""

import argparse
import contextlib
import fcntl
import html
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

COLUMNS = {
    "todo": "Todo", "plan": "Plan", "implement": "Implement", "cleanup": "Cleanup",
    "verify": "Verify", "ux": "UI/UX verify", "merge": "Merge",
    "human": "Human interaction needed", "done": "Done",
}
ACTIVE = ["plan", "implement", "cleanup", "verify", "ux", "merge"]
PRIORITIES = {"high": 0, "normal": 1, "low": 2}
MAX_FAILURES = 3
TRUSTED_AUTHORS = {"OWNER", "MEMBER", "COLLABORATOR"}
APPROVED_LABEL = "factory:approved"
HUMAN_LABEL = "factory:human"


def stage_label(status):
    return f"factory:{status}"


def failure_label(count):
    return f"factory:failures-{count}"


LABELS = {
    **{stage_label(s): "1d76db" for s in COLUMNS if s not in ("todo", "human")},
    HUMAN_LABEL: "d93f0b",
    APPROVED_LABEL: "0e8a16",
    **{failure_label(n): "fbca04" for n in range(1, MAX_FAILURES + 1)},
    "priority:high": "b60205",
    "priority:low": "c5def5",
}


class BoardError(Exception):
    pass


def git_common_dir():
    try:
        common = subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        raise BoardError("not inside a git repository")
    return Path(common)


def project_root():
    """Find the main checkout, so that worktrees share one board."""
    return git_common_dir().parent


def gh(root, *args):
    try:
        result = subprocess.run(["gh", *args], cwd=root, capture_output=True, text=True)
    except FileNotFoundError:
        raise BoardError("the GitHub CLI (gh) is required: install it and run gh auth login")
    if result.returncode != 0:
        raise BoardError(f"gh {args[0]} failed: {result.stderr.strip()}")
    return result.stdout


def gh_issues(root, query):
    """Read a paginated issue listing; gh may print one JSON array per page."""
    text = gh(root, "api", "--paginate", f"repos/{{owner}}/{{repo}}/issues?per_page=100&{query}")
    decoder, issues, position = json.JSONDecoder(), [], 0
    text = text.strip()
    while position < len(text):
        page, position = decoder.raw_decode(text, position)
        issues.extend(page)
        while position < len(text) and text[position].isspace():
            position += 1
    return issues


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def cache_path(root):
    return root / ".factory" / "tasks.json"


def load_cache(root):
    try:
        return {t["number"]: t for t in json.loads(cache_path(root).read_text())["tasks"]}
    except FileNotFoundError:
        raise BoardError("no board here; run init first")
    except (json.JSONDecodeError, KeyError) as e:
        raise BoardError(f"{cache_path(root)} is damaged: {e}")


def write_atomic(path, text):
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def save(root, tasks):
    ordered = sorted(tasks.values(), key=lambda t: t["number"])
    write_atomic(cache_path(root), json.dumps({"tasks": ordered}, indent=2) + "\n")
    write_atomic(root / ".factory" / "dashboard.html", render_html(ordered))


def to_task(issue, cached):
    labels = [label["name"] for label in issue["labels"]]
    status = "todo"
    if issue["state"] == "closed":
        status = "done"
    elif HUMAN_LABEL in labels:
        status = "human"
    else:
        for stage in [*ACTIVE, "done"]:
            if stage_label(stage) in labels:
                status = stage
    priority = "high" if "priority:high" in labels else "low" if "priority:low" in labels else "normal"
    failures = max((n for n in range(1, MAX_FAILURES + 1) if failure_label(n) in labels), default=0)
    is_human = status == "human"
    return {
        "number": issue["number"], "id": f"#{issue['number']}", "title": issue["title"],
        "description": issue.get("body") or "", "url": issue.get("html_url", ""),
        "labels": labels, "status": status, "priority": priority, "failures": failures,
        "author": issue["user"]["login"],
        "trusted": issue.get("author_association") in TRUSTED_AUTHORS or APPROVED_LABEL in labels,
        "created": issue["created_at"], "updated": issue["updated_at"],
        "branch": cached.get("branch"),
        "human_reason": cached.get("human_reason") if is_human else None,
        "human_stage": cached.get("human_stage") if is_human else None,
        "last_event": cached.get("last_event"),
    }


def sync(root):
    """Issues are the source of truth; the local file adds only what labels can't hold."""
    cache = load_cache(root)
    issues = gh_issues(root, "state=open") + gh_issues(root, f"state=closed&labels={stage_label('done')}")
    return {
        i["number"]: to_task(i, cache.get(i["number"], {}))
        for i in issues if "pull_request" not in i
    }


@contextlib.contextmanager
def locked(root):
    """Hold the board lock, since parallel task runs may write at the same time."""
    if not cache_path(root).exists():
        raise BoardError("no board here; run init first")
    with open(root / ".factory" / ".lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield sync(root)


def find(tasks, task_id):
    try:
        return tasks[int(task_id.lstrip("#"))]
    except (ValueError, KeyError):
        raise BoardError(f"no open factory task {task_id}")


def change_labels(root, task, add=(), remove=()):
    remove = [label for label in remove if label in task["labels"]]
    add = [label for label in add if label not in task["labels"]]
    args = [arg for label in add for arg in ("--add-label", label)]
    args += [arg for label in remove for arg in ("--remove-label", label)]
    if args:
        gh(root, "issue", "edit", str(task["number"]), *args)
    task["labels"] = [label for label in task["labels"] if label not in remove] + add


def set_status(root, task, status):
    stages = [stage_label(s) for s in COLUMNS if s not in ("todo", "human")] + [HUMAN_LABEL]
    target = [] if status == "todo" else [HUMAN_LABEL if status == "human" else stage_label(status)]
    change_labels(root, task, add=target, remove=[label for label in stages if label not in target])
    task["status"] = status


def clear_failures(root, task):
    change_labels(root, task, remove=[failure_label(n) for n in range(1, MAX_FAILURES + 1)])
    task["failures"] = 0


def hand_to_human(root, task, reason):
    if task["status"] != "human":
        task["human_stage"] = task["status"]
    set_status(root, task, "human")
    task["human_reason"] = reason
    task["last_event"] = f"Needs a human: {reason}"
    gh(root, "issue", "comment", str(task["number"]), "--body",
       f"Factory needs a human for this task (stage: {task['human_stage']}).\n\n{reason}")


def next_task(tasks):
    todo = [t for t in tasks.values() if t["status"] == "todo" and t["trusted"]]
    return min(todo, key=lambda t: (PRIORITIES[t["priority"]], t["number"]), default=None)


def summary(task):
    line = f"{task['id']}  [{task['status']}]  ({task['priority']})  {task['title']}"
    if task["failures"]:
        line += f"  failures={task['failures']}"
    if not task["trusted"]:
        line += "  [unapproved: outside author]"
    if task.get("human_reason"):
        line += f"  -- needs a human after {task['human_stage']}: {task['human_reason']}"
    return line


def render_card(task):
    e = lambda value: html.escape(str(value))
    title = e(task["title"])
    if str(task.get("url", "")).startswith("https://"):
        title = f'<a href="{e(task["url"])}">{title}</a>'
    parts = [
        f'<article class="card {e(task["priority"])}">',
        f'<div class="meta"><span>{e(task["id"])}</span><span>{e(task["priority"])}</span></div>',
        f'<h3>{title}</h3>',
    ]
    if not task["trusted"]:
        parts.append(f'<p class="reason">Unapproved: opened by {e(task["author"])}, who is outside the project</p>')
    if task.get("branch"):
        parts.append(f'<code>{e(task["branch"])}</code>')
    if task["failures"]:
        parts.append(f'<p>Failures: {e(task["failures"])}</p>')
    if task.get("human_reason"):
        parts.append(f'<p class="reason"><b>After {e(task["human_stage"])}:</b> {e(task["human_reason"])}</p>')
    elif task.get("last_event"):
        parts.append(f'<p>{e(task["last_event"])}</p>')
    parts.append(f'<time>{e(task["updated"])}</time></article>')
    return "".join(parts)


def render_html(tasks):
    columns = []
    for status, name in COLUMNS.items():
        cards = [t for t in tasks if t["status"] == status]
        if status == "todo":
            cards.sort(key=lambda t: (PRIORITIES[t["priority"]], t["number"]))
        else:
            cards.sort(key=lambda t: t["updated"], reverse=status == "done")
        body = "".join(render_card(t) for t in cards) or '<p class="empty">Nothing here</p>'
        columns.append(
            f'<section class="column {status}"><h2>{name} '
            f'<span class="count">{len(cards)}</span></h2>{body}</section>'
        )
    running = sum(t["status"] in ACTIVE for t in tasks)
    human = sum(t["status"] == "human" for t in tasks)
    return PAGE.format(running=running, human=human, updated=html.escape(now()), columns="".join(columns))


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="10">
<title>Factory Board</title>
<style>
:root {{ color-scheme: light dark; --bg: #f5f6f8; --column: #e9ebef; --card: #fff; --text: #1d2129;
  --muted: #626a78; --line: #d6d9df; --high: #c8372d; --normal: #2f6fde; --low: #7a828f; --warn: #fbeae8; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg: #14161a; --column: #1e2127; --card: #2a2e36;
  --text: #eceef2; --muted: #a0a7b4; --line: #3a3f49; --high: #f0776d; --normal: #7aa7f5; --low: #8e96a3; --warn: #43251f; }} }}
* {{ box-sizing: border-box; }}
body {{ margin: 0; padding: 16px; background: var(--bg); color: var(--text); font: 14px/1.4 system-ui, sans-serif; }}
header {{ display: flex; flex-wrap: wrap; gap: 4px 16px; align-items: baseline; margin-bottom: 16px; }}
h1 {{ margin: 0; font-size: 20px; }}
header span {{ color: var(--muted); }}
main {{ display: grid; grid-auto-flow: column; grid-auto-columns: minmax(220px, 1fr); gap: 12px; overflow-x: auto; align-items: start; padding-bottom: 8px; }}
.column {{ background: var(--column); border-radius: 8px; padding: 10px; min-height: 120px; }}
.column.human {{ outline: 2px solid var(--high); outline-offset: -2px; }}
h2 {{ display: flex; justify-content: space-between; gap: 8px; margin: 0 0 10px; font-size: 13px; font-weight: 600; }}
.count {{ color: var(--muted); font-variant-numeric: tabular-nums; }}
.card {{ background: var(--card); border: 1px solid var(--line); border-left: 3px solid var(--normal); border-radius: 6px; padding: 10px; margin-bottom: 8px; overflow-wrap: anywhere; }}
.card.high {{ border-left-color: var(--high); }}
.card.low {{ border-left-color: var(--low); }}
.meta, time {{ display: flex; justify-content: space-between; color: var(--muted); font-size: 12px; }}
h3 {{ margin: 4px 0 6px; font-size: 14px; font-weight: 600; }}
h3 a {{ color: inherit; }}
code {{ display: block; color: var(--muted); font-size: 12px; margin-bottom: 6px; }}
.card p {{ margin: 0 0 6px; font-size: 13px; }}
.card p.reason {{ background: var(--warn); border-radius: 4px; padding: 6px; }}
.empty {{ color: var(--muted); font-size: 13px; margin: 0; }}
</style>
</head>
<body>
<header><h1>Factory Board</h1><span>{running} running</span><span>{human} need a human</span><span>Updated {updated}</span></header>
<main>{columns}</main>
</body>
</html>
"""


def cmd_init(args, root):
    factory = root / ".factory"
    factory.mkdir(exist_ok=True)
    if not cache_path(root).exists():
        write_atomic(cache_path(root), json.dumps({"tasks": []}) + "\n")
    # Local state stays out of git without adding a commit to the user's repo.
    exclude = git_common_dir() / "info" / "exclude"
    exclude.parent.mkdir(exist_ok=True)
    existing = exclude.read_text() if exclude.exists() else ""
    if ".factory/" not in existing.splitlines():
        prefix = existing + ("\n" if existing and not existing.endswith("\n") else "")
        exclude.write_text(prefix + ".factory/\n")
    for label, color in LABELS.items():
        gh(root, "label", "create", label, "--color", color, "--force")
    with locked(root) as tasks:
        save(root, tasks)
    print(f"Board ready: {factory / 'dashboard.html'}")


def cmd_add(args, root):
    with locked(root) as tasks:
        command = ["issue", "create", "--title", args.title, "--body", args.description or ""]
        if args.priority != "normal":
            command += ["--label", f"priority:{args.priority}"]
        url = gh(root, *command).strip()
        number = int(url.rstrip("/").rsplit("/", 1)[-1])
        tasks = sync(root)
        save(root, tasks)
    print(summary(find(tasks, str(number))))


def cmd_list(args, root):
    with locked(root) as tasks:
        save(root, tasks)
    shown = [t for t in tasks.values() if t["status"] != "done" or args.status == "done"]
    if args.status:
        visible = {args.status, "human", *ACTIVE}
        shown = [t for t in shown if t["status"] in visible]
    order = list(COLUMNS)
    shown.sort(key=lambda t: (-order.index(t["status"]), PRIORITIES[t["priority"]], t["number"]))
    for task in shown:
        print(summary(task))
    if not shown:
        print("No tasks")


def cmd_show(args, root):
    with locked(root) as tasks:
        save(root, tasks)
    print(json.dumps(find(tasks, args.id), indent=2))


def cmd_next(args, root):
    with locked(root) as tasks:
        save(root, tasks)
    task = next_task(tasks)
    if task is None:
        print("No approved todo tasks")
        return 1
    print(json.dumps(task, indent=2))


def cmd_approve(args, root):
    with locked(root) as tasks:
        task = find(tasks, args.id)
        change_labels(root, task, add=[APPROVED_LABEL])
        task["trusted"] = True
        task["last_event"] = "Approved by the user"
        save(root, tasks)
    print(summary(task))


def cmd_move(args, root):
    with locked(root) as tasks:
        task = find(tasks, args.id)
        if not task["trusted"] and args.status != "todo":
            raise BoardError(f"{task['id']} is from an outside author; the user must approve it first")
        previous = task["status"]
        set_status(root, task, args.status)
        # Leaving the human column means someone decided to retry, so the count starts over.
        if previous == "human" or args.status in ("todo", "done"):
            clear_failures(root, task)
        task["human_reason"] = task["human_stage"] = None
        task["last_event"] = args.note or f"Moved from {previous} to {args.status}"
        save(root, tasks)
    print(summary(task))


def cmd_fail(args, root):
    with locked(root) as tasks:
        task = find(tasks, args.id)
        failures = task["failures"] + 1
        if failures > MAX_FAILURES:
            hand_to_human(root, task, f"Failed {failures} times. Latest: {args.reason}")
        else:
            change_labels(root, task, add=[failure_label(failures)],
                          remove=[failure_label(n) for n in range(1, failures)])
            task["failures"] = failures
            task["last_event"] = f"Failure {failures}: {args.reason}"
        save(root, tasks)
    print(summary(task))
    print("RETRY" if task["status"] != "human" else "HUMAN")


def cmd_human(args, root):
    with locked(root) as tasks:
        task = find(tasks, args.id)
        hand_to_human(root, task, args.reason)
        save(root, tasks)
    print(summary(task))


def cmd_edit(args, root):
    with locked(root) as tasks:
        task = find(tasks, args.id)
        command = []
        if args.title is not None:
            command += ["--title", args.title]
        if args.description is not None:
            command += ["--body", args.description]
        if not command and args.priority is None and args.branch is None:
            raise BoardError("nothing to edit")
        if command:
            gh(root, "issue", "edit", str(task["number"]), *command)
            task.update(title=args.title or task["title"],
                        description=task["description"] if args.description is None else args.description)
        if args.priority is not None:
            add = [] if args.priority == "normal" else [f"priority:{args.priority}"]
            change_labels(root, task, add=add,
                          remove=[l for l in ("priority:high", "priority:low") if l not in add])
            task["priority"] = args.priority
        if args.branch is not None:
            task["branch"] = args.branch
        save(root, tasks)
    print(summary(task))


def cmd_close(args, root):
    with locked(root) as tasks:
        task = find(tasks, args.id)
        command = ["issue", "close", str(task["number"]), "--comment", args.comment]
        if args.not_planned:
            command += ["--reason", "not planned"]
        elif task["status"] != "done":
            raise BoardError(f"{task['id']} is {task['status']}, not done; only finished work closes as completed")
        gh(root, *command)
        if args.not_planned:
            del tasks[task["number"]]
        save(root, tasks)
    print(f"Closed {task['id']}")


def cmd_render(args, root):
    with locked(root) as tasks:
        save(root, tasks)
    print(root / ".factory" / "dashboard.html")


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    stages = [s for s in COLUMNS if s != "human"]

    sub.add_parser("init").set_defaults(func=cmd_init)
    p = sub.add_parser("add")
    p.add_argument("title")
    p.add_argument("-d", "--description")
    p.add_argument("-p", "--priority", choices=PRIORITIES, default="normal")
    p.set_defaults(func=cmd_add)
    p = sub.add_parser("list")
    p.add_argument("--status", choices=COLUMNS)
    p.set_defaults(func=cmd_list)
    p = sub.add_parser("show")
    p.add_argument("id")
    p.set_defaults(func=cmd_show)
    sub.add_parser("next").set_defaults(func=cmd_next)
    p = sub.add_parser("approve")
    p.add_argument("id")
    p.set_defaults(func=cmd_approve)
    p = sub.add_parser("move")
    p.add_argument("id")
    p.add_argument("status", choices=stages)
    p.add_argument("--note")
    p.set_defaults(func=cmd_move)
    p = sub.add_parser("fail")
    p.add_argument("id")
    p.add_argument("reason")
    p.set_defaults(func=cmd_fail)
    p = sub.add_parser("human")
    p.add_argument("id")
    p.add_argument("reason")
    p.set_defaults(func=cmd_human)
    p = sub.add_parser("edit")
    p.add_argument("id")
    p.add_argument("--title")
    p.add_argument("-d", "--description")
    p.add_argument("-p", "--priority", choices=PRIORITIES)
    p.add_argument("--branch")
    p.set_defaults(func=cmd_edit)
    p = sub.add_parser("close")
    p.add_argument("id")
    p.add_argument("--comment", required=True)
    p.add_argument("--not-planned", action="store_true")
    p.set_defaults(func=cmd_close)
    sub.add_parser("render").set_defaults(func=cmd_render)
    return parser


def main():
    args = build_parser().parse_args()
    try:
        return args.func(args, project_root()) or 0
    except BoardError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
