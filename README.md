# factory

A Claude skill that takes software tasks from a repo's GitHub issues through to a merge into `develop`, using subagents to plan, implement, clean up and verify (including a UI/UX check for UI work), with an HTML kanban board of what's running.

## Install

Clone into your Claude Code skills directory:

```bash
git clone git@github.com:ai-app-programming/factory.git ~/.claude/skills/factory
```

Requires Git, the [GitHub CLI](https://cli.github.com/) logged in with access to the target repo's issues, and Python 3.8+ (standard library only, Linux or macOS).

## Use

```text
Add "support CSV export" to the factory list as high priority
Show me the open tasks
Work on the next task
Build password reset end to end
Show the kanban board
```

Tasks are GitHub issues, with their stage, priority and failure count stored as labels. Only issues from the repo's owner, members and collaborators are worked on until you approve others. Open `.factory/dashboard.html` in the target repo to see the board; it reloads every 10 seconds, and `.factory/` stays out of git.

A task moves to the **Human interaction needed** column on its fourth failure, or as soon as a merge fails.

## Layout

- `SKILL.md`: the orchestrator's workflow
- `references/agent-briefs.md`: prompts for each subagent
- `references/coding-style.md`: how to choose between repo style and Google's guides
- `scripts/board.py`: task state and dashboard generation
- `tests/`: tests for `board.py`, using a fake `gh`
- `evals/`: test cases for the skill itself

## Test

```bash
python3 -m unittest discover tests
```
