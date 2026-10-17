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
        ros-jazzy-demo-nodes-py \
        ros-jazzy-rosbag2 \
        ros-jazzy-rosbag2-storage-default-plugins \
        ros-jazzy-example-interfaces \
    && rm -rf /var/lib/apt/lists/*

COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

WORKDIR /ws
ENTRYPOINT ["/entrypoint.sh"]
CMD ["bash"]
