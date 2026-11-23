#!/usr/bin/env bash
# Weekly scored run, launched by cron on Monday morning (UTC).
#
# It sends the Playbook report with the real scores, then the drafts for every
# reachable target. Nothing is sent to a target: the drafts go to the supervisor
# for approval. The JSON summary goes to the log, not to Telegram.
set -euo pipefail

cd "$HOME/GTMTool/GTM"

if ! .venv/bin/python -m main \
  --send-telegram \
  --send-draft \
  --computed-by weekly-cron
then
  .venv/bin/python -c "from integrations import telegram; telegram.send_message_safely('GTM : le run hebdomadaire a échoué. Voir /home/hunter/gtm-weekly.log')" || true
  exit 1
fi
