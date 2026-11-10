# González Cardona · Architectural AI Visualizer — complete local app in one container.
#
# Blender publishes Linux builds for x86-64 only, so the image is linux/amd64. On Apple Silicon
# Docker Desktop runs it under emulation: rendering is CPU-only and slower than the native app.
# Secrets are never baked in: OPENAI_API_KEY comes from `.env` at run time (see README).

# Blender has no Linux arm64 build, so every stage is x86-64 (emulated on Apple Silicon).
ARG PLATFORM=linux/amd64
ARG BLENDER_VERSION=4.5.9
ARG LIBREDWG_VERSION=0.14

# --- 1. Web app: production build plus the Node packages the model scripts need -------------
FROM --platform=$PLATFORM node:24-bookworm-slim AS site
WORKDIR /app/site
COPY site/package.json site/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY site/ ./
RUN npm run build

# --- 2. LibreDWG dwg2dxf: local DWG → DXF conversion (no cloud converter) ---------------------
FROM --platform=$PLATFORM debian:bookworm-slim AS libredwg
ARG LIBREDWG_VERSION
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential ca-certificates curl pkg-config python3 xz-utils \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /build
RUN curl -fsSL "https://ftp.gnu.org/gnu/libredwg/libredwg-${LIBREDWG_VERSION}.tar.xz" | tar -xJ \
    && cd "libredwg-${LIBREDWG_VERSION}" \
    && ./configure --prefix=/opt/libredwg --disable-bindings --disable-docs --disable-dependency-tracking \
    && make -j"$(nproc)" \
    && make install \
    && rm -rf /opt/libredwg/share

# --- 3. Blender LTS (headless; Cycles on CPU) ------------------------------------------------
FROM --platform=$PLATFORM debian:bookworm-slim AS blender
ARG BLENDER_VERSION
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl xz-utils \
    && rm -rf /var/lib/apt/lists/*
RUN curl -fsSL "https://download.blender.org/release/Blender${BLENDER_VERSION%.*}/blender-${BLENDER_VERSION}-linux-x64.tar.xz" \
    | tar -xJ -C /opt \
    && mv "/opt/blender-${BLENDER_VERSION}-linux-x64" /opt/blender

# --- 4. Runtime ------------------------------------------------------------------------------
FROM --platform=$PLATFORM python:3.12-slim-bookworm AS runtime
ARG AAV_REVISION=unknown
# Shared libraries Blender needs in background mode, and fonts for drawing DWG plan sheets.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        fonts-dejavu-core fonts-liberation \
        libegl1 libgl1 libglib2.0-0 libice6 libsm6 libx11-6 libxext6 libxfixes3 libxi6 \
        libxkbcommon0 libxrender1 libxxf86vm1 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.13.0 /uv /usr/local/bin/uv
COPY --from=node:24-bookworm-slim /usr/local/bin/node /usr/local/bin/node
COPY --from=blender /opt/blender /opt/blender
COPY --from=libredwg /opt/libredwg /opt/libredwg

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

COPY --from=site /app/site /app/site
COPY pipelines/ /app/pipelines/
COPY scripts/ /app/scripts/
COPY docs/PROMPT_STYLE.md /app/docs/PROMPT_STYLE.md

RUN useradd --create-home --uid 1000 aav && mkdir -p /data && chown aav:aav /data
USER aav

ENV PATH="/app/.venv/bin:/opt/libredwg/bin:${PATH}" \
    LD_LIBRARY_PATH="/opt/libredwg/lib" \
    BLENDER_BIN="/opt/blender/blender" \
    DWG2DXF="/opt/libredwg/bin/dwg2dxf" \
    MPLCONFIGDIR="/tmp/matplotlib" \
    PYTHONUNBUFFERED=1 \
    AAV_REVISION="${AAV_REVISION}"

VOLUME ["/data"]
EXPOSE 5174
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5174/api/health', timeout=4)"
CMD ["python", "-m", "pipelines.web.server", "--host", "0.0.0.0", "--port", "5174", \
     "--data-dir", "/data", "--site-root", "/app/site"]
