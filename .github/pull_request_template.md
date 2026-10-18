## 何を変えたか / What

<!-- 変更の内容を、短く。 / A short description of the change. -->

## なぜ / Why

<!-- 困っていたこと、関係する Issue (例: Closes #123)。 / The problem it solves; related issue (e.g. Closes #123). -->

## 確かめたこと / How it was tested

<!-- 動かしたテストと結果。画面の変更はスクリーンショットも。 / Tests you ran and the result; screenshots for UI changes. -->

- [ ] 関係するテストを動かした / Ran the relevant tests
- [ ] バックエンド全体 `docker compose --profile test run --rm test` (最後に 1 回) / Full backend suite once
- [ ] Web: `cd web && npx vitest run` と `npx tsc --noEmit` / Web unit tests and typecheck
- [ ] 画面の操作を変えた場合: `scripts/e2e.sh` / E2E for UI flows
- [ ] ROS・pydantic・FastAPI に触れる変更は、Jazzy と Lyrical の両方で / Both Jazzy and Lyrical for ROS / pydantic / FastAPI changes

タイミングの揺れで落ちたテスト (単独なら通る、変更と無関係) があれば、ここに書いてください。 / Note any timing flakes (pass alone, unrelated to the change) here.

## チェックリスト / Checklist

- [ ] 新しい機能にテストを付けた / New features have tests
- [ ] ドキュメントを更新した (`docs/guide/`、`docs/design/`、`docs/project/testing.md`) / Updated the docs
- [ ] 依存を足したときは `package.xml`・Dockerfile・`web/package.json`・`docs/project/dependencies.md` をそろえた / Dependencies are consistent
- [ ] 新しい API・WebSocket は `Host` / `Origin` / `Content-Type` の検査の内側にある / New routes are behind the Host / Origin / Content-Type checks
- [ ] 利用者の入力を `eval` / `exec` に渡していない。サブプロセスは argv のリスト / No eval/exec of user input; subprocesses use argv lists
- [ ] コミットメッセージが Conventional Commits の形 / Commits follow Conventional Commits
