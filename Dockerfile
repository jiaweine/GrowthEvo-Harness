FROM python:3.13-slim@sha256:7c61056e61ac89e852de05f3dc6fa51a6dd2181797bceed46aa725dd7cb2cd3b

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    GROWTHEVO_HOST=0.0.0.0 \
    GROWTHEVO_PORT=8765

WORKDIR /app

COPY pyproject.toml README.md ./
COPY growthevo ./growthevo
RUN python -m pip install --disable-pip-version-check '.[web]'

RUN useradd --create-home --uid 10001 growthevo && chown -R growthevo:growthevo /app
USER growthevo

EXPOSE 8765

# Liveness stays available at /api/health for diagnostics, while the container
# health contract follows readiness so a fail-closed production process cannot
# be advertised as traffic-ready merely because the Python process is alive.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/api/ready', timeout=3)" || exit 1

CMD ["growthevo-web"]
