FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    JOB_DATA_PATH=/data/latest_jobs.json

WORKDIR /app

COPY requirements-scraper.txt .
RUN pip install --upgrade pip \
    && pip install -r requirements-scraper.txt \
    && playwright install --with-deps chromium

COPY . .

RUN useradd --create-home --shell /usr/sbin/nologin appuser \
    && mkdir -p /data \
    && chown -R appuser:appuser /app /data /ms-playwright

USER appuser

VOLUME ["/data"]

CMD ["python", "run_scrapers.py"]
