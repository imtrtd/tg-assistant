# Запуск на VPS

Бот работает в Docker: один контейнер, база SQLite в каталоге `data/` рядом с кодом.
Хватит самого маленького сервера: 1 vCPU, 512 МБ–1 ГБ ОЗУ, Ubuntu 22.04+ или Debian 12+.

## 1. Получить сервер

Бесплатные варианты (нужна регистрация и банковская карта для проверки личности):

| Провайдер | Что бесплатно | Замечания |
|---|---|---|
| Oracle Cloud Always Free | 2 ВМ AMD (1 ГБ ОЗУ) или ARM до 4 ядер / 24 ГБ, бессрочно | Самый щедрый вариант; ARM-машины не всегда есть в наличии |
| Google Cloud Free Tier | 1 ВМ e2-micro (1 ГБ ОЗУ) в регионах us-west1 / us-central1 / us-east1, бессрочно | Исходящий трафик свыше 1 ГБ/мес платный |
| AWS / Azure | Ограниченный срок (стартовые кредиты или 12 месяцев) | Потом платно |

Условия бесплатных тарифов меняются — сверьтесь с сайтом провайдера перед регистрацией.

При создании ВМ выберите образ Ubuntu 24.04 и добавьте свой SSH-ключ.
Входящие порты открывать не нужно: бот сам ходит в Telegram (polling).

## 2. Установить бота

Зайдите на сервер по SSH и выполните от root:

```bash
curl -fsSL https://raw.githubusercontent.com/imtrtd/tg-assistant/main/deploy/setup-vps.sh | bash
```

Скрипт ставит Docker, при необходимости добавляет 1 ГБ подкачки, клонирует репозиторий
в `/opt/tg-assistant` и создаёт `.env` из шаблона.

## 3. Настроить и запустить

```bash
nano /opt/tg-assistant/.env        # TELEGRAM_BOT_TOKEN и ALLOWED_USER_IDS
cd /opt/tg-assistant
docker compose up -d --build
docker compose logs -f             # в логе должно появиться «Bot @... started»
```

Один токен — один запущенный бот. Перед запуском на сервере остановите бота на своём
компьютере, иначе Telegram будет отдавать обновления то одному, то другому (ошибка 409 Conflict).

## Перенос базы с компьютера

Остановите бота локально и скопируйте файл базы на сервер до первого запуска:

```bash
scp data/bot.db root@СЕРВЕР:/opt/tg-assistant/data/bot.db
ssh root@СЕРВЕР chown 1000:1000 /opt/tg-assistant/data/bot.db
```

## Обновление

```bash
/opt/tg-assistant/deploy/update.sh
```

Делает копию базы, подтягивает `main`, пересобирает образ и перезапускает бота.
Миграции применяются при старте.

## Резервные копии

```bash
/opt/tg-assistant/deploy/backup.sh     # копия в backups/, хранятся последние 14
```

Ежедневно в 4:00 через cron (`crontab -e`):

```
0 4 * * * /opt/tg-assistant/deploy/backup.sh >/dev/null
```

Восстановление: `docker compose down`, скопировать нужный файл из `backups/` в `data/bot.db`,
`chown 1000:1000 data/bot.db`, `docker compose up -d`.

## Полезные команды

```bash
docker compose ps            # состояние
docker compose logs --tail 100
docker compose restart
docker compose down          # остановить
```
