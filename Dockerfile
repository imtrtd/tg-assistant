FROM python:3.12-slim

# cloudflared 2025.8.0 — тот же выпуск, что у сервиса в docker-compose.
# Нужен, чтобы контейнер сам открыл HTTPS для мини-приложения в Telegram.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && arch="$(dpkg --print-architecture)" \
    && case "$arch" in \
         amd64) file=cloudflared-linux-amd64; \
                sum=c7d3a69da0f7b9b1bc1ddcb0597d3552bcd7c15f8bbaba463dc489b94b7544ee ;; \
         arm64) file=cloudflared-linux-arm64; \
                sum=733909afee6b3577f20f6fa092e649e8ca47d72214c5a70d47e4f59e6697d005 ;; \
         *) echo "unsupported architecture: $arch" >&2; exit 1 ;; \
       esac \
    && curl -fsSL -o /usr/local/bin/cloudflared \
         "https://github.com/cloudflare/cloudflared/releases/download/2025.8.0/${file}" \
    && echo "${sum}  /usr/local/bin/cloudflared" | sha256sum -c - \
    && chmod 755 /usr/local/bin/cloudflared \
    && apt-get purge -y curl \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install .

# База SQLite лежит в /app/data — сюда монтируется том (docker-compose, Railway).
RUN useradd --create-home --uid 1000 bot \
    && mkdir -p /app/data \
    && chown -R bot:bot /app
USER bot

# Бот раз в 30 с обновляет data/heartbeat; нет отметки 2 минуты — контейнер unhealthy.
# Зависший цикл событий бот завершает сам, и Docker перезапускает его (restart: unless-stopped).
HEALTHCHECK --interval=60s --timeout=10s --start-period=60s --retries=2 \
    CMD ["python", "-m", "tg_assistant.ops", "healthcheck"]

CMD ["python", "-m", "tg_assistant"]
