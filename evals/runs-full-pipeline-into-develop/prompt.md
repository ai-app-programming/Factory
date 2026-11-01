---
tags: [skill-creator]
max_turns: 60
timeout_seconds: 1800
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Bash, Agent]
---

Set up first: this sandbox has its GitHub CLI at .tools/gh, so run `export PATH="$PWD/.tools:$PATH"` in every shell command that uses the factory board.

This repo has a Python file calc.py with an add function and a unittest test file. Using the factory, add a divide function that gives a clear error on division by zero, and take it all the way to develop.

Input files: calc.py, test_calc.py
