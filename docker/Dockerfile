# ---- stage 1: build the web UI (Vite + React) -------------------------------
FROM node:24.14.0-bookworm-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npx tsc --noEmit -p tsconfig.json && npx vite build --outDir /out --emptyOutDir

# ---- stage 2: ROS 2 runtime ---------------------------------------------------
FROM ros:jazzy-ros-base

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3-fastapi \
        python3-uvicorn \
        python3-pydantic \
        python3-httpx \
        python3-websockets \
        python3-pytest \
        python3-yaml \
        python3-psutil \
        python3-pil \
        python3-numpy \
        ffmpeg \
        ros-jazzy-demo-nodes-cpp \
        ros-jazzy-demo-nodes-py \
        ros-jazzy-rosbag2 \
        ros-jazzy-rosbag2-storage-default-plugins \
        ros-jazzy-example-interfaces \
        ros-jazzy-audio-common-msgs \
        ros-jazzy-lifecycle \
    && rm -rf /var/lib/apt/lists/*

# Built UI baked into the image; the server picks it up via ROSHANAVI_STATIC_DIR
# (the workspace source is bind-mounted, so package data cannot be relied on here).
COPY --from=web /out /opt/roshanavi/static
ENV ROSHANAVI_STATIC_DIR=/opt/roshanavi/static

COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

WORKDIR /ws
ENTRYPOINT ["/entrypoint.sh"]
CMD ["bash"]
