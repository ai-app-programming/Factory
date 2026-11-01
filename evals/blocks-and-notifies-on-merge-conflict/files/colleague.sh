#!/usr/bin/env bash
set -eu
printf 'print("Good day")\n' > hello.py
git -c user.name=colleague -c user.email=colleague@example.com commit -qm "Change greeting" hello.py
