FROM ubuntu:24.04 AS dependencies

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PATH=/opt/venv/bin:$PATH

WORKDIR /app

# Ubuntu 24.04 LTS is an officially supported Playwright 1.62 platform and
# supplies Python 3.12. Build inside a dedicated virtual environment so the
# runtime remains isolated from distro Python packages while retaining the
# vendor security feed used by the image scanner.
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get upgrade --yes \
    && DEBIAN_FRONTEND=noninteractive apt-get install --yes --no-install-recommends \
        ca-certificates \
        python3 \
        python3-venv \
    && python3 -m venv /opt/venv \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && DEBIAN_FRONTEND=noninteractive python -m playwright install --with-deps --only-shell chromium \
    && rm -rf /var/lib/apt/lists/*
# ODSS only launches Chromium's headless shell, so it does not need the
# Xvfb/Xorg server. The binary is not linked to the CUPS client library either.
# Keep those generic Playwright dependencies out of the runtime surface.
RUN apt-get purge --yes xvfb xserver-common libcups2t64
# The official Ubuntu base already reserves numeric UID/GID 1000. Use that
# non-root identity directly and give it a private application home instead of
# mutating or duplicating the distro account.
RUN install -d --owner=1000 --group=1000 --mode=0750 /home/odss
ENV HOME=/home/odss

FROM dependencies AS source

COPY --chown=odss:odss . .

FROM source AS test

USER root
RUN pip install --no-cache-dir -r requirements-dev.txt
USER 1000:1000
RUN python -m pytest -q && touch /tmp/odss-tests-passed

FROM dependencies AS runtime

# Runtime receives only the service tree plus the one post-build browser probe;
# the full test suite never ships in the production image. Both copies come
# from the same source stage whose complete suite produced this marker.
COPY --from=source --chown=1000:1000 /app/app ./app
COPY --from=source --chown=1000:1000 /app/VERSION ./VERSION
COPY --from=source --chown=1000:1000 /app/tests/check_webgl_runtime.py ./tests/check_webgl_runtime.py
COPY --from=test /tmp/odss-tests-passed /app/.tests-passed

USER 1000:1000
EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
