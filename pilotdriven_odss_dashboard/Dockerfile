FROM python:3.12.13-slim-trixie

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && DEBIAN_FRONTEND=noninteractive python -m playwright install --with-deps --only-shell chromium \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 1000 odss \
    && useradd --uid 1000 --gid 1000 --no-create-home --home-dir /app --shell /usr/sbin/nologin odss
# ODSS only launches Chromium's headless shell, so it does not need the
# Xvfb/Xorg server. The binary is not linked to the CUPS client library either.
# Keep those generic Playwright dependencies out of the runtime surface.
RUN apt-get purge --yes xvfb xserver-common libcups2t64
RUN usermod --home /home/odss odss \
    && install -d --owner=odss --group=odss --mode=0750 /home/odss
ENV HOME=/home/odss
COPY --chown=odss:odss . .
USER 1000:1000
EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
