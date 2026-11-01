#!/usr/bin/env bash
set -eu
here="$(cd "$(dirname "$0")" && pwd)"
cp -R "$here/files/." .
mkdir -p .tools
cp "$here/../../tests/fake_gh.py" .tools/gh
chmod +x .tools/gh
git init -q -b develop
echo ".tools/" >> .git/info/exclude
git add -A
git -c user.name=eval -c user.email=eval@example.com commit -qm "Initial commit"
git branch main
