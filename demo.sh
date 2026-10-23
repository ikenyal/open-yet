#!/bin/zsh
# Demo for the video. Same fictional challenge, opening a few minutes from now.
#   ./demo.sh before        -> the original function `open-yet` (no tool)
#   ./demo.sh after         -> `open-yet-remind`, asked to be told when it opens
# Env: AWS_PROFILE, MINUTES (default 4)
set -euo pipefail
MODE=${1:?before or after}
export AWS_REGION=us-east-1
MIN=${MINUTES:-4}
OPENS=$(date -u -v+${MIN}M +"%B %-d, %Y at %H:%M UTC")
CLOSES=$(date -u -v+3d +"%B %-d, %Y at %H:%M UTC")
TEXT="Weekend Challenge: Demo. Entries open $OPENS and close $CLOSES. Required tag: #demo."
REQUEST="Can you let me know when it opens?"

if [[ $MODE == before ]]; then FN=open-yet; REQ=""; else FN=open-yet-remind; REQ=$REQUEST; fi

echo "\$ $FN"
echo "> $TEXT"
[[ -n $REQ ]] && echo "> $REQ"
echo
TMP=$(mktemp -d)
TEXT="$TEXT" REQ="$REQ" python3 -c '
import json, os
b = {"text": os.environ["TEXT"], "timezone": "Asia/Tokyo"}
if os.environ["REQ"]: b["request"] = os.environ["REQ"]
print(json.dumps({"body": json.dumps(b)}))' > $TMP/p.json
aws lambda invoke --function-name $FN --cli-binary-format raw-in-base64-out \
  --payload file://$TMP/p.json --cli-read-timeout 120 $TMP/out.json >/dev/null
python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['body'])" $TMP/out.json
