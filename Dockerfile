FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY shared ./shared
COPY tools ./tools
COPY tests ./tests

EXPOSE 8080

# Honour HEALTHCHECK_PORT rather than hardcoding 8080, so changing the variable
# does not leave the container reporting unhealthy while it works fine.
HEALTHCHECK --interval=60s --timeout=5s --start-period=20s \
  CMD python -c "import os, sys, urllib.request; port = os.getenv('HEALTHCHECK_PORT', '8080'); sys.exit(0 if urllib.request.urlopen(f'http://127.0.0.1:{port}/health').status == 200 else 1)" || exit 1

CMD ["python", "-m", "app.poller"]
