FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml wsgi.py ./

COPY rrserver ./rrserver

RUN pip install --no-cache-dir .

COPY . .

RUN useradd --create-home --uid 10001 recnet \
    && mkdir -p /app/instance \
    && chown -R recnet:recnet /app \
    && chmod 755 /app/instance

USER recnet

EXPOSE 5000

CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "1", "--threads", "100", "--access-logfile", "-", "wsgi:app"]
