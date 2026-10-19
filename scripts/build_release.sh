#!/usr/bin/env bash
# Build a release source tarball that already contains the built web UI, so that users
# who install roshanavi from source do not need Node.js / npm (docs/project/distribution.md).
#
#   scripts/build_release.sh [--no-web-build] [--ref <git-ref>]
#
# Steps:
#   1. read the version from ros2_ws/src/roshanavi/package.xml
#   2. build the web UI (npm ci + vite build) into ros2_ws/src/roshanavi/roshanavi/static
#      (the directory is git-ignored, and setup.py ships it as package data)
#   3. write dist/roshanavi-<version>.tar.gz = `git archive <ref>` (tracked files only, so no
#      .git, node_modules, build output or local data) + the built static files, under the
#      top-level folder roshanavi-<version>/
#   4. write dist/roshanavi-<version>.tar.gz.sha256
#
# Extract it into <workspace>/src/ and build as usual (docs/guide/install.md):
#   tar -xzf roshanavi-<version>.tar.gz -C ~/ros2_ws/src
#   rosdep install --ignore-src -y --from-paths <the 3 core packages>
#   colcon build --packages-up-to roshanavi
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PKG_XML="$ROOT/ros2_ws/src/roshanavi/package.xml"
STATIC_REL="ros2_ws/src/roshanavi/roshanavi/static"
STATIC_DIR="$ROOT/$STATIC_REL"
DIST_DIR="$ROOT/dist"

build_web=1
ref="HEAD"
while [ $# -gt 0 ]; do
    case "$1" in
        --no-web-build) build_web=0 ;;
        --ref) shift; ref="${1:?--ref needs a value}" ;;
        -h|--help) sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
    shift
done

for tool in git tar gzip sha256sum; do
    command -v "$tool" >/dev/null || { echo "missing tool: $tool" >&2; exit 1; }
done

# Version: the first <version> element of package.xml (the package's own, not a dependency's).
version="$(sed -n 's:.*<version>\([^<]*\)</version>.*:\1:p' "$PKG_XML" | head -n 1)"
if ! [[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+([-.+][0-9A-Za-z.]+)?$ ]]; then
    echo "cannot read a version from $PKG_XML (got '$version')" >&2
    exit 1
fi
echo "roshanavi version: $version (git ref: $ref)" >&2

if [ -n "$(git -C "$ROOT" status --porcelain --untracked-files=no)" ]; then
    echo "warning: the working tree has uncommitted changes; the tarball contains '$ref' only," >&2
    echo "         plus the static files built from the working tree's web/." >&2
fi

if [ "$build_web" -eq 1 ]; then
    command -v npm >/dev/null || { echo "npm is needed to build the web UI (or use --no-web-build)" >&2; exit 1; }
    echo "building the web UI ..." >&2
    (cd "$ROOT/web" && npm ci --no-audit --no-fund && npx vite build)
fi

if [ ! -f "$STATIC_DIR/index.html" ]; then
    echo "$STATIC_REL/index.html is missing; the web UI was not built" >&2
    exit 1
fi

prefix="roshanavi-$version"
mkdir -p "$DIST_DIR"
tarball="$DIST_DIR/$prefix.tar.gz"
tmp_tar="$(mktemp "$DIST_DIR/.$prefix.XXXXXX.tar")"
trap 'rm -f "$tmp_tar"' EXIT

git -C "$ROOT" archive --format=tar --prefix="$prefix/" "$ref" > "$tmp_tar"
# Append the (git-ignored) built UI. Paths are rewritten to sit under the same top-level folder.
tar -rf "$tmp_tar" -C "$ROOT" --owner=0 --group=0 --numeric-owner --transform "s,^,$prefix/," "$STATIC_REL"
gzip -n -9 -c "$tmp_tar" > "$tarball"
(cd "$DIST_DIR" && sha256sum "$prefix.tar.gz" > "$prefix.tar.gz.sha256")

# Sanity checks: the UI is inside, and no dev-only junk is.
listing="$(tar -tzf "$tarball")"
grep -q "^$prefix/$STATIC_REL/index.html\$" <<<"$listing" \
    || { echo "FAIL: index.html is not in the tarball" >&2; exit 1; }
if grep -Eq "(^|/)(node_modules|\.git)/" <<<"$listing"; then
    echo "FAIL: the tarball contains node_modules or .git" >&2
    exit 1
fi

echo "wrote $tarball ($(du -h "$tarball" | cut -f1), $(wc -l <<<"$listing") entries)" >&2
echo "$tarball"
