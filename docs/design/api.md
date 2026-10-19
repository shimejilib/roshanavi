# roshanavi — API (REST / WebSocket)

## server API

| Method | Path | 内容 |
|---|---|---|
| GET | `/api/graph` | グラフスナップショット |
| GET | `/api/traffic?window=` | 統計一覧 (各エントリに `monitored`, `status`: ok/not_monitored/unsupported/error、`heavy` (既定で計測しない型か)、計測していないトピックで詳細計測モードのとき `hz_traced`)。`window` は 1 / 5 / 10 秒 ([map-and-traffic.md#traffic](map-and-traffic.md#traffic)) |
| PUT | `/api/traffic/{topic}/monitor` | `{"enabled": bool}` でトピック単位の計測 on/off。プロジェクトファイルの `traffic_monitor` に保存され、再起動で復元される (#61) |
| GET | `/api/types` | 利用可能なメッセージ型一覧 |
| GET | `/api/data-kinds` | データの種類の一覧 `{kinds[{id, type, available, python}], type_kinds, common_types, conversions[{from, to, note}]}` (`conversions` は地図の配線で許す種類の変換、[wiring.md](wiring.md)) |
| GET | `/api/types/{pkg}/msg/{name}/template` | テンプレ dict |
| POST/GET/DELETE | `/api/inject[/{id}]` | 注入ジョブ |
| POST | `/api/inject/{id}/pause\|resume` | 注入ジョブの一時停止・再開 ([input-and-media.md#injector](input-and-media.md#injector)) |
| GET / PUT | `/api/nodes/{node}/parameters` | パラメータ一覧 (型・値・説明・読み取り専用・範囲) / 1 つ変更 `{name, type, value, allow_external}` ([launcher.md#ノードのパラメータと型の定義](launcher.md#ノードのパラメータと型の定義-p45a)) |
| GET | `/api/node-list` | ノード一覧 ([launcher.md#ノード一覧の集約](launcher.md#ノード一覧の集約-p45b)): `{rows, groups}`。行 = グラフのノード ∪ 起動リスト・常駐ダミー (止まっているもの)。lifecycle ノードは状態付き |
| GET / POST | `/api/nodes/{node}/lifecycle` | lifecycle の状態と可能な遷移 / 遷移 `{transition}` か目標 `{goal: active\|inactive}` + `allow_external` ([launcher.md#lifecycle ノード](launcher.md#lifecycle-ノード-p45b)) |
| POST | `/api/launch-import/preview` | launch ファイルを別プロセスで評価し、ノードごとの起動設定案を返す `{source, args}` → `{preview_id, nodes, blocked, skipped, arguments, whole}` ([launcher.md#launch の分解取り込み](launcher.md#launch-の分解取り込み-p45b)) |
| POST | `/api/launch-import/commit` | 案から取り込む `{preview_id, mode: nodes\|whole, indices, role}` (自動保存) |
| GET | `/api/takeover` | launch の引き取り ([integration.md](integration.md)): `{active, state: off\|starting\|ready\|error\|inactive, package, launch_file, args, mode, mine, error, report{carried, lost, rest, notes, separate, suggest_whole}, pending{preview_id, reason, files, added, removed, changed, unchanged, report}, targets}` |
| POST | `/api/takeover/start` | パッケージの launch ファイルを引き取って起動する `{package, launch_file, args, mode: node\|whole, mine[]}` (202、解析は裏で。`--launch` と同じ) |
| POST | `/api/takeover/check` | 今すぐ解析し直して差分を `pending` にする (適用はしない)。引き取っていなければ 409 `no_takeover` |
| POST | `/api/takeover/apply`, `/api/takeover/dismiss` | `{preview_id}`: 取り込み直す (追加は起動、削除は停止、変更は動いていれば再起動) → `{added, removed, changed, restarted, errors, status}` / 「あとで」。古い `preview_id` は 404 `preview_expired` |
| GET / POST | `/api/leftovers`, `/api/leftovers/stop` | 強制終了された前回のサーバーが残したプロセス `{count, processes[{pid, pgid, target, cmd}]}` / 止める (記録と一致するものだけ。SIGINT → SIGTERM → SIGKILL) → `{stopped, survivors}` ([launcher.md#子プロセスの後始末](launcher.md#子プロセスの後始末-12)) |
| POST | `/api/registry/delete`, `/api/registry/undo` | ノード一覧の「削除」`{ids[]}` (起動リスト・入力・変換・関数・クラスノード、1〜200 個。知らない ID があれば何も消さずに 404) → `{removed[{id, kind, was_running}], undo_id, undo_sec}` / 「元に戻す」`{undo_id}` (15 秒以内に 1 回) → `{restored, started, errors}`。期限切れは 404 `undo_expired` |
| GET | `/api/interfaces/{pkg}/{msg\|srv\|action}/{Name}` | 型の定義 `{type, text, expanded, truncated}` ([launcher.md#ノードのパラメータと型の定義](launcher.md#ノードのパラメータと型の定義-p45a)) |
| GET | `/api/files` | data_dir 内のファイル一覧 (stream/bag 選択用) |
| GET | `/api/echo/{topic}/sample` | エコー中のトピックの最新メッセージを切り詰めずに返す (上限 256 KiB。超えると `capped: true` で表示用の値)。変換ノードのプレビュー用 ([nodes.md](nodes.md)) |
| GET / POST | `/api/scenarios` | シナリオの一覧 (プロジェクト + サンプル、各 `last_result`、`project_dir`) / 保存 `{spec\|yaml, file?, overwrite?}` (201、同名は 409) ([scenarios.md#サーバー](scenarios.md#サーバー-scenarios-タブ-servicepy--storepy)) |
| GET / PUT / DELETE | `/api/scenarios/{id}` | id は一覧の `project:<file>` / `example:<file>` だけ。取得 `{yaml, spec, errors}` / 更新 `{spec\|yaml}` / 削除 (サンプルは 403 `read_only`)。誤りは 422 `invalid_scenario` + `errors[{path, line, message}]` |
| POST | `/api/scenarios/validate` | 保存せずに検査 `{spec\|yaml}` → `{ok, errors, spec, yaml}` (常に 200) |
| POST | `/api/scenarios/{id}/run` | 実行を始める (202、結果の途中経過を返す)。1 つずつ (409 `run_busy`) |
| GET | `/api/scenario-runs`, `/api/scenario-runs/{run_id}` | 結果の履歴 (新しい 50 件) と実行中の結果 / 1 件の結果 (ステップごとの `status`・`message`・`hints`・`details`) |
| POST | `/api/scenario-runs/{run_id}/cancel` | 実行の中止 (後片付けは行う) |
| POST / GET / DELETE | `/api/scenario-record[?since=]` | 記録モードの開始 `{watch[]}` (最大 8) / 状態とタイムライン (`events[{seq, t, kind: op\|msg, ...}]`) / 停止 |
| POST | `/api/scenario-record/measure` | 記録した区間の計測 `{kind: rate\|throughput\|latency, start, end, topic\|input+output, match}` (しきい値の提案用) |
| WS | `/ws/scenarios` | 0.25 秒ごとに `{record: {active, session, events(新しい分)}, running, run?(実行中か変化時)}` |
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
| GET | `/api/functions/modules`, `/api/functions/module?name=` | 関数・クラスノード用: 使えるモジュールの一覧 (A ワークスペース / B 登録した場所 / C インストール済み。各 `scope`・`source`・`listable`) / 1 つのモジュールの関数 (`functions[]`) とクラス (`classes[]`)、候補にならなかった名前 (`skipped[]`)、通知 (`notices[]`) を `ast` の静的解析だけで返す (利用者のコードは import しない。[nodes.md#関数ノード](nodes.md#関数ノード-ふつうの関数をそのままノードにするp55)、[nodes.md#クラスノード](nodes.md#クラスノード-状態を持つ処理をそのままノードにする)、[user-code.md](user-code.md)) |
| GET / PUT | `/api/functions/locations[?refresh=true]` | 「コードの場所」: 範囲ごとに見つかったもの、見つからない理由 (`problems[{code, path?, file?, line?, …}]`)、ここに置けば見つかる場所 (`place_here[]`)、ノードを動かす Python (`python`)、設定 (`settings`)。PUT `{code_paths, installed_modules}` で B / C を変える (新しく足したフォルダを検査。400 / 404 `invalid_code_path`、プロジェクトファイルに自動保存) ([user-code.md#7](user-code.md#7-api-と画面)) |
| POST | `/api/functions/scaffold` | 「ひな形を作る」`{name}` → 201 `{package, directory, module, function, class_name, files[]}`。400 `invalid_package_name`、409 `file_exists` / `name_taken`、403 `not_writable` |
| GET | `/api/functions/dependency?missing=&module=` | 足りないライブラリの入れ方: rosdep キー (`rosdep resolve` で確かめた apt のキー、確かめられないときは `unavailable` と候補)・`package.xml` に足す 1 行・`rosdep install` のコマンド、または venv の手順。pip は実行しない |
| POST / PUT | `/api/functions[?start=true]`, `/api/functions/{id}` | 関数ノードの登録 / 更新 (`FunctionSpec`)。404 `unknown_module` |
| POST | `/api/functions/{id}/export-code` | 関数を包む rclpy ノードのコードを書き出す `{directory}` → `{file, command}`。つながっていない口 (トピック名が空) があれば 409 `unwired_ports` |
| POST / PUT | `/api/classes[?start=true]`, `/api/classes/{id}` | クラスノードの登録 / 更新 (`ClassSpec`) |
| POST | `/api/classes/{id}/call` | 操作メソッドを呼ぶ `{method}`: `std_msgs/Empty` を `/<ノード名>/<メソッド名>` に送り、ノードが記録するのを待って `{method, topic, record{count, last_at, ok, result, error}}`。動いていない 409 `not_running`、操作メソッドでない 404 `unknown_action`、5 秒待っても呼ばれない 504 `call_failed`。記録モード中は `call` ステップになる |
| POST | `/api/classes/{id}/export-code` | クラスを包む rclpy ノード (`lifecycle: true` なら LifecycleNode) のコードを書き出す `{directory, lifecycle?}` → `{file, command}`。つながっていない口があれば 409 `unwired_ports` |
| POST | `/api/transforms/preview` | 変換の試算 `{spec, samples}` → `{ok, passed, output, errors[]}` (常に 200) |
| GET / POST | `/api/projects`, `/api/projects/open` | 切り替えられるプロジェクトの一覧 / 一覧の `id` を開く (開いた `id` は再起動後も記憶する。[launcher.md#プロジェクトファイル](launcher.md#プロジェクトファイル-p3)) |
| WS | `/ws/logs/{id}` | ログのストリーム (`{log_id, lines:[{seq, ts, stream, text}]}`、0.2 秒ごと) |
| GET | `/api/media/types?topic=` | 対応型 `[{type, kind}]`。topic を付けると端点の型 (`endpoints`) と自動判定 (`detected`, `detected_supported`) |
| WS | `/ws/capture` | ブラウザ入力。最初にテキストで開始メッセージ、続けてバイナリフレーム ([input-and-media.md#メディア](input-and-media.md#メディア-アダプタファイルソースブラウザ入力ビューア-p4)) |
| WS | `/ws/view/{topic}?sample_rate=` | 画像・音声ビューア。JSON のメタ情報の直後に 1 つのバイナリ (JPEG / PCM) |
| GET / POST | `/api/recordings` | 録画の一覧 + 状態 / 開始 `{topics[], name}` ([input-and-media.md#録画](input-and-media.md#録画-p4)) |
| POST | `/api/recordings/stop` | 録画の停止 (SIGINT で bag を確定) |
| DELETE | `/api/recordings/{name}` | 録画の削除 (recordings ディレクトリの直下のみ) |
| GET | `/api/resources` | リソース監視の最新の全体 ([resources.md](resources.md)): `{available, reason?, hostname, ncpu, own_user_only, host{cpu, mem, disk, nics, udp, gpu}, breakdown, processes[], others[], nodes{node: {pid, pids, confidence, source, shared, scope, cpu_pct, rss, uss, threads, fds, read_bps, write_bps, gpu_mem, leak}}, connections[], events[], diagnostics[], sampler}`。停止中は `available: false` + `reason: starting\|off` |
| GET | `/api/resources/history?node=\|scope=self\|host` | 直近 5 分 (1 秒ごと) の `{t, cpu_pct, rss, read_bps, write_bps, gpu_mem, connections}`。`node` を付けると `current` (そのノードの今の値) と `connections` (接続先) も返す |
| WS | `/ws/resources` | リソースタブ用。1 秒ごとに `/api/resources` と同じ全体を push |

- 記録モードの間、`POST /api/inject`・`DELETE /api/inject/{id}`・`POST /api/targets/{id}/start|stop|restart` は成功した操作を記録に足す ([scenarios.md#UI での作り方: 記録モード](scenarios.md#ui-での作り方-記録モード-主軸))。
- `/ws/live` は `targets` (起動対象の一覧) と `build` (ビルドの状態)、`recording` (録画中ならその状態、なければ null)、`resources` (地図のバッジ用: ノードごとの `cpu_pct`・`rss`・`confidence`・`shared`・`scope`・`leak`、PC 全体、roshanavi 自身、リソースの診断) も毎秒送る。
- traffic の各エントリ (REST / WS 共通) には `publishers[]` (送信者ごとの値と根拠, rates.py)、`subscribers[]` (受信者ごとの理論値, [map-and-traffic.md#送受信ごとのトラフィック・遅いトピック](map-and-traffic.md#送受信ごとのトラフィック遅いトピック-p45b))、`rate_window_sec` / `rate_note` ([map-and-traffic.md#送受信ごとのトラフィック・遅いトピック](map-and-traffic.md#送受信ごとのトラフィック遅いトピック-p45b)) が付く。

## 既定ポート・入力検証・エラー形式
- 既定ポートは **6871**。ROS 2 の DDS/RTPS が使う 7400 + 250 × ドメイン ID 以上より下、Linux の一時ポート (32768–60999) の外、X11 (6000–6063)・redis (6379)・k8s (6443) などのよく使う開発用ポートとも重ならない。
- 入力は pydantic モデルで検証。既定 bind は `127.0.0.1` (Docker 内では `0.0.0.0` を明示指定し、ポート公開は compose 側で `127.0.0.1:6871:6871`)。
- エラーは `{error: {code, message}}` で返す。

## ローカル Web からの攻撃対策
認証なし・localhost bind が前提 (`security.py` の ASGI ミドルウェア)。
- DNS rebinding: 全 HTTP/WS リクエストの `Host` を許可リスト (`localhost`, `127.0.0.1`, `[::1]` の任意ポート + 繰り返し指定可の `--allowed-host`) で検査。違反は 403 `forbidden_host` (WS は close 1008)。
- Cross-site WebSocket hijacking: WS ハンドシェイクに `Origin` があれば http(s) origin かつ host が許可リスト内 (または `--allowed-origin` と完全一致) であること。違反は close 1008。Origin 無し (非ブラウザ) は許可。Vite dev (`http://localhost:5173`) は localhost で通る。
- CSRF: POST/PUT/PATCH/DELETE でボディがある場合 `Content-Type: application/json` 必須、違反は 415 `unsupported_media_type`。ボディ無し DELETE は可。
- Docker では compose が `127.0.0.1:6871:6871` を公開するためホストからの Host は `localhost:6871`/`127.0.0.1:6871` で許可される。別名でアクセスする場合は `--allowed-host` を足す。
