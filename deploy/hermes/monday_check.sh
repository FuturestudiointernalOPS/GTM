#!/usr/bin/env bash
# Launcher for the Monday technical check, called by a Hermes cron job.
# Hermes only runs scripts from ~/.hermes/scripts/, so this file is copied there
# from the repo (see docs/infra.md). The code itself stays in the repo.
set -euo pipefail

cd "$HOME/GTMTool/GTM"
exec .venv/bin/python -m workflows.monday_check
