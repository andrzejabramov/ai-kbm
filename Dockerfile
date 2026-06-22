# Базовый образ — лёгкий Python 3.11
FROM python:3.11-slim

# Метаданные для амбассадорской публикации
LABEL maintainer="Андрей Абрамов <npkap@mail.ru>"
LABEL description="AI-Агент отдела продаж ООО «КБМ»"
LABEL version="1.0.0"

# Рабочая директория
WORKDIR /app

# Системные зависимости (минимум)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Сначала копируем requirements — кэшируется при пересборке
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем весь код
COPY . .

# Порт приложения
EXPOSE 8000

# Healthcheck — проверяем, что сервис жив
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/ || exit 1

# Запуск через gunicorn (продакшен-сервер)
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "2", "--timeout", "120", "--access-logfile", "-", "--error-logfile", "-", "app:app"]