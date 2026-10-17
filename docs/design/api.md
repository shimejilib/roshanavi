# roshanavi — API (REST / WebSocket)

## server API

| Method | Path | 内容 |
|---|---|---|
| GET | `/api/graph` | グラフスナップショット |
| GET | `/api/traffic?window=` | 統計一覧 (各エントリに `monitored`, `status`: ok/not_monitored/unsupported/error)。`window` は 1 / 5 / 10 秒 ([map-and-traffic.md#traffic](map-and-traffic.md#traffic)) |
| PUT | `/api/traffic/{topic}/monitor` | `{"enabled": bool}` でトピック単位の監視 on/off |
| GET | `/api/types` | 利用可能なメッセージ型一覧 |
| GET | `/api/types/{pkg}/msg/{name}/template` | テンプレ dict |
| POST/GET/DELETE | `/api/inject[/{id}]` | 注入ジョブ |
| POST | `/api/inject/{id}/pause\|resume` | 注入ジョブの一時停止・再開 ([input-and-media.md#injector](input-and-media.md#injector)) |
| GET / PUT | `/api/nodes/{node}/parameters` | パラメータ一覧 (型・値・説明・読み取り専用・範囲) / 1 つ変更 `{name, type, value, allow_external}` ([launcher.md#ノードのパラメータと型の定義](launcher.md#ノードのパラメータと型の定義-p45a)) |
| GET | `/api/node-list` | ノード一覧 ([launcher.md#ノード一覧の集約](launcher.md#ノード一覧の集約-p45b)): `{rows, groups}`。行 = グラフのノード ∪ 起動リスト・常駐ダミー (止まっているもの)。lifecycle ノードは状態付き |
| GET / POST | `/api/nodes/{node}/lifecycle` | lifecycle の状態と可能な遷移 / 遷移 `{transition}` か目標 `{goal: active\|inactive}` + `allow_external` ([launcher.md#lifecycle ノード](launcher.md#lifecycle-ノード-p45b)) |
| POST | `/api/launch-import/preview` | launch ファイルを別プロセスで評価し、ノードごとの起動設定案を返す `{source, args}` → `{preview_id, nodes, blocked, skipped, arguments, whole}` ([launcher.md#launch の分解取り込み](launcher.md#launch-の分解取り込み-p45b)) |
| POST | `/api/launch-import/commit` | 案から取り込む `{preview_id, mode: nodes\|whole, indices, role}` (自動保存) |
| GET | `/api/interfaces/{pkg}/{msg\|srv\|action}/{Name}` | 型の定義 `{type, text, expanded, truncated}` ([launcher.md#ノードのパラメータと型の定義](launcher.md#ノードのパラメータと型の定義-p45a)) |
| GET | `/api/files` | data_dir 内のファイル一覧 (stream/bag 選択用) |
| GET/POST | `/api/scenarios`, `/api/scenarios/run` | シナリオ一覧・実行 (結果は JSON) |
| WS | `/ws/live?window=` | 1 秒毎に `{traffic, graph?(変化時), jobs, server_time}` を push。traffic 各エントリに直近 1 秒の受信数 `recent_count`、`window_sec`、`stale` |
| WS | `/ws/echo/{topic}` | エコー |
| GET / POST | `/api/workspace`, `/api/workspace/refresh` | パッケージ・実行ファイル・launch ファイル一覧 ([launcher.md#Launcher](launcher.md#launcher-p3)) |
| GET / POST | `/api/targets[?start=true]` | 起動リストの一覧 (状態・pid・対応ノード) / 登録 (`TargetSpec`)。`start=true` で登録と同時に起動 |
| GET / PUT / DELETE | `/api/targets/{id}` | 取得 / 設定の更新 (反映は再起動時) / 停止して削除 |
| POST | `/api/targets/{id}/start\|stop\|restart` | 起動・停止・再起動 |
| GET / DELETE | `/api/targets/{id}/logs?since=` | ログ (リングバッファ) の取得 / クリア。ビルドログは id `_build` |
| GET / POST / DELETE | `/api/build` | ビルドの状態 / 開始 `{package, restart_running}` (202) / 中止 |
| GET / PUT | `/api/project` | 作業中のプロジェクト + `dirty`, `autosave`, `save_error` / 全体を置き換えて保存 |
| POST | `/api/project/save`, `/api/project/reload` | 現在の内容を保存 / ファイルから読み直す |
| POST / PUT | `/api/dummies[?start=true]`, `/api/dummies/{id}` | 恒久ダミー (入力ノード) の登録 / 更新 (`DummySpec`)。`start=true` で登録と同時に起動 |
| POST | `/api/inject/{job_id}/persist` | 注入ジョブを恒久ダミーノードにして起動 `{name, namespace?, autostart, stop_job}` |
| POST | `/api/dummies/export` | launch ファイル + 設定 YAML を書き出す `{directory, ids[]}` (P5: 変換ノードも) |
| POST / PUT | `/api/transforms[?start=true]`, `/api/transforms/{id}` | 変換ノードの登録 / 更新 (`TransformSpec`, [nodes.md#変換ノード](nodes.md#変換ノード-p5)) |
| POST | `/api/transforms/preview` | 変換の試算 `{spec, samples}` → `{ok, passed, output, errors[]}` (常に 200) |
| GET / POST | `/api/projects`, `/api/projects/open` | 切り替えられるプロジェクトの一覧 / 一覧の `id` を開く ([launcher.md#プロジェクトファイル](launcher.md#プロジェクトファイル-p3)) |
| WS | `/ws/logs/{id}` | ログのストリーム (`{log_id, lines:[{seq, ts, stream, text}]}`、0.2 秒ごと) |
| GET | `/api/media/types?topic=` | 対応型 `[{type, kind}]`。topic を付けると端点の型 (`endpoints`) と自動判定 (`detected`, `detected_supported`) |
| WS | `/ws/capture` | ブラウザ入力。最初にテキストで開始メッセージ、続けてバイナリフレーム ([input-and-media.md#メディア](input-and-media.md#メディア-アダプタファイルソースブラウザ入力ビューア-p4)) |
| WS | `/ws/view/{topic}?sample_rate=` | 画像・音声ビューア。JSON のメタ情報の直後に 1 つのバイナリ (JPEG / PCM) |
| GET / POST | `/api/recordings` | 録画の一覧 + 状態 / 開始 `{topics[], name}` ([input-and-media.md#録画](input-and-media.md#録画-p4)) |
| POST | `/api/recordings/stop` | 録画の停止 (SIGINT で bag を確定) |
| DELETE | `/api/recordings/{name}` | 録画の削除 (recordings ディレクトリの直下のみ) |

- `/ws/live` は `targets` (起動対象の一覧) と `build` (ビルドの状態)、`recording` (録画中ならその状態、なければ null) も毎秒送る。
- traffic の各エントリ (REST / WS 共通) には `publishers[]` (送信者ごとの値と根拠, rates.py)、`subscribers[]` (受信者ごとの理論値, [map-and-traffic.md#送受信ごとのトラフィック・遅いトピック](map-and-traffic.md#送受信ごとのトラフィック遅いトピック-p45b))、`rate_window_sec` / `rate_note` ([map-and-traffic.md#送受信ごとのトラフィック・遅いトピック](map-and-traffic.md#送受信ごとのトラフィック遅いトピック-p45b)) が付く。

## 既定ポート・入力検証・エラー形式
- 既定ポートは **6871** (ro(6)s-ha(8)-na(7)-bi(1))。ROS 2 の DDS/RTPS が使う 7400 + 250 × ドメイン ID 以上より下、Linux の一時ポート (32768–60999) の外、X11 (6000–6063)・redis (6379)・k8s (6443) などのよく使う開発用ポートとも重ならない。
- 入力は pydantic モデルで検証。既定 bind は `127.0.0.1` (Docker 内では `0.0.0.0` を明示指定し、ポート公開は compose 側で `127.0.0.1:6871:6871`)。
- エラーは `{error: {code, message}}` で返す。

## ローカル Web からの攻撃対策
認証なし・localhost bind が前提 (`security.py` の ASGI ミドルウェア)。
- DNS rebinding: 全 HTTP/WS リクエストの `Host` を許可リスト (`localhost`, `127.0.0.1`, `[::1]` の任意ポート + 繰り返し指定可の `--allowed-host`) で検査。違反は 403 `forbidden_host` (WS は close 1008)。
- Cross-site WebSocket hijacking: WS ハンドシェイクに `Origin` があれば http(s) origin かつ host が許可リスト内 (または `--allowed-origin` と完全一致) であること。違反は close 1008。Origin 無し (非ブラウザ) は許可。Vite dev (`http://localhost:5173`) は localhost で通る。
- CSRF: POST/PUT/PATCH/DELETE でボディがある場合 `Content-Type: application/json` 必須、違反は 415 `unsupported_media_type`。ボディ無し DELETE は可。
- Docker では compose が `127.0.0.1:6871:6871` を公開するためホストからの Host は `localhost:6871`/`127.0.0.1:6871` で許可される。別名でアクセスする場合は `--allowed-host` を足す。
