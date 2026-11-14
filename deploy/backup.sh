#!/usr/bin/env bash
# Согласованная копия базы SQLite в backups/ (можно запускать при работающем боте).
# Хранятся последние KEEP копий. Пример для cron, каждый день в 4:00:
#   0 4 * * * /opt/tg-assistant/deploy/backup.sh >/dev/null
set -euo pipefail
cd "$(dirname "$0")/.."

KEEP="${KEEP:-14}"
name="bot-$(date +%Y%m%d-%H%M%S).db"

docker compose exec -T bot python - "$name" <<'PY'
import sqlite3
import sys

src = sqlite3.connect("/app/data/bot.db")
dst = sqlite3.connect(f"/app/data/{sys.argv[1]}")
with dst:
    src.backup(dst)
dst.close()
src.close()
PY

mkdir -p backups
mv "data/$name" "backups/$name"
ls -1t backups/bot-*.db | tail -n +"$((KEEP + 1))" | xargs -r rm --
echo "backups/$name"
