FROM python:3.12-slim

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
