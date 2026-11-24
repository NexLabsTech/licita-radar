FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_ENV=production \
    COOKIE_SECURE=1 \
    DB_PATH=/app/data/licitaradar.db
WORKDIR /app
COPY requirements.txt /app/
RUN python -m pip install --no-cache-dir -r requirements.txt \
    && groupadd --gid 10001 radar \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin radar \
    && mkdir -p /app/data /app/backups \
    && chown -R radar:radar /app/data /app/backups
COPY app/ /app/app/
COPY scripts/ /app/scripts/
USER 10001:10001
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
