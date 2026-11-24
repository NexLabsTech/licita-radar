FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 APP_ENV=production COOKIE_SECURE=1 DB_PATH=/app/data/licitaradar.db
WORKDIR /app
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt && groupadd -r radar && useradd -r -g radar radar \
    && mkdir -p /app/data && chown radar:radar /app/data
COPY app/ /app/app/
USER radar
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
