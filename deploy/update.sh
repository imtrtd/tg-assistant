#!/usr/bin/env bash
# Обновить бота на VPS до последней версии main: копия базы, код, пересборка, перезапуск.
set -euo pipefail
cd "$(dirname "$0")/.."

./deploy/backup.sh || echo "Копию базы сделать не удалось (бот не запущен?), продолжаю" >&2
git pull --ff-only
docker compose up -d --build
docker image prune -f >/dev/null
docker compose ps
