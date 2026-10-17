ARG ROS_DISTRO=jazzy

# ---- stage 1: build the web UI (Vite + React) -------------------------------
FROM node:24.14.0-bookworm-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npx tsc --noEmit -p tsconfig.json && npx vite build --outDir /out --emptyOutDir

# ---- stage 2: ROS 2 runtime ---------------------------------------------------
# ROS_DISTRO picks the distro: jazzy (default) or lyrical (both official); kilted is verified
# once only (best effort). The base image sets ROS_DISTRO in the environment too.
FROM ros:${ROS_DISTRO}-ros-base
ARG ROS_DISTRO

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
        ros-${ROS_DISTRO}-demo-nodes-cpp \
        ros-${ROS_DISTRO}-demo-nodes-py \
        ros-${ROS_DISTRO}-rosbag2 \
        ros-${ROS_DISTRO}-rosbag2-storage-default-plugins \
        ros-${ROS_DISTRO}-example-interfaces \
        ros-${ROS_DISTRO}-audio-common-msgs \
        ros-${ROS_DISTRO}-vision-msgs \
        ros-${ROS_DISTRO}-lifecycle \
        ros-${ROS_DISTRO}-launch-pytest \
        lttng-tools \
        python3-bt2 \
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
