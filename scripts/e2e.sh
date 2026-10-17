#!/usr/bin/env bash
# Run the whole Playwright E2E against an isolated stack (lab-e2e + demo-e2e on their own
# ROS_DOMAIN_ID, fresh tmpfs /data, no published port), then tear everything down.
# The user's `lab` / `demo` and ./data are never touched; the script verifies that.
# ROS_DISTRO (default jazzy) picks the distro of lab-e2e / demo-e2e (image roshanavi:dev-<distro>),
# e.g. `ROS_DISTRO=lyrical scripts/e2e.sh`. The user's lab keeps running whatever it runs.
set -u
cd "$(dirname "$0")/.."
export UID GID="$(id -g)"
export ROS_DISTRO="${ROS_DISTRO:-jazzy}"
# Passed through to compose so a second checkout / git worktree can run its own isolated stack
# next to the lab: ROSHANAVI_IMAGE (image tag), COMPOSE_PROJECT_NAME, E2E_ROS_DOMAIN_ID.
export ROSHANAVI_IMAGE="${ROSHANAVI_IMAGE:-roshanavi:dev-${ROS_DISTRO}}"
echo "E2E on ROS 2 ${ROS_DISTRO}" >&2
DC=(docker compose --profile e2e)
proj_hash() { docker compose exec -T lab sha256sum /data/roshanavi.yaml 2>/dev/null | cut -d' ' -f1; }

SERVICES=(lab-e2e demo-e2e e2e)
# Never `down`: that would also stop the user's lab / demo. Remove only the e2e services + volume.
cleanup() {
    "${DC[@]}" rm -sfv "${SERVICES[@]}" >/dev/null 2>&1
    docker volume ls -q --filter label=com.docker.compose.volume=e2e-media \
        --filter "label=com.docker.compose.project=$(docker compose config --format json | python3 -c 'import json,sys;print(json.load(sys.stdin)["name"])')" \
        | xargs -r docker volume rm >/dev/null 2>&1
}

before="$(proj_hash)"
cleanup
"${DC[@]}" up --build --abort-on-container-exit --exit-code-from e2e "${SERVICES[@]}"
code=$?
cleanup

after="$(proj_hash)"
if [ "$before" != "$after" ]; then
    echo "FAIL: ./data/roshanavi.yaml of the user's lab changed during E2E ($before -> $after)" >&2
    exit 1
fi
exit "$code"
