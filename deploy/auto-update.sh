#!/usr/bin/env bash
# Автообновление: если в origin/main появились новые коммиты, запускает deploy/update.sh
# (копия базы, git pull, пересборка, перезапуск). Без новых коммитов ничего не делает.
# Запускается таймером systemd tg-assistant-update.timer (ставит deploy/setup-vps.sh).
set -euo pipefail
cd "$(dirname "$0")/.."

# Не запускаться дважды, если прошлая сборка ещё идёт (на 1 ГБ памяти она небыстрая).
exec 9>/tmp/tg-assistant-update.lock
flock -n 9 || { echo "Обновление уже идёт"; exit 0; }

branch="${AUTO_UPDATE_BRANCH:-main}"
git fetch --quiet origin "$branch"
local_rev="$(git rev-parse HEAD)"
remote_rev="$(git rev-parse "origin/$branch")"
if [ "$local_rev" = "$remote_rev" ]; then
    exit 0
fi
# Только перемотка вперёд: локальные правки на сервере не затираем.
if ! git merge-base --is-ancestor "$local_rev" "$remote_rev"; then
    echo "На сервере есть коммиты, которых нет в origin/$branch: автообновление пропущено" >&2
    exit 1
fi
echo "Обновляю ${local_rev:0:7} -> ${remote_rev:0:7}"
./deploy/update.sh
