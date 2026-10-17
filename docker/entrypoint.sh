#!/bin/bash
# Shared entrypoint for all compose services.
#  - sources ROS 2 Jazzy
#  - if ROSHANAVI_BUILD=1, builds the workspace (/ws/src -> /ws/install) first
#  - sources the workspace overlay when present, then execs the command
set -e
# shellcheck disable=SC1091
source /opt/ros/jazzy/setup.bash

if [ "${ROSHANAVI_BUILD:-0}" = "1" ]; then
    cd /ws
    if ! colcon build --event-handlers console_direct- > /tmp/colcon_build.log 2>&1; then
        echo "colcon build failed:" >&2
        tail -n 40 /tmp/colcon_build.log >&2
        exit 1
    fi
    echo "colcon build ok" >&2
fi

if [ -f /ws/install/setup.bash ]; then
    # shellcheck disable=SC1091
    source /ws/install/setup.bash
fi
exec "$@"
