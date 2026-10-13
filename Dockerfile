FROM python:3.14-slim@sha256:a2b82f3c48559aa0a8446d9af49826b6e2b2016f4cd2afabfe6013ec53729170

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    GROWTHEVO_HOST=0.0.0.0 \
    GROWTHEVO_PORT=8765

WORKDIR /app

COPY constraints/web-container-py313.txt ./constraints/web-container-py313.txt
COPY growthevo ./growthevo
# The web container runs directly from the checked-in source tree. Avoid building
# the local project through a separate PEP 517 isolation environment, whose
# setuptools/wheel resolver would otherwise sit outside the runtime lock.
#
# Provider SDK roots are pinned to the exact minimum versions continuously
# exercised by the offline SDK-floor contract. This keeps production activation
# from depending on an untested moving provider SDK while Product Surface/Stress
# rebuild the complete resolved image graph on every relevant change.
RUN python -m pip install --disable-pip-version-check \
    --constraint constraints/web-container-py313.txt \
    fastapi==0.141.1 uvicorn==0.54.0 \
    psycopg==3.3.6 psycopg-binary==3.3.6 psycopg-pool==3.3.3 \
    PyJWT==2.15.1 cryptography==50.0.2 \
    openai==2.0.0 anthropic==0.60.0 google-genai==2.22.0

RUN useradd --create-home --uid 10001 growthevo && chown -R growthevo:growthevo /app
USER growthevo

EXPOSE 8765

# Liveness stays available at /api/health for diagnostics, while the container
# health contract follows readiness so a fail-closed production process cannot
# be advertised as traffic-ready merely because the Python process is alive.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/api/ready', timeout=3)" || exit 1

CMD ["python", "-m", "growthevo.web.cli"]