# roshanavi — project instructions

ROS 2 Jazzy dev tool for developers new to ROS: live topic/node map, traffic per node × topic, input / transform / function nodes, launcher, media injection, tracing-based measurement, scenario tests with record mode. Web UI (React + Vite) + FastAPI/rclpy backend + C++ probe. Default port **6871**. License MIT.

User-facing replies are in **Japanese**, plain language, no unexplained jargon (the user is the product owner; target users are developers new to ROS).

## Where things are
- `docs/README.md` — index of every doc (one line each). Start there; read only the page you need.
- `docs/overview/` — `vision.md` (motivation / target users / user journey / goals; read first), `architecture.md` (tech stack, repo layout, how the pieces fit), `roadmap.md` (phases and status; open work is tracked in GitHub Issues).
- `docs/design/` — the spec and every decision, by topic (single source of truth): `map-and-traffic.md`, `measurement.md` (C++ probe, tracing), `input-and-media.md` (inject, expr, media, recording), `nodes.md` (input / transform / function nodes, data kinds), `launcher.md` (launcher, project file, params, lifecycle, launch import, node list), `ui.md`, `api.md`, `security.md` (every security decision with links), `scenarios.md` (runner, CLI, record mode). The spec used to be one file with numbered sections; those numbers no longer exist, so refer to the page and heading.
- `docs/project/testing.md` — test policy, commands, and test items with status (✅ 🟡 ⬜ 👀). Update the section you touch.
- `docs/project/dependencies.md` — every dependency with purpose/license/rosdep key. Update it together with `package.xml` / Dockerfile / `web/package.json`. Never let Docker have a dependency that `package.xml` lacks.
- `docs/project/distribution.md` — install/packaging design (planned). Planned-but-not-built designs: `docs/planned/resources.md` (CPU/GPU/mem/disk/net monitoring, Lv1 only), `docs/planned/remote-access.md` (device pairing).
- `docs/images/` — UI screenshots, written by the E2E specs.
- Packages: `ros2_ws/src/roshanavi` (Python server), `roshanavi_msgs`, `roshanavi_probe` (C++), `roshanavi_examples` (sample nodes), `roshanavi_test_nodes`. Web: `web/`.

## Commands (ROS is NOT installed on the host — everything runs in Docker)
- Backend tests (gtest + pytest): `docker compose --profile test run --rm test`
- One test file: `docker compose --profile test run --rm test python3 -m pytest -p no:cacheprovider -q /ws/src/roshanavi/test/<file>.py -k <expr>`
- Web unit tests: `cd web && npm ci && npx vitest run [file]`; typecheck `npx tsc --noEmit`
- E2E (isolated stack, never against the user's lab): `scripts/e2e.sh`
- Run the app: `docker compose up -d --build lab demo` → http://localhost:6871

## Test policy
- The machine may be busy; many tests are real-time (Hz, pacing, latency). While iterating, run only the tests relevant to the change. Run the full backend suite once and `scripts/e2e.sh` once at the end.
- A failure that is clearly a timing flake unrelated to the change (passes when re-run alone) is reported, not chased. Never loosen tolerances to hide real stalls.
- New features need tests (unit + integration; E2E for UI flows). TDD where practical.

## How work is organized
- The main session designs, writes briefs, audits diffs, and reports to the user. Implementation goes to subagents (`Agent` tool) with an explicit model: `sonnet` for normal/medium work, `opus` for heavy design-level implementation, `haiku` for mechanical edits. Main implements directly only when a subagent failed twice or the change is very subtle.
- Run heavy subagents **one at a time** (max 2 if urgent). Ask them to be token-efficient: grep first, then read limited ranges.
- Always audit a subagent's result before accepting it: reproduce the test summary, read the security-relevant parts of the diff, look at screenshots for UI work. Report problems found in the audit honestly.
- Do not inject new scope into a running subagent unless it touches the same files; queue it for the next phase.

## Rules that have bitten this project
- `ros_runtime.create_subscription` registers **no QoS event handlers** on purpose (rclpy executor busy-loop holding the GIL). Keep it that way for every new subscription/client.
- Never `eval`/`exec` user input. Expressions go through the AST-whitelist evaluator (`expr.py`, `msg_view.py`); extend it only with tests for the security boundary.
- All subprocesses: argv lists, no shell; user paths: realpath containment inside workspace/data_dir; launch files are evaluated only in the sandboxed child process.
- The server binds 127.0.0.1 by default; Host/Origin/Content-Type middleware must cover every new route and WebSocket.
- Never signal processes roshanavi did not start (lifecycle transitions via the ROS API are fine, with confirmation).
- Rates: one semantics everywhere (`stats.window_rate`: interval-based, stale → 0, too few samples → "計測中…").
- E2E must not touch the user's `./data`.

## Git
- Conventional commits (`feat:`, `fix:`, `docs:`, `test:`, `chore:`, `refactor:`, `perf:`, `build:`, `style:`).
- End commit messages with: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`
- Remote: private `github.com/shimejilib/roshanavi`.
