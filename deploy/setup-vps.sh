#!/usr/bin/env bash
# Первичная настройка чистого VPS (Ubuntu 22.04+/Debian 12+) под tg-assistant.
# Запуск от root:
#   curl -fsSL https://raw.githubusercontent.com/imtrtd/tg-assistant/main/deploy/setup-vps.sh | bash
# Скрипт можно запускать повторно: он обновит код и ничего не сломает.
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/imtrtd/tg-assistant.git}"
APP_DIR="${APP_DIR:-/opt/tg-assistant}"
# Автообновление из main раз в 10 минут (таймер systemd). AUTO_UPDATE=0 — не ставить.
AUTO_UPDATE="${AUTO_UPDATE:-1}"

if [ "$(id -u)" -ne 0 ]; then
    echo "Запустите скрипт от root: sudo bash $0" >&2
    exit 1
fi

echo "==> Пакеты"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq git curl ca-certificates

if ! command -v docker >/dev/null 2>&1; then
    echo "==> Docker"
    curl -fsSL https://get.docker.com | sh
fi
systemctl enable --now docker

# На маленьких VPS (1 ГБ ОЗУ и меньше) сборка образа может не поместиться в память.
if [ "$(swapon --noheadings | wc -l)" -eq 0 ] && [ ! -f /swapfile ]; then
    echo "==> Файл подкачки 1 ГБ"
    fallocate -l 1G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile >/dev/null
    swapon /swapfile
    echo "/swapfile none swap sw 0 0" >> /etc/fstab
fi

echo "==> Код в $APP_DIR"
if [ -d "$APP_DIR/.git" ]; then
    git -C "$APP_DIR" pull --ff-only
else
    git clone "$REPO_URL" "$APP_DIR"
fi

cd "$APP_DIR"
mkdir -p data backups
# Контейнер работает от пользователя с uid 1000 — ему нужен доступ к базе.
chown -R 1000:1000 data

if [ "$AUTO_UPDATE" = "1" ]; then
    echo "==> Автообновление: таймер tg-assistant-update (раз в 10 минут)"
    cat > /etc/systemd/system/tg-assistant-update.service <<UNIT
[Unit]
Description=tg-assistant: update from GitHub if main changed
After=network-online.target docker.service
Wants=network-online.target

[Service]
Type=oneshot
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/deploy/auto-update.sh
UNIT
    cat > /etc/systemd/system/tg-assistant-update.timer <<UNIT
[Unit]
Description=tg-assistant: check for updates every 10 minutes

[Timer]
OnBootSec=5min
OnUnitActiveSec=10min
RandomizedDelaySec=60

[Install]
WantedBy=timers.target
UNIT
    systemctl daemon-reload
    systemctl enable --now tg-assistant-update.timer
else
    systemctl disable --now tg-assistant-update.timer 2>/dev/null || true
fi

if [ ! -f .env ]; then
    cp .env.example .env
    chmod 600 .env
    cat <<MSG

Готово. Осталось два шага:

  1. Впишите токен бота и свой Telegram id:
       nano $APP_DIR/.env
  2. Запустите бота:
       cd $APP_DIR && docker compose up -d --build

Логи:        docker compose logs -f
Обновление:  само, раз в 10 минут (журнал: journalctl -u tg-assistant-update)
             или вручную: $APP_DIR/deploy/update.sh
MSG
else
    echo "==> .env уже есть, пересобираю и перезапускаю бота"
    docker compose up -d --build
fi
