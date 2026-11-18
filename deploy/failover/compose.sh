#!/usr/bin/env bash
# docker compose для схемы «ПК + облако» с .env из корня репозитория.
#   deploy/failover/compose.sh up -d --build
#   deploy/failover/compose.sh logs -f bot
set -euo pipefail
cd "$(dirname "$0")/../.."
[ -f .env ] || { echo ".env not found in $(pwd)" >&2; exit 1; }
exec docker compose --env-file .env -f deploy/failover/docker-compose.yml "$@"
