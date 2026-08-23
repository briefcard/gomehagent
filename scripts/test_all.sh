#!/bin/sh
# Every suite, in parallel, failures only.
#
# Serially this takes five minutes on a quiet machine and over ten under load,
# which is long enough that it stops being run — and a suite nobody runs is a
# suite that is not protecting anything. Every suite sets its own
# DATABASE_URL to a fresh temp file at import, so there was never a shared
# resource to serialise around; it was just never parallelised. Measured
# 2026-08-23: 5m+ -> 1m28s at -P 8.
#
#   scripts/test_all.sh              all of them
#   scripts/test_all.sh campaign     only suites whose name matches
#
# Prints nothing per passing suite. A silent run is a green run.
set -u
cd "$(dirname "$0")/.." || exit 2

match="${1:-}"
if [ -n "$match" ]; then
  files=$(ls scripts/test_*.py | grep -- "$match")
else
  files=$(ls scripts/test_*.py)
fi
[ -z "$files" ] && { echo "no suites match '$match'"; exit 2; }

total=$(printf '%s\n' $files | wc -l | tr -d ' ')
start=$(date +%s)

# `-P 8` rather than nproc: these are CPU-bound Python processes and the
# machine still has to be usable while they run.
fails=$(printf '%s\n' $files \
  | xargs -P 8 -I{} sh -c 'python3 {} >/dev/null 2>&1 || echo {}')

end=$(date +%s)
n=$(printf '%s' "$fails" | grep -c . )

if [ "$n" -eq 0 ]; then
  echo "all $total suites passed in $((end - start))s"
  exit 0
fi

echo "$n of $total FAILED in $((end - start))s:"
printf '%s\n' "$fails" | sed 's/^/  /'
echo
echo "re-run one with its own output:  python3 <path>"
exit 1
