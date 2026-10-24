#!/bin/zsh
# Demo for the video.
#   ./demo.sh before   -> the agent I started with (`open-yet`), a made-up challenge opening in a few minutes
#   ./demo.sh after    -> `open-yet-remind`, same kind of text, asked to be told when it opens (books an email)
#   ./demo.sh dst      -> both functions, on a window after US daylight saving ends (Nov 6, 12:00 AM PT)
# Env: AWS_PROFILE, MINUTES (default 4)
set -euo pipefail
MODE=${1:?before, after or dst}
export AWS_REGION=us-east-1
MIN=${MINUTES:-4}
REQUEST="Can you let me know when it opens?"

ask() {  # ask <function> <text> [request]
  local fn=$1 text=$2 req=${3:-}
  echo "\$ $fn"
  echo "> $text"
  [[ -n $req ]] && echo "> $req"
  echo
  local tmp=$(mktemp -d)
  TEXT="$text" REQ="$req" python3 -c '
import json, os
b = {"text": os.environ["TEXT"], "timezone": "Asia/Tokyo"}
if os.environ["REQ"]: b["request"] = os.environ["REQ"]
print(json.dumps({"body": json.dumps(b)}))' > $tmp/p.json
  aws lambda invoke --function-name $fn --cli-binary-format raw-in-base64-out \
    --payload file://$tmp/p.json --cli-read-timeout 120 $tmp/out.json >/dev/null
  python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['body'])" $tmp/out.json
}

if [[ $MODE == dst ]]; then
  TEXT="Weekend Challenge: Demo. Entries open November 6, 2026 at 12:00 AM PT and close November 9, 2026 at 1:00 PM PT."
  ask open-yet "$TEXT"
  echo "----------------------------------------"
  ask open-yet-remind "$TEXT"
  exit 0
fi

OPENS=$(date -u -v+${MIN}M +"%B %-d, %Y at %H:%M UTC")
CLOSES=$(date -u -v+3d +"%B %-d, %Y at %H:%M UTC")
TEXT="Weekend Challenge: Demo. Entries open $OPENS and close $CLOSES. Required tag: #demo."
if [[ $MODE == before ]]; then ask open-yet "$TEXT"; else ask open-yet-remind "$TEXT" "$REQUEST"; fi
