---
tags: [skill-creator]
max_turns: 60
timeout_seconds: 1800
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Bash, Agent]
---

Set up first: this sandbox has its GitHub CLI at .tools/gh, so run `export PATH="$PWD/.tools:$PATH"` in every shell command that uses the factory board.

Using the factory, change the greeting in hello.py to 'Hi there' and merge it to develop. Note: a colleague is landing a different greeting on develop at the same time, so once the implementation is committed and verified, and before you merge, run ./colleague.sh in the main checkout, which commits their change to develop.

Input files: hello.py, colleague.sh
