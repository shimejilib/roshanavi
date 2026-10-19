#!/usr/bin/env bash
# Record docs/images/demo.gif: the live map with flowing edges, then an input node being
# created. Playwright records a video against an isolated lab-e2e stack (never the user's lab),
# ffmpeg turns it into a GIF (<= 15 s, <= 4 MB).
#
#   ROSHANAVI_IMAGE=roshanavi:mygif COMPOSE_PROJECT_NAME=roshanavi-mygif \
#   ROS_DOMAIN_ID=91 E2E_ROS_DOMAIN_ID=92 scripts/record_demo_gif.sh
#
# Needs docker, ffmpeg and `cd web && npm ci` (the Playwright runner mounts web/node_modules).
set -euo pipefail
cd "$(dirname "$0")/.."
export UID GID="$(id -g)"
export ROS_DISTRO="${ROS_DISTRO:-jazzy}"
export ROSHANAVI_IMAGE="${ROSHANAVI_IMAGE:-roshanavi:dev-${ROS_DISTRO}}"
export E2E_VIZ=0  # the test-only image publisher is not part of the demo
OUT="docs/images/demo.gif"
WORK="$(mktemp -d)"
DC=(docker compose --profile e2e)
SERVICES=(lab-e2e demo-e2e e2e)

cleanup() {
    "${DC[@]}" rm -sfv "${SERVICES[@]}" >/dev/null 2>&1 || true
    rm -rf "$WORK" web/demo-gif/out
}
trap cleanup EXIT

command -v ffmpeg >/dev/null || { echo "ffmpeg is needed" >&2; exit 1; }
rm -rf web/demo-gif/out
"${DC[@]}" up -d --build lab-e2e demo-e2e
"${DC[@]}" run --rm -e DEMO_GIF_OUT=/repo/web/demo-gif/out e2e \
    npx playwright test -c demo-gif/playwright.config.ts

video="$(find web/demo-gif/out -name '*.webm' | head -n 1)"
[ -n "$video" ] || { echo "no video was recorded" >&2; exit 1; }
cp "$video" "$WORK/in.webm"

# Two-pass GIF: a palette built from the video keeps the file small and the colours clean.
filters="fps=10,scale=960:-1:flags=lanczos"
ffmpeg -v error -y -t 15 -i "$WORK/in.webm" -vf "$filters,palettegen=max_colors=96:stats_mode=diff" "$WORK/palette.png"
ffmpeg -v error -y -t 15 -i "$WORK/in.webm" -i "$WORK/palette.png" \
    -lavfi "$filters [x]; [x][1:v] paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle" "$OUT"
size=$(stat -c %s "$OUT")
echo "wrote $OUT ($((size / 1024)) KiB)" >&2
if [ "$size" -gt $((4 * 1024 * 1024)) ]; then
    echo "FAIL: the GIF is larger than 4 MB; lower fps / scale in this script" >&2
    exit 1
fi
