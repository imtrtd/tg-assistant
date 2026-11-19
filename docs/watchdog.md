# Сторож, healthchecks.io и бэкапы в Telegram

Работает на любом хостинге: Docker на ПК или VPS, Railway, облако из [failover.md](failover.md).

## Зависания

Бот раз в 30 секунд пишет время в `data/heartbeat` (`HEARTBEAT_FILE`).

* Отдельный поток-сторож завершает процесс, если цикл событий не отвечал больше 2 минут.
  Docker (`restart: unless-stopped`), systemd или Railway сразу запускают бота заново.
* В образе есть `HEALTHCHECK`: `docker ps` покажет `unhealthy`, если отметок нет.
  Проверка вручную: `python -m tg_assistant.ops healthcheck` (код выхода 0 — всё хорошо).

## Если выключено всё

Сторож не поможет, если выключен сам сервер. Для этого есть внешняя проверка:

1. Зарегистрируйтесь на [healthchecks.io](https://healthchecks.io) (бесплатно до 20 проверок).
2. Add Check: Period — 1 минута, Grace — 3 минуты.
3. Integrations → Telegram — подключите своего Telegram.
4. Скопируйте адрес проверки (`https://hc-ping.com/...`) в `HEALTHCHECK_PING_URL`.

Пингует только узел, который сейчас работает. При переключении ПК ↔ облако пинги
не прерываются; если не работает ни один узел, через ~4 минуты придёт сообщение.

## Уведомления администраторам

`ADMIN_IDS` получают:

* «Бот работает на узле …» — при запуске и при каждом переключении ПК ↔ облако;
* ошибки обработчиков (не чаще раза в минуту, как и раньше);
* бэкап базы файлом `tg-assistant-ГГГГММДД-ЧЧММ.json.gz` раз в `BACKUP_INTERVAL_HOURS`
  (по умолчанию 24, 0 — выключить). Время последнего бэкапа хранится в базе, поэтому при
  переключении узлов копии не дублируются.

Бэкап одинаков для SQLite и Postgres. Восстановление в пустую базу из `DATABASE_URL`:

```bash
python -m tg_assistant.backup restore tg-assistant-20261118-0930.json.gz
# в Docker:
docker compose run --rm -v "$PWD:/restore" bot \
  python -m tg_assistant.backup restore /restore/tg-assistant-20261118-0930.json.gz
```

Выгрузить вручную: `python -m tg_assistant.backup export backup.json.gz`.
Telegram принимает от ботов файлы до 50 МБ; если архив чатов вырастет больше, бот сообщит
об этом — тогда ограничьте `ARCHIVE_RETENTION_DAYS`.
