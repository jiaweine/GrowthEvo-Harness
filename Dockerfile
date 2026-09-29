FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    GROWTHEVO_HOST=0.0.0.0 \
    GROWTHEVO_PORT=8765

WORKDIR /app

COPY pyproject.toml README.md ./
COPY growthevo ./growthevo
RUN python -m pip install --upgrade pip && python -m pip install '.[web]'

RUN useradd --create-home --uid 10001 growthevo && chown -R growthevo:growthevo /app
USER growthevo

EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/api/health', timeout=3)" || exit 1

CMD ["growthevo-web"]
