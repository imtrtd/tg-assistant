# ПК + облако: бот работает, даже когда компьютер выключен

Два экземпляра бота с одной общей базой Postgres:

| Узел | Где | Приоритет | Когда работает |
|---|---|---|---|
| `pc` | локальный VPS на компьютере (Multipass) | 10 | всегда, когда компьютер включён |
| `oracle` | Oracle Cloud Always Free | 0 | только пока ПК выключен или без сети |

Заметки, напоминания и архив лежат в Postgres на облачном сервере, поэтому оба узла видят
одни и те же данные. Отвечает в Telegram и рассылает напоминания всегда ровно один узел —
лидер.

```
             Telegram
            ▲        ▲
   getUpdates        getUpdates (только лидер)
            │        │
   ┌────────┴──┐  ┌──┴────────────────────────────┐
   │ ПК: bot   │  │ Oracle: bot   postgres  backup │
   │ db-access ├──► Cloudflare ──► db-tunnel ──┘   │
   └───────────┘  └────────────────────────────────┘
```

## Как узлы договариваются

Код — `src/tg_assistant/leader.py`, включается сам, если `DATABASE_URL` указывает на Postgres.

* Лидер держит advisory-блокировку Postgres (`pg_try_advisory_lock`). Блокировка привязана
  к соединению: если узел выключился или пропала сеть, база снимает её сама (~30 секунд
  благодаря TCP keepalive).
* Узлы раз в `LEADER_INTERVAL` секунд (по умолчанию 10) отмечаются в таблице `cluster_nodes`.
* Облако, будучи лидером, видит, что ПК снова в сети (приоритет выше), останавливает бота
  и отпускает блокировку — ПК подхватывает через 10–20 секунд.
* Если лидер потерял связь с базой, он сразу останавливает бота: двое одновременно не работают.

Переключение занимает до ~40 секунд. Сообщения, присланные в это время, не теряются:
Telegram хранит их, и новый лидер получит их при первом запросе.

## 1. Сервер Oracle Cloud (делаете вы)

1. Зарегистрируйтесь на [cloud.oracle.com](https://signup.cloud.oracle.com/) (нужна карта для
   проверки, списаний на Always Free нет). Домашний регион выбирается один раз — берите
   ближайший с ARM-машинами, например Frankfurt.
2. Compute → Instances → Create instance:
   образ Ubuntu 24.04, форма `VM.Standard.A1.Flex` (1–2 OCPU, 6–12 ГБ — это бесплатно),
   добавьте свой публичный SSH-ключ. Если ARM нет в наличии — `VM.Standard.E2.1.Micro`.
3. Входящие порты открывать не нужно — всё идёт через исходящие соединения.

## 2. Облачный узел

```bash
curl -fsSL https://raw.githubusercontent.com/imtrtd/tg-assistant/main/deploy/setup-vps.sh | sudo bash
cd /opt/tg-assistant && sudo nano .env
```

В `.env` (кроме `TELEGRAM_BOT_TOKEN`, `ALLOWED_USER_IDS`, `ADMIN_IDS`, `DEFAULT_TIMEZONE`):

```ini
COMPOSE_PROFILES=db
NODE_NAME=oracle
NODE_PRIORITY=0
POSTGRES_PASSWORD=<длинный случайный: openssl rand -hex 24>
DATABASE_URL=postgresql+asyncpg://tga:<тот же пароль>@postgres:5432/tga
CF_TUNNEL_TOKEN=<токен туннеля, шаг 3>
```

```bash
deploy/failover/compose.sh up -d --build
deploy/failover/compose.sh logs -f bot   # «Node oracle ... is the leader: bot started»
```

## 3. Cloudflare: доступ ПК к базе

В Zero Trust (или через API):

1. Networks → Tunnels → Create tunnel `tga-db` (cloudflared). Токен — в `CF_TUNNEL_TOKEN`.
2. Public hostname: `db.<домен>` → сервис `TCP`, адрес `postgres:5432`.
3. Access → Service Auth → Service Tokens → Create: `tga-pc`. Client ID и Secret — для ПК.
4. Access → Applications → Self-hosted `db.<домен>`, политика `Service Auth` с этим токеном.

## 4. Узел на ПК

В локальном VPS, в каталоге бота, `.env`:

```ini
COMPOSE_PROFILES=remote-db
NODE_NAME=pc
NODE_PRIORITY=10
DATABASE_URL=postgresql+asyncpg://tga:<пароль>@db-access:5432/tga
DB_HOSTNAME=db.<домен>
CF_ACCESS_CLIENT_ID=<Client ID>
CF_ACCESS_CLIENT_SECRET=<Client Secret>
```

```bash
deploy/failover/compose.sh up -d --build
```

Через 10–20 секунд в логах облака появится `Node pc has higher priority: handing over
leadership`, а на ПК — `Node pc (priority 10) is the leader`.

Кто сейчас лидер:

```bash
deploy/failover/compose.sh exec postgres psql -U tga -c "select * from cluster_nodes"
```

## Перенос старых данных из SQLite

Один раз, до запуска ботов на Postgres (база должна быть пустой):

```bash
deploy/failover/compose.sh run --rm -v "$PWD/data:/app/old" bot \
  sh -c 'python -m tg_assistant.copy_db sqlite+aiosqlite:////app/old/bot.db "$DATABASE_URL"'
```

## Обновление

```bash
cd /opt/tg-assistant && git pull && deploy/failover/compose.sh up -d --build
```

Сначала обновляйте облако, потом ПК: новые миграции применяет тот, кто запустился первым.

## Копии базы

Контейнер `pg-backup` на облаке раз в сутки пишет `backups/tga-*.dump` (последние 14).
Восстановление: `pg_restore --clean -d tga backups/tga-....dump`.
