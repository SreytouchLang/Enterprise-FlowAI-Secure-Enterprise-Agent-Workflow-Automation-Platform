FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /srv/api
COPY apps/api/pyproject.toml apps/api/requirements.lock ./
RUN pip install -r requirements.lock
COPY apps/api/app ./app
COPY apps/api/alembic.ini ./
COPY apps/api/alembic ./alembic
COPY infrastructure/docker/bootstrap_database.py ./bootstrap_database.py
COPY infrastructure/docker/create_bucket.py ./create_bucket.py
COPY demo-data /srv/demo-data
RUN pip install --no-deps . && useradd --create-home --uid 10001 appuser && mkdir -p /srv/api/data && chown appuser:appuser /srv/api/data
USER appuser
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--proxy-headers", "--forwarded-allow-ips", "*"]
