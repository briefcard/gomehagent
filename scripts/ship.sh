#!/bin/sh
# Gate, commit, push — in that order, gated on EXIT CODES.
#
# Exists because of edf6803: a red suite reached main when a commit was
# chained off `tail` succeeding instead of off the tests. Piping a test run
# into anything discards the one bit that matters. This script is the only
# sanctioned path to push, and each gate stops the train by itself:
#
#   1. every app module byte-compiles;
#   2. the web app IMPORTS — a duplicated decorator once took web.py down at
#      import and 44 suites with it, and py_compile cannot see that class;
#   3. the full suite passes, judged by test_all.sh's own exit code.
#
# Usage: scripts/ship.sh "commit subject" [body-file]
set -e
cd "$(dirname "$0")/.."

if [ -z "$1" ]; then
  echo "usage: scripts/ship.sh \"commit subject\" [body-file]" >&2
  exit 2
fi

echo "── gate 1/3: byte-compile app/"
python3 -m compileall -q app scripts

echo "── gate 2/3: the web app imports"
DATABASE_URL="sqlite:///$(mktemp -d)/ship.db" APPROVAL_SECRET=ship-gate \
  python3 -c "import app.web, app.worker" 

echo "── gate 3/3: the full suite"
./scripts/test_all.sh

echo "── gates green — committing"
git add -A
if [ -n "$2" ] && [ -f "$2" ]; then
  git commit -q -F "$2"
else
  git commit -q -m "$1

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
fi
git push origin "$(git rev-parse --abbrev-ref HEAD)"
git log --oneline -1
