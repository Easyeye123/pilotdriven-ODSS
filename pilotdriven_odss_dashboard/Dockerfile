# The custom OCR component is built from immutable upstream source and tested
# before it can enter the shared runtime foundation. See ocr/README.md.
FROM ubuntu:24.04@sha256:534baea6a22c03a63003dbc8dbe78fe34bc0d7e595d9a9dc9834884ff530eb55 AS ocr-build
WORKDIR /ocr-build
COPY ocr ./ocr
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install --yes --no-install-recommends \
        ca-certificates python3 \
        build-essential=12.10ubuntu1 \
        g++=4:13.2.0-7ubuntu1 \
        g++-13=13.3.0-6ubuntu2~24.04.1 \
        gcc-13=13.3.0-6ubuntu2~24.04.1 \
        libstdc++-13-dev=13.3.0-6ubuntu2~24.04.1 \
        libc6-dev=2.39-0ubuntu8.9 \
        cmake=3.28.3-1build7 \
        ninja-build=1.11.1-2 \
        pkg-config=1.8.1-2build1 \
        libleptonica-dev=1.82.0-3build4 \
        libicu-dev=74.2-1ubuntu3.1 \
        libarchive-dev=3.7.2-2ubuntu0.9 \
        libcurl4-openssl-dev=8.5.0-2ubuntu10.16 \
        libcurl4t64=8.5.0-2ubuntu10.16 \
    && python3 ocr/build_component.py

FROM ubuntu:24.04@sha256:534baea6a22c03a63003dbc8dbe78fe34bc0d7e595d9a9dc9834884ff530eb55 AS dependencies

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PATH=/opt/venv/bin:$PATH \
    TESSDATA_PREFIX=/usr/share/tesseract-ocr/5/tessdata

WORKDIR /app
COPY --from=ocr-build /ocr-out/pilotdriven-tesseract.deb /tmp/pilotdriven-tesseract.deb

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
        /tmp/pilotdriven-tesseract.deb \
    && python3 /usr/share/pilotdriven-tesseract/verify_component.py \
    && rm /tmp/pilotdriven-tesseract.deb \
    && python3 -m venv /opt/venv \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && DEBIAN_FRONTEND=noninteractive python -m playwright install --with-deps --only-shell chromium \
    && rm -rf /var/lib/apt/lists/*
# ODSS only launches Chromium's headless shell, so it does not need the
# Xvfb/Xorg server. The binary is not linked to the CUPS client library either.
# The venv is already populated, so the distro venv bootstrap wheels are also
# build-only inputs. Remove all of them from the shared runtime foundation.
RUN apt-get purge --yes \
        libcups2t64 \
        python3-pip-whl \
        python3-setuptools-whl \
        python3-venv \
        python3.12-venv \
        xserver-common \
        xvfb \
    && rm -rf /var/lib/apt/lists/*
# The official Ubuntu base already reserves numeric UID/GID 1000. Use that
# non-root identity directly and give it a private application home instead of
# mutating or duplicating the distro account.
RUN install -d --owner=1000 --group=1000 --mode=0750 /home/odss
ENV HOME=/home/odss

FROM dependencies AS source

COPY --chown=1000:1000 . .

FROM source AS test

USER root
RUN pip install --no-cache-dir -r requirements-dev.txt
USER 1000:1000
# The private corpus is a read-only build context, not a credential-sized secret.
# Bind the test result to its checksum and never copy this input into a layer.
ARG SAVED_ANALYSIS_BUNDLE_SHA256
RUN --mount=type=bind,from=saved_analyses,source=saved-analysis-v74.tar,target=/run/private-test-inputs/saved-analysis-v74.tar,readonly \
    printf '%s  %s\n' "$SAVED_ANALYSIS_BUNDLE_SHA256" /run/private-test-inputs/saved-analysis-v74.tar | sha256sum --check --status \
    && PILOTDRIVEN_SAVED_ANALYSIS_BUNDLE=/run/private-test-inputs/saved-analysis-v74.tar python -m pytest -q \
    && touch /tmp/odss-tests-passed

FROM dependencies AS runtime

# Runtime receives only the service tree plus the one post-build browser probe;
# the full test suite never ships in the production image. Both copies come
# from the same source stage whose complete suite produced this marker.
COPY --from=source --chown=1000:1000 /app/app ./app
COPY --from=source --chown=1000:1000 /app/VERSION ./VERSION
COPY --from=source --chown=1000:1000 /app/tests/check_webgl_runtime.py ./tests/check_webgl_runtime.py
COPY --from=source --chown=1000:1000 /app/tests/check_ocr_runtime.py ./tests/check_ocr_runtime.py
COPY --from=test /tmp/odss-tests-passed /app/.tests-passed

USER 1000:1000
EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
