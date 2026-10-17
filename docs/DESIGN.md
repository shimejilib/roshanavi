# roshanavi — 設計書 (ROS 2 Jazzy)

ROS 2 システムの「通信の可視化」「ダミー入力の注入」「入出力シナリオの自動判定」を 1 つの Web UI / CLI にまとめるツール。

## 0. 出発点と対象ユーザー

- **課題**: ROS 2 のテスト・確認手段 (`ros2 topic hz/echo/pub`, rqt_graph, rqt_publisher, launch_testing, bag ...) が分散しており、一つの UI になっていない。それぞれの使い方と組み合わせ方を知っていることが前提になっている。
- **対象**: ROS を深く理解していない開発者が、ROS のノードを開発・確認できること。ROS 熟練者が CI で使えることは副次的なゴール。
- **設計への含意**: CLI の知識や YAML 手書きを前提にしない (UI で完結し、YAML は保存・CI 用の形式)。用語 (QoS 等) は UI 上で平易に補足し、つまずきやすい点 (QoS 不一致、subscriber 不在 など) はツール側から指摘する。

## 0.1 主要ユーザー体験: ノード単体開発者の 1 日

「自分のノードを作っている人」が、ROS のコマンドを覚えずに **起動 → 入力 → 観察 → テスト化 → 修正 → 再確認** を GUI で回せること。

1. **ツールを起動**: ワークスペースで 1 コマンド (`ros2 run roshanavi app`)。ブラウザが開く。
2. **プロジェクトを開く**: プロジェクトファイル (`roshanavi.yaml`) に、起動対象・ダミー入力・監視トピック・シナリオを保存する。初回はワークスペースを走査して作る。
3. **ノードを起動 (Launcher)**: 自分のノードと依存ノードを GUI で選んで起動・停止・再起動する。
   - 候補はワークスペースから自動で列挙する (パッケージの実行ファイル、launch ファイル)。
   - パラメータとリマップを GUI で設定できる。プロセスごとにログ (stdout/stderr) を表示する。
   - **ビルドボタン**: `colcon build --packages-select <pkg>` を実行し、成功したら対象ノードを自動で再起動する。
4. **ダミー入力**: 入力トピックを選び、手入力・式・ファイル (画像/動画/音声/JSONL/CSV)・bag から送る。
   - **恒久ノード化**: ダミー入力を、GUI のジョブではなく独立した ROS ノード (例: `/dummy_camera`) として常駐させる。
     - 名前付きでグラフに現れ、ツールの起動時に自動で起動できる (プロジェクトに保存)。
     - launch ファイル + 設定 YAML に書き出し、ツールなしでも `ros2 launch` で動かせる。
5. **観察**: 出力トピックをエコー、グラフ、プロット、**画像ビューア**、**音声の波形・再生**で確認する。
6. **テスト化**: 記録モードで、いまの操作と出力をシナリオに保存する (§5.4)。
7. **修正ループ**: コードを直す → ビルドボタン → ノードが自動で再起動 → 保存済みシナリオを一括再実行し、回帰を確認する。

### 実行形態
- 利用者のノードと同じ ROS 環境で動く必要があるため、**本番の形はネイティブ実行** (利用者のワークスペースに入れて colcon build、将来は apt)。
- Docker は開発・CI・デモ用に位置づける。Docker で使う場合は、利用者のワークスペースをマウントする。

### 同梱サンプルノード (`roshanavi_examples`)
チュートリアル、デモ、自動テストの対象を兼ねる。
- `image_filter`: Image → グレースケール + エッジの Image (stamp 引き継ぎあり/なしをパラメータで切替 → latency の両モード検証用)
- `blob_detector`: Image → 検出結果 (配列長・座標の判定用)
- `audio_level`: 音声 → 音量 (dB) と無音検出
- `state_machine`: `/cmd` (start/stop/fault) → `/state` (IDLE/RUNNING/ERROR) (guards・状態遷移の判定用)

## 1. ゴールと非ゴール

**ゴール**
- G1 グラフ: ノード ⇄ トピックの接続図を QoS 付きでリアルタイム表示。エッジを Hz / 帯域で強調。
- G2 トラフィック: 全トピックの Hz・帯域・平均サイズ・ジッタ・最終受信時刻を一覧 + スパークライン。
- G3 注入: 任意型のトピックへ 単発 / 周期 / 式 / ファイルストリーム (JSONL・CSV) / bag 再生 で入力。
- G4 シナリオ: YAML で「注入 → 期待出力」を記述し、UI と CLI (JUnit XML, exit code) で判定。CI 可。
- G5 エコー: 選択トピックの最新メッセージを UI で確認。画像は表示、音声は波形と再生。
- G6 Launcher: 自分のノード・依存ノードの起動・停止・再起動・ログ表示・ビルド (§0.1)。
- G7 恒久ダミーノード: ダミー入力を名前付きの常駐ノードにし、launch ファイルとして書き出せる (§0.1)。
- G8 メディア注入: 画像・動画 (フレーム分解)・音声ファイルを適切な msg に変換して送る (§4.6.1)。

**非ゴール (MVP)**: サービス・アクション (今後対応予定。README に明記する)、CARET 級のコールバック単位レイテンシ解析、複数ドメイン同時監視、認証付きリモート公開。

## 2. 技術選定

| 層 | 採用 | 理由 |
|---|---|---|
| ROS | rclpy (Jazzy, Python 3.12) | 動的型解決 (`rosidl_runtime_py`) で任意 msg を扱える |
| サーバー | FastAPI + uvicorn (Ubuntu 24.04 apt の python3-fastapi / python3-uvicorn) | REST + WebSocket。pip を使わず apt で揃える |
| フロント | Vite + React + TypeScript, Cytoscape.js (グラフ), uPlot (スパークライン) | ビルド成果物を FastAPI が静的配信 |
| 実行環境 | Docker (`ros:jazzy-ros-base` ベース) + docker compose | ホストを汚さない。CI 流用 |

## 3. リポジトリ構成

```
roshanavi/
  docker/Dockerfile            # ros:jazzy-ros-base + fastapi/uvicorn/pytest/demo_nodes_py/rosbag2
  docker-compose.yml           # lab (サーバー, :8080) / demo (talker・listener 等) / test
  docs/DESIGN.md
  ros2_ws/src/roshanavi/       # ament_python パッケージ
    roshanavi/
      ros_runtime.py   # rclpy ノード + MultiThreadedExecutor を専用スレッドで回す。スレッド安全な facade
      graph.py         # グラフスナップショット
      qos_compat.py    # pub × sub の QoS 互換判定 (純関数)
      diagnostics.py   # 初心者向け診断 (純関数)
      traffic.py       # 全トピック raw 購読 + 統計
      msgutil.py       # 型解決 / テンプレ生成 / dict⇄msg / 表示用切り詰め
      expr.py          # AST ホワイトリスト式評価器 (eval 禁止)
      injector.py      # 注入ジョブ管理
      echo.py          # オンデマンド購読 → 最新メッセージ
      launcher/        # §4.9-4.10: discovery / validate / command / process / target / manager /
                       #   build / env / schema / project / dummy_config / service
      process_map.py   # ノード ⇄ プロセス対応づけ (再利用可能。リソース計測でも使う)
      dummy_node.py    # エントリ: `ros2 run roshanavi dummy --config <yaml>` (恒久ダミーノード)
      scenario/        # schema.py / runner.py / junit.py / cli.py
      server.py        # FastAPI アプリ (REST + WS)
      server_launcher.py # Launcher / プロジェクト / ビルド / ダミーの REST + /ws/logs
      main.py          # エントリ: `ros2 run roshanavi server`
      static/          # web のビルド成果物 (git 管理外、ビルドで生成)
    test/              # pytest (unit + rclpy 統合)
  web/                 # Vite + React (§6.2)。e2e/ は Playwright
  examples/scenarios/  # サンプルシナリオ
```

## 4. バックエンド詳細

### 4.1 ros_runtime
- 単一ノード `roshanavi` を生成し、`MultiThreadedExecutor` をデーモンスレッドで spin。
- FastAPI (asyncio) からの操作はロックで保護したメソッド経由。購読コールバックは統計更新のみ行い軽量に保つ。
- 自分自身 (ノード名 `roshanavi*`) はグラフ・統計から既定で除外 (`show_self` オプション)。

### 4.2 graph
- `get_node_names_and_namespaces()`, `get_topic_names_and_types()`, `get_publishers_info_by_topic()`, `get_subscriptions_info_by_topic()` から構築。
- 出力: `{nodes:[{id,name,namespace,role}], topics:[{name,types[]}], edges:[{node,topic,dir:"pub"|"sub",qos:{reliability,durability,history,depth,deadline_ms,liveliness,lease_ms}}], diagnostics:[...]}`
  - `deadline_ms` / `lease_ms` は未設定・無制限なら `null`。
  - `role`: 実ノードは Launcher の対応づけ (§4.9) で `mine` / `dependency` / `dummy` になり、`target_id` と `confidence` (`exact`/`heuristic`) が付く。対応づかないノードは `"other"`。同じ完全修飾名のノードが複数あっても 1 つにまとめる。実行中の注入ジョブ (topic を持つもの) は仮想ノード `dummy:<job id>` (`role:"dummy"`, `job_id`) として pub エッジ付きで含める。注入の publisher は roshanavi 自身のノード (既定で非表示) に属するため、ジョブ単位の仮想ノードにしないと注入が地図に現れない。bag ジョブは `rosbag2_player` が通常ノードとして見えるので仮想ノードにしない。
  - `diagnostics` (`diagnostics.py` / `qos_compat.py`, 純関数): `{code, severity, topic, nodes[], detail}`。重大度順 (error → warning) で決定的に並べる。
    - `qos_incompatible` (error): topic ごとに pub × sub の全組を判定。reliability (BEST_EFFORT pub → RELIABLE sub)、durability (VOLATILE pub → TRANSIENT_LOCAL sub)、deadline (pub の deadline > sub の要求、pub 無制限で sub 有限も不可)、liveliness (AUTOMATIC pub → MANUAL_BY_TOPIC sub)、lease (pub > sub)。`detail.reasons=[{policy,pub,sub}]`。
    - `no_subscriber` / `no_publisher` (warning): 片側しかいないトピック。隠しトピック (`_` で始まる区切り)、`/rosout`、`/parameter_events`、roshanavi 自身しか端点を持たないトピックは対象外。
    - `similar_names` (warning): pub のみのトピックと sub のみのトピックの組で、`_`/`-`/大小文字を除くと同一、または同じ名前空間で最後の区切りの Levenshtein 距離 ≤ 2 (4 文字以下の名前は ≤ 1)。
    - `type_mismatch` (error): 同名トピックに複数の型。
  - 文言は UI 側の i18n 辞書で組み立てる (API は英語のコードと構造化データのみ)。
- 1 秒周期でスナップショットを更新し、変化時のみ WS 送信 (ハッシュ比較)。

### 4.3 traffic
- 新規トピックを 1 秒周期で検出し `create_subscription(msg_type, topic, cb, qos, raw=True)` で購読 (デシリアライズしない)。
- QoS 互換: 当該トピックの publisher に BEST_EFFORT が 1 つでもあれば BEST_EFFORT で購読、それ以外 RELIABLE。durability は VOLATILE、depth 10。
- 購読コールバックは 2 引数 `(data, info)` で、rclpy Jazzy が `raw=True` でも渡す `MessageInfo` (dict: `source_timestamp`, `received_timestamp` [ns], `publication_sequence_number`, `reception_sequence_number`) を使う。`publisher_gid` は Jazzy では公開されないため gid は常に none (publisher 別集計は gid が取れる場合のみ)。サンプルは (受信 monotonic 時刻, size, source_ts, received_ts, gid, seq)。純粋な統計計算は `stats.py` (時計注入可)。
- 統計 (スライディングウィンドウ既定 5 秒): `hz`, `hz_basis` (`"source"`|`"receive"`), `hz_recv`, `hz_source`, `bytes_per_sec`, `avg_size`, `jitter_ms`, `jitter_recv_ms`, `dropped`, `drop_ratio`, `latency_ms`, `last_seen`, `total_count`。スパークライン用に 1 秒刻みの hz 履歴を 60 点保持。
  - `hz_recv`/`jitter_recv_ms`: 受信時刻の間隔 ((n-1)/span, 標準偏差)。`ros2 topic hz` 相当で、欠落・購読遅れで過小評価し転送ジッタを含む。
  - `hz_source`: publisher 側レート。publisher (gid) ごとに source_timestamp 間隔から算出して合算。連番が単調ならロスした分も publish 数に数える。全サンプルの source_timestamp が 0/未対応なら null で、`hz`/`jitter_ms` は受信側にフォールバック (`hz_basis="receive"`)。`jitter_ms` は source 間隔の標準偏差 (publish ジッタ)。
  - `dropped`/`drop_ratio`: ウィンドウ内の publication_sequence_number の欠番 (publisher ごと)。連番が 0 / 非単調 (publisher 再起動、gid 無しでの複数 publisher の混在、RMW が未設定) の場合は `null`。
  - `latency_ms`: mean(received_timestamp - source_timestamp)。publisher と subscriber が同一ホスト (同一クロック) の場合のみ意味を持つ。
- 重い型 (`sensor_msgs/msg/Image`, `CompressedImage`, `PointCloud2`, `PointCloud`。LaserScan は含まない) は既定で購読せず `status:"not_monitored"`, `monitored:false` で一覧に残す (グラフ情報は表示)。`--monitor-heavy` で全て監視、`PUT /api/traffic/{topic}/monitor` `{"enabled": bool}` でトピック単位に実行時切替 (既定より優先、任意のトピックを無効化も可)。購読の張り替えは次回の housekeeping (<=1 s) で反映され、`monitored` は即時に更新される。
- 除外: 正規表現リスト (既定で `/rosout`, `/parameter_events` は統計対象だが UI で畳む)。型解決できないトピックは `unsupported` として記録し購読しない。
- 消えたトピックは購読解除。
- **送信元ごとの値 (`rates.py`, 純関数)**: 統計はトピック単位で、rclpy Jazzy の `MessageInfo` には publisher gid がないため、受信したサンプルの送信元は区別できない。そこで roshanavi が正確に分かる値から地図のエッジ用に分ける。`/api/traffic` と `/ws/live` の各エントリに `source_count` と `publishers:[{node, hz, bps, basis}]` を付ける。
  - 注入ジョブ (`dummy:<id>`): 実際に送った件数から求めた送信レート (`Job.send_rate`、直近 5 秒、bytes/s は最初のメッセージのシリアライズ後サイズ × Hz) → `basis:"exact"`。恒久ダミーノード: 設定の `rate_hz` → `"configured"`。
  - それ以外の送信元が 1 つだけ: ダミーが無ければトピック合計そのもの (`"measured"`)、あれば `max(0, 合計 − ダミーの合計)` (`"estimated"`、UI に「推定」と説明)。bytes/s はダミー全員のサイズが分かるときだけ分ける。
  - それ以外の送信元が 2 つ以上: 分けられないので `"unknown"` (エッジに数値を出さず、トピックに「合計 X Hz / 送信元 N」)。受信側のエッジ (topic → sub) は常にトピック合計。

### 4.4 msgutil
- `resolve_type("std_msgs/msg/String")` → クラス (`rosidl_runtime_py.utilities.get_message`)。
- `template(type)` → 既定値インスタンスを `message_to_ordereddict` した dict (UI で YAML 編集の初期値)。
- `build(type, dict)` → `set_message_fields` でメッセージ生成。失敗時はフィールドパス付きの明確なエラー。
- `to_display(msg)` → dict 化、長い配列は先頭 N 要素 + 件数に切り詰め (画像・点群対策)。

### 4.5 expr (安全な式評価)
- Web 入力を `eval` しない。`ast.parse(mode="eval")` → 許可ノードのみ再帰評価: 数値/文字列リテラル, 四則・剰余・べき, 比較, 単項 ±, 三項演算子, 許可関数呼び出し。
- 変数: `i` (送信回数, 0 始まり), `t` (ジョブ開始からの秒), `now` (epoch 秒)。
- 関数: `sin cos tan abs min max round floor ceil sqrt random uniform(a,b) randint(a,b) str int float`、定数 `pi e`。
- 属性アクセス・添字・内包表記・lambda は拒否。べき指数や文字列長に上限 (DoS 防止)。
- メッセージ dict 中の文字列 `"${...}"` を式として評価。全体が `${...}` 一つなら評価結果の型をそのまま、文字列中に埋め込みなら文字列置換。

### 4.6 injector
- ジョブモデル: `{id, topic, type, qos, mode, payload, rate_hz?, count?, source?}`。`POST /api/inject` で開始、`DELETE /api/inject/{id}` で停止、`GET /api/inject` で一覧 (送信数・状態・エラー)。
- mode:
  - `once`: 1 回送信して完了。
  - `periodic`: `rate_hz` で送信、`count` 指定で自動終了。payload の `${}` は毎回評価 (= 式モードも兼ねる)。
  - `stream`: JSONL (1 行 1 メッセージ dict) または CSV (ヘッダ = フィールドパス, `a.b.c` 形式) を `rate_hz` で順送り、`loop` 可。
  - `bag`: `ros2 bag play <path> [--rate r] [--loop] [--topics ...]` をサブプロセス起動、停止で SIGINT。
- ファイルパス (stream / bag) は設定された `data_dir` (既定 `/data`) 配下のみ許可 (realpath で検査、パストラバーサル防止)。
- publisher はジョブごとに作成、終了時に破棄。

### 4.6.1 メディアファイル注入
`data_dir` 内のファイルを、型に合わせて変換して送る。デコードは ffmpeg (サブプロセス、パイプ経由) を使う。

| 入力 | 送信形式 | 備考 |
|---|---|---|
| PNG/JPG/BMP (単体・フォルダ) | `sensor_msgs/Image` (encoding 指定可: rgb8/bgr8/mono8) または `CompressedImage` | フォルダは名前順にスライドショーとして周期送信する |
| MP4/MKV/AVI | フレームに分解し、`Image` / `CompressedImage` で送る | 既定は動画の fps。`rate_hz`、開始・終了時刻、リサイズ、loop を指定可。`header.stamp` は送信時刻 |
| WAV/MP3/FLAC/OGG | PCM に変換し、チャンクに分けて送る | サンプルレート・チャンネル数・チャンク長 (既定 20 ms) を指定可。実時間のペースで送る |

- **音声の型**: ROS 2 コアに標準の音声 msg はない。`audio_common_msgs` (AudioData / AudioDataStamped / AudioInfo) が使える環境ならそれを優先し、なければ `std_msgs/UInt8MultiArray` (PCM S16LE) を既定にする。型はプロジェクト設定で選べる。
- 巨大なファイルは逐次デコードし、メモリに全展開しない。

### 4.6.2 latency の対応づけモード (§5)
- `match: header.stamp` (既定): 出力が入力の stamp を引き継ぐノード向け。
- `match: order`: 受信順に対応づける近似。stamp を引き継がないノード向け。取りこぼしがあるとずれるため、`throughput` と併用を推奨し、結果に「近似」と表示する。

### 4.7 echo
- `WS /ws/echo/{topic}` 接続中のみデシリアライズ購読し、最大 10 Hz に間引いて `to_display` を送る。接続切断で購読解除。

### 4.8 server API

| Method | Path | 内容 |
|---|---|---|
| GET | `/api/graph` | グラフスナップショット |
| GET | `/api/traffic` | 統計一覧 (各エントリに `monitored`, `status`: ok/not_monitored/unsupported/error) |
| PUT | `/api/traffic/{topic}/monitor` | `{"enabled": bool}` でトピック単位の監視 on/off |
| GET | `/api/types` | 利用可能なメッセージ型一覧 |
| GET | `/api/types/{pkg}/msg/{name}/template` | テンプレ dict |
| POST/GET/DELETE | `/api/inject[/{id}]` | 注入ジョブ |
| GET | `/api/files` | data_dir 内のファイル一覧 (stream/bag 選択用) |
| GET/POST | `/api/scenarios`, `/api/scenarios/run` | シナリオ一覧・実行 (結果は JSON) |
| WS | `/ws/live` | 1 秒毎に `{traffic, graph?(変化時), jobs}` を push。traffic 各エントリに直近 1 秒の受信数 `recent_count` |
| WS | `/ws/echo/{topic}` | エコー |
| GET / POST | `/api/workspace`, `/api/workspace/refresh` | パッケージ・実行ファイル・launch ファイル一覧 (§4.9) |
| GET / POST | `/api/targets` | 起動対象の一覧 (状態・pid・対応ノード) / 登録 (`TargetSpec`) |
| GET / PUT / DELETE | `/api/targets/{id}` | 取得 / 設定の更新 (反映は再起動時) / 停止して削除 |
| POST | `/api/targets/{id}/start\|stop\|restart` | 起動・停止・再起動 |
| GET / DELETE | `/api/targets/{id}/logs?since=` | ログ (リングバッファ) の取得 / クリア。ビルドログは id `_build` |
| GET / POST / DELETE | `/api/build` | ビルドの状態 / 開始 `{package, restart_running}` (202) / 中止 |
| GET / PUT | `/api/project` | 作業中のプロジェクト + `dirty` / 全体を置き換えて保存 |
| POST | `/api/project/save`, `/api/project/reload` | 現在の内容を保存 / ファイルから読み直す |
| POST / PUT | `/api/dummies`, `/api/dummies/{id}` | 恒久ダミーの登録 / 更新 (`DummySpec`) |
| POST | `/api/inject/{job_id}/persist` | 注入ジョブを恒久ダミーノードにして起動 `{name, namespace?, autostart, stop_job}` |
| POST | `/api/dummies/export` | launch ファイル + 設定 YAML を書き出す `{directory, ids[]}` |
| WS | `/ws/logs/{id}` | ログのストリーム (`{log_id, lines:[{seq, ts, stream, text}]}`、0.2 秒ごと) |

- `/ws/live` は `targets` (起動対象の一覧) と `build` (ビルドの状態) も毎秒送る。

- 入力は pydantic モデルで検証。既定 bind は `127.0.0.1` (Docker 内では `0.0.0.0` を明示指定し、ポート公開は compose 側で `127.0.0.1:8080:8080`)。
- エラーは `{error: {code, message}}` で返す。
- ローカル Web からの攻撃対策 (認証なし localhost bind 前提, `security.py` の ASGI ミドルウェア):
  - DNS rebinding: 全 HTTP/WS リクエストの `Host` を許可リスト (`localhost`, `127.0.0.1`, `[::1]` の任意ポート + 繰り返し指定可の `--allowed-host`) で検査。違反は 403 `forbidden_host` (WS は close 1008)。
  - Cross-site WebSocket hijacking: WS ハンドシェイクに `Origin` があれば http(s) origin かつ host が許可リスト内 (または `--allowed-origin` と完全一致) であること。違反は close 1008。Origin 無し (非ブラウザ) は許可。Vite dev (`http://localhost:5173`) は localhost で通る。
  - CSRF: POST/PUT/PATCH/DELETE でボディがある場合 `Content-Type: application/json` 必須、違反は 415 `unsupported_media_type`。ボディ無し DELETE は可。
  - Docker では compose が `127.0.0.1:8080:8080` を公開するためホストからの Host は `localhost:8080`/`127.0.0.1:8080` で許可される。別名でアクセスする場合は `--allowed-host` を足す。

### 4.9 Launcher (P3)

自分のノードと依存ノードを GUI で起動・停止・再起動し、ログを見て、ビルドし直す (§0.1 の 3)。`roshanavi/launcher/`。

**ワークスペースの走査 (`discovery.py`)**
- ワークスペースは `--workspace` (既定: `$ROSHANAVI_WORKSPACE` → カレントディレクトリ)。`install/` (分離・merged 両方) を先に、続いて `AMENT_PREFIX_PATH` を overlay 順に見る。
- パッケージ = ament index (`share/ament_index/resource_index/packages`)。実行ファイル = `lib/<pkg>/` の実行可能ファイル、launch ファイル = `share/<pkg>/launch/` (2 階層まで) の `*.launch.{py,xml,yaml}` と `*_launch.{py,xml,yaml}`。
- `origin`: `<ws>/install` 由来なら `workspace`、それ以外は `system`。`sourced`: サーバー起動時の `AMENT_PREFIX_PATH` に入っていたか。`src/` の `package.xml` を走査して `source_dir` を付ける (`COLCON_IGNORE` 等は除外)。未ビルドのパッケージも `built:false` で一覧に出す (ビルドボタン用)。
- 結果はキャッシュし、`POST /api/workspace/refresh` とビルド成功時に再走査する。

**プロセス管理 (`process.py` / `target.py` / `manager.py`)**
- `subprocess.Popen(argv list)` のみ (シェルは使わない)。`start_new_session=True` で新しいセッション = プロセスグループにし、`ros2 launch` が起こす子孫も同じグループに入れる。
- 停止: グループに SIGINT → 5 秒待つ → SIGTERM → 3 秒 → SIGKILL。開始時点の子孫のうちグループ外に出たものも最後に kill する。
- 状態: `stopped` / `starting` (起動後 2 秒) / `running` / `exited` (自分で 0 終了) / `crashed` (自分で非 0 終了) / `invalid` (設定が検証を通らない。例: パッケージが消えた)。稼働時間、再起動回数、`pending_restart` (実行中に設定を変えた) を返す。世代番号で、古いプロセスの終了通知が新しいプロセスの状態を上書きしないようにする。
- 自動再起動 (`auto_restart`、既定 off): `crashed` のとき 1, 2, 4 … 最大 30 秒のバックオフで再起動する。30 秒以上動いたら間隔を戻す。ユーザーが止めたら再起動しない。
- ログ: stdout / stderr を行単位で読み、`stream` タグ付きでターゲットごとのリングバッファ (5000 行) に入れる。起動コマンドと終了コードは `system` 行として残す。子プロセスの環境に `PYTHONUNBUFFERED=1`, `RCUTILS_LOGGING_BUFFERED_STREAM=0`, `RCUTILS_COLORIZED_OUTPUT=0` を入れ、遅延と色コードをなくす。
- サーバー終了時に全ターゲットを並列に停止する。uvicorn の SIGINT/SIGTERM 処理の後の `finally`、SIGHUP → SIGTERM への読み替え、`atexit` の 3 経路で呼ぶ (冪等)。サーバー自身が SIGKILL された場合だけは子が残る (制約)。

**入力の検証 (`validate.py` / `command.py`)** — 値はすべて argv の 1 要素として渡すが、`ros2 run` / `ros2 launch` / rcl 自身が解釈する argv (`--prefix`, `--ros-args`, `--params-file`, `__node:=` …) を利用者の値に紛れ込ませないため、厳しく検査する。
- package / executable / launch file は正規表現 (先頭 `-` 不可、`..` 不可) に加え、**走査結果に存在すること**。
- パラメータ: 名前は `^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$`、値は制御文字不可・4096 文字まで。`-p name:=value` の 1 要素で渡す (bool は `true`/`false`)。
- リマップ: 両側とも rclpy の `validate_topic_name` を通り、`__` で始まらないこと (`__node` 等の特殊リマップは専用欄のみ)。ノード名・名前空間は `validate_node_name` / `validate_namespace`。
- `run` の追加引数: `--ros-args`, `--`, `-r`, `-p`, `--params-file`, `-e`, `--prefix`, `--ros-*`, `--log-*` などと、`__xxx:=` 形式を拒否する。`launch` の引数は `name:=value` のみ (名前は識別子)。launch には name / namespace / params / remaps を渡さない (スキーマで拒否)。
- パラメータファイル: `realpath` がワークスペースか data_dir の内側にある既存の `.yaml` であること (`..`、絶対パス、外向き symlink を拒否)。
- 生成される argv: `ros2 run <pkg> <exe> [args…] --ros-args -r __node:=<name> -r __ns:=<ns> -p k:=v … -r a:=b … --params-file <path>` / `ros2 launch <pkg> <file> k:=v …`。

**まだ source されていないパッケージ (`env.py`)** — サーバー起動後に初めてビルドしたパッケージは `AMENT_PREFIX_PATH` 等に入っていない。colcon が各パッケージに書く `share/<pkg>/package.dsv` (`prepend-non-duplicate;PYTHONPATH;…` などの宣言的な形式) を読んで子プロセスの環境に適用し、`AMENT_PREFIX_PATH` にもプレフィックスを足す。シェルスクリプトは実行しない。これで roshanavi から起動するノードはすぐ使えるが、利用者のターミナルでは `source install/setup.bash` のやり直しが必要 (UI に「未 source」バッジと説明を出す)。

**ビルドボタン (`build.py`)**
- `colcon build --packages-select <pkg> --symlink-install --event-handlers console_direct+` をワークスペース直下で実行する。同時に 1 つだけ (409 `build_running`)。対象は `src/` にある workspace パッケージのみ (`not_buildable`)。ログは id `_build`。
- 判定: 終了コード 0 でも「`ignoring unknown package`」「`Summary: 0 packages finished`」なら失敗とする (setup.py が壊れていると colcon はパッケージを認識できず 0 で終わるため)。失敗時は最初のエラー行 (`error:`, `CMake Error`, `…Error: `, `Traceback`, `Failed <<<` から最大 12 行) を `error_lines` に入れて UI に出す。
- 成功時は走査をやり直し、`restart_running` (既定 on) なら、そのパッケージの実行中ターゲットを再起動する (`restarted`)。未 source だったパッケージは `needs_resource:true` として UI で案内する。

**ノード ⇄ プロセスの対応づけ (`process_map.py`)** — 次フェーズの CPU / メモリ計測 (RESOURCES.md) でもそのまま使う。
- 純関数 `map_nodes(nodes, targets, first_seen, baseline, sticky)` と、状態を持つ `NodeProcessMapper` (初出時刻・ベースライン・確定済みの推定) に分ける。プロセスツリーは psutil (`process_tree(pid)`: ルート + 子孫を深さ順)。
- **exact**: ターゲットのプロセスツリーの argv に `__node:=<name>` (と `__ns:=`、`node:__node:=` 形式も) があれば一致。`ros2 run` のラッパーと実行ファイルの両方に付くため、最も深いプロセスを pid とする。launch_ros は `Node(name=…)` のときに付け、Launcher はノード名を入力したときに付ける。
- **heuristic**: ターゲットの (再) 起動から 20 秒以内に初めて現れ、他のターゲットが exact で持っていないノード。候補が複数あれば、実行ファイル名とノード名が一致するターゲット、なければ最後に起動したターゲット。一度決まった推定は、そのターゲットが生きている間は保持する。
- ベースライン: 自分のプロセスが 1 つも動いていない間に見えたノードは推定の対象外 (消えたらベースラインからも外す)。autostart はサーバー起動の 2 秒後に行い、既存ノードの発見を先に済ませる。roshanavi 自身のノードは対象外。
- 限界 (UI に「推定」と出す): composable node はコンテナプロセス単位 (コンテナ内のどのノードかは分からない)。別コンテナ (PID 名前空間が別) や別 PC のノードは対応づけない。起動直後に無関係のノードが同時に現れると推定を誤ることがある (ノード名を付ければ exact になる)。

**役割**: グラフの各ノードに `role` を付ける。`mine` (ターゲットの「開発中」フラグ)、`dependency` (それ以外のターゲット)、`dummy` (注入ジョブの仮想ノードと恒久ダミーノード)、`other`。対応づいたノードには `target_id` と `confidence` (`exact`/`heuristic`) も付ける。

### 4.10 プロジェクトファイルと恒久ダミーノード (P3)

**`roshanavi.yaml`** (既定: ワークスペース直下、`--project PATH` で変更。Docker の lab は `/data/roshanavi.yaml`)
```yaml
version: 1
targets:
- id: talker               # [a-z0-9][a-z0-9_-]{0,63}、targets と dummies で一意
  kind: run                # run | launch
  package: demo_nodes_cpp
  executable: talker       # kind: launch なら launch_file
  name: my_talker          # 以下は任意 (run のみ: name / namespace / params / params_file / remaps)
  params: {rate: 2, use_sim_time: false}
  remaps: {chatter: /chat}
  args: []                 # run: 実行ファイルへの追加引数 / launch: ["name:=value", ...]
  role: mine               # mine | dependency
  autostart: true
  auto_restart: false
dummies:
- id: cam
  name: dummy_camera       # ROS ノード名
  topic: /camera/info
  type: std_msgs/msg/String
  mode: periodic           # once | periodic | stream (bag は不可)
  payload: {data: "frame ${i}"}
  rate_hz: 5
  qos: {reliability: reliable, durability: volatile, depth: 10}
  autostart: true
watch_topics: [/chat]
```
- pydantic のスキーマで検証する。未知のキーは拒否し、エラーはパス付き (`targets.0.colour: extra fields not permitted`、YAML の構文エラーは行・列付き)。
- 保存は同じディレクトリの一時ファイル → fsync → `os.replace` (原子的)。キーはスキーマ順、空の値は省いて書く (差分が安定し、git で読みやすい)。
- サーバーは起動時に読み込み、作業中の内容 (起動対象とダミーの登録・変更) との差を `dirty` として返す。UI の「プロジェクトに保存」で明示的に保存する。パッケージが見つからないなど検証を通らないターゲットも、`invalid` 状態で一覧に残す (古いプロジェクトでも開ける)。
- `autostart: true` のターゲットとダミーはサーバー起動時に起動する (`--no-autostart` で無効)。

**恒久ダミーノード (`dummy_node.py`)**
- `ros2 run roshanavi dummy --config <yaml> --ros-args -r __node:=<name>`: 1 つの注入 (once / periodic / stream、`${}` 式、JSONL / CSV) を **独立した ROS ノード** として実行する。injector をそのまま使い、SIGINT / SIGTERM まで動き続ける (once や count 付きでも、送り終えた後もノードは残る)。設定エラーは終了コード 2、注入エラーは 1。
- Launcher が `kind: dummy` のターゲットとして管理する (役割 `dummy`、ノード名を `__node:=` で渡すので対応づけは exact)。設定 YAML (`{dummy: <DummySpec>, data_dir}`) はサーバーの一時ディレクトリに書く。
- 注入タブの実行中ジョブから「常駐ノードにする」で、同じペイロード・モード・レート・QoS の恒久ダミーを作って起動し、元のジョブは止める (`POST /api/inject/{id}/persist`)。
- **書き出し**: ワークスペース内の指定ディレクトリ (realpath で包含を検査、なければ作る) に `<id>.yaml` と `roshanavi_dummies.launch.py` を書く。`ros2 launch <dir>/roshanavi_dummies.launch.py` で、roshanavi のサーバー / UI なしで動く。ただし roshanavi パッケージのインストールは必要 (各ノードが `roshanavi dummy` を実行するため。生成ファイルの先頭に明記)。ノード名・ID は検証済みの値だけを `repr()` で埋め込む。

## 5. シナリオ (G4)

対象ユースケース: **センサー処理パイプライン** (画像・点群の前処理・認識) と **自作ノード群** (独自 msg, 状態遷移)。MVP はトピックのみ (サービス・アクションは今後対応、README に明記)。

### 5.1 ステップの種類

| ステップ | 意味 |
|---|---|
| `send` | 1 件送る (式 `${}` 可) |
| `start` / `stop` | 周期送信やストリームを裏で開始・停止する (`id` で参照) |
| `play` | bag を再生する (`topics` で絞り込み可、`wait: true` で再生終了まで待つ) |
| `wait` | 指定秒待つ |
| `expect` | `within` 秒以内に、`where` を満たすメッセージが `count` 件届く |
| `always` | `for` 秒間、届くメッセージがすべて `where` を満たす (最低 1 件届くこと、`min_count` で変更可) |
| `never` | `for` 秒間、`where` を満たすメッセージが 1 件も来ない (`where` 省略時は「何も来ない」) |
| `rate` | `for` 秒間の周期が `min_hz..max_hz` に入る |
| `throughput` | 入力トピックの件数に対する出力トピックの件数の比が `min_ratio` 以上 (取りこぼし・フレーム落ちの検出) |
| `latency` | 入力と出力を `match` (`header.stamp` または `order`, §4.6.2) で対応づけ、処理時間の `p50/p95/max` を上限で判定 |

加えて、シナリオ全体に掛かる **`guards`** を持てる。例: 「シナリオ中ずっと `/state` が ERROR にならない」。`never`/`always` と同じ書き方で、どのステップの最中に破れても fail にする。

### 5.2 例

```yaml
# センサー処理: bag の画像を流し、検出ノードの出力・取りこぼし・処理時間を確認
name: detector_basic
setup:
  - cmd: ["ros2", "launch", "my_perception", "detector.launch.py"]
    wait_for_node: /detector
steps:
  - play: {id: cam, bag: bags/street_30s, topics: [/camera/image_raw]}
  - expect: {topic: /detections, within: 3.0}
  - throughput: {input: /camera/image_raw, output: /detections, for: 10.0, min_ratio: 0.95}
  - latency: {input: /camera/image_raw, output: /detections, match: header.stamp, p95_ms: 100}
  - stop: cam
  - never: {topic: /detections, for: 1.0}    # 入力が止まれば出力も止まる
```

```yaml
# 自作ノード: 状態遷移
name: state_machine
guards:
  - never: {topic: /state, where: [{field: data, op: eq, value: ERROR}]}
steps:
  - send: {topic: /cmd, data: {data: start}}
  - expect: {topic: /state, within: 1.0, where: [{field: data, op: eq, value: RUNNING}]}
  - send: {topic: /cmd, data: {data: stop}}
  - expect: {topic: /state, within: 1.0, where: [{field: data, op: eq, value: IDLE}]}
```

```yaml
# センサー途絶
name: lidar_dropout
steps:
  - start: {id: scan, topic: /scan, stream: streams/scan.jsonl, rate_hz: 10, loop: true}
  - wait: 2.0
  - stop: scan
  - expect: {topic: /diagnostics, within: 1.0, where: [{field: status.0.level, op: eq, value: 2}]}
```

### 5.3 判定ルール
- **取りこぼし防止**: runner はシナリオ開始時に、シナリオ内で参照される全トピックを先に購読し、受信時刻付きでバッファする。各判定ステップは「そのステップ開始時刻以降」に受信したメッセージを評価する。heavy 型 (§4.3) も、シナリオ中は参照トピックに限って購読する。
- `where` の op: `eq ne lt le gt ge range approx(tol) regex contains exists len_eq len_range`。field はドット区切り + 配列添字 (`detections.0.bbox.center.position.x`)。`len_*` は配列長 (例: 検出数)。
- 失敗時は「何が来て何が足りなかったか」を平易に出す (受信件数、最後に受信した値、条件ごとの不一致箇所)。参照トピックに publisher がいない、QoS が不一致、などの原因候補も併記する。
- CLI: `ros2 run roshanavi scenario run <file|dir> [--junit out.xml]` → 失敗時 exit 1。
- Python API (`roshanavi.scenario.run_scenario(path) -> Result`) を公開し、launch_pytest からも使える。

### 5.4 UI での作り方: 記録モード (主軸)
YAML は保存・CI 用の形式であり、ユーザーは原則として手で書かない。

1. **記録開始**: 確認したい出力トピック (watch) を選び、記録を始める。
2. **入力操作がステップになる**: UI からの送信・開始・停止・bag 再生が、そのまま `send`/`start`/`stop`/`play` になり、操作の間隔は `wait` になる。
3. **出力をクリックして期待値にする**: watch トピックのタイムラインに流れたメッセージをクリックし、「これが来るはず」を選ぶと `expect` ができる。
   - フィールドは自動で選ぶ: スカラー値は `eq`、浮動小数は `approx`。`header.stamp` やカウンタのように毎回変わる値は既定で除外し、チェックボックスで調整できる。
   - `within` は実測の応答時間に余裕を持たせた値 (例: 実測 × 3、最低 0.5 秒) を既定にする。
4. **種類を変える**: 作った期待を `always`/`never`/`rate`/`throughput`/`latency` に切り替えられる (範囲選択した区間を `for` に使う)。
5. **保存して再実行**: 保存すると YAML になり、Scenarios タブと CLI から再実行できる。

## 6. フロントエンド

タブ: **Graph** / **Traffic** / **Inject** / **Launcher** / **Scenarios**。右ペインに選択トピックの詳細 (統計・エコー・注入ショートカット)。
- Graph (**ライブ通信マップ**, §6.1)
- Traffic: ソート可能な表 + 行内 uPlot スパークライン。停止トピック (last_seen > 3 s) を強調。
- Inject: トピック選択 → 型自動入力 → テンプレ YAML エディタ → mode 別フォーム → 開始。実行中ジョブ一覧と停止ボタン。
- Scenarios: examples ディレクトリのシナリオ一覧 / 実行 / ステップ別結果表示。
- Launcher (§6.3): パッケージ選択 → 起動設定 → 起動対象の一覧・ログ・ビルド。

### 6.1 ライブ通信マップ (Graph タブ)
ノードとトピックがどうつながり、いまどこに通信が流れているかを、リアルタイムに一目で分かるようにする。

**レイアウト**
- Cytoscape + dagre で左→右のデータフロー配置にする (入力元 → 処理 → 出力先)。トポロジーが変化してもアニメーションで追従し、既存要素の位置は保つ。
- ノード=角丸、トピック=楕円。ノードは役割で色分けする: **自分のノード** (Launcher で起動) / **依存ノード** / **ダミーノード** / その他。

**通信の見せ方**
- エッジの太さ ∝ log(帯域)。エッジ上に `10.0 Hz · 1.2 MB/s` のラベルを付ける (ズームに応じて省略)。
- **流れのアニメーション**: publisher → トピック → subscriber の向きに粒が流れ、粒の頻度が Hz に比例する (上限あり)。1 Hz 以下の低頻度トピックは、受信のたびにエッジを一瞬光らせる。
- 状態の色分け: 通信中 / 停止 (`last_seen` > 3 s, 破線グレー) / 取りこぼしあり (`drop_ratio` > 0, 橙) / 非監視 (heavy 型, 点線)。
- ノードの縁取りの濃さ = そのノードの入出力帯域の合計。

**ROS 初心者向けの指摘 (診断)**
- **QoS 不一致**: reliability / durability が非互換で、つながっていない pub–sub を赤い破線で描き、理由を平易に表示する (例: 「送信側は BEST_EFFORT、受信側は RELIABLE のため届きません」)。
- **相手がいない**: publisher しかいない / subscriber しかいないトピックに印を付ける。
- **名前の取り違え候補**: 編集距離が近いトピック名 (`/cmd_vel` と `/cmdvel` など) で、片方に pub、片方に sub しかない場合に警告する。
- **型の不一致**: 同名トピックで型が異なる場合に警告する。

**操作**
- ノードやトピックをクリックすると、上流・下流の経路を強調し、それ以外を薄くする (フォーカスモード)。右ペインに詳細 (統計、エコー、注入、ログ) を出す。
- 名前フィルタ、`/rosout` 等の非表示トグル、一時停止 (スナップショットを固定して観察する)。

**計測の限界 (UI に明記する)**
- 帯域や Hz は **トピック単位** の値である。subscriber ごとに実際に届いた量は、外部からは測れない。必要なら対象ノード側の Topic Statistics かトレースを使う (将来対応)。
- 更新は 1 秒周期。流れのアニメーションは見た目の表現であり、1 粒 = 1 メッセージではない。

**バックエンドへの追加要件**
- `/ws/live` に、トピックごとの直近 1 秒の受信イベント数を含める (低頻度トピックを光らせるため)。
- グラフスナップショットに QoS 互換性の判定結果と、診断の警告リストを含める (判定はバックエンドで行い、テスト可能にする)。
- ノードの役割 (自分 / 依存 / ダミー) は、Launcher とダミーノードの管理情報から付与する。

### 6.2 実装メモ (P2)

**構成 (`web/`)**: Vite + React 19 + TypeScript (strict)。依存はすべて完全一致でピン留め (`package-lock.json`)。
- `src/tabs/registry.tsx`: タブ定義 `{id, label, keepMounted, render}`。Launcher / Scenarios は ここに追加する。Graph と Inject は非表示中もマウントしたまま (レイアウト・入力を保持)。
- `src/detail/DetailPane.tsx`: 右ペイン。選択 (topic / node) ごとにセクションを並べる (統計・エコー・注入ショートカット・監視切替)。ログや画像ビューアは後のフェーズで追加する。
- `src/i18n/messages.ts`: UI 文言の唯一の辞書 (既定は日本語)。英語は同じキーで `locales.en` を足せば切り替わる (欠けたキーは日本語にフォールバック)。
- 純粋ロジック (vitest): `graph/model.ts` (スナップショット → 要素、状態・太さの写像、フィルタ)、`graph/diff.ts` (差分パッチ)、`graph/focus.ts` (上流・下流)、`graph/particles.ts` (粒のシミュレーション)、`graph/diagnosticsText.ts` (診断の文章化)、`traffic/sort.ts`、`inject/buildRequest.ts`、`state/live.ts`、`api/reconnect.ts`、`lib/format.ts`。

**ライブ通信マップの決定事項**
- **差分更新**: 毎秒の要素リストを前回と比較し、追加・削除・data 更新だけを cytoscape に適用する。dagre レイアウトは **トポロジーが変わったときだけ** アニメーション付きで再実行する (統計の変化では位置は動かない)。新しい要素は隣接ノードの位置から生えるように置く。dagre は決定的なので、変化のない部分の位置はほぼ保たれる。ただしユーザーがドラッグした位置はトポロジー変化時に再配置される (P2 の制約)。
- **流れの粒は canvas オーバーレイで描く**: cytoscape のスタイル (例: `line-dash-offset`) をフレームごとに変えると、そのたびに cytoscape がグラフ全体を再描画するため、200 要素 × 60 fps では重い。オーバーレイなら cytoscape の再描画はデータ更新時 (1 Hz) だけで、粒は色ごとに 1 本の Path2D でまとめて描く。エッジ端点 (モデル座標) はノード移動時だけ再計算してキャッシュし、描画時に pan/zoom で変換する。粒の頻度は `min(6, 1 + sqrt(hz - 1))` 個/秒、総数上限 1200。計測 (Playwright, headless Chromium, 180 要素 + 粒): 約 60 fps (`web/e2e/perf.spec.ts`)。
- **低頻度 (≤ 1 Hz)**: 連続放出せず、`recent_count > 0` の tick ごとにエッジを光らせて 1 粒流す (実際の受信に同期)。
- **状態**: 通信中 = 青実線 / 停止 (`last_seen` > 3 s) = 灰破線 / 取りこぼし (`drop_ratio` > 0) = 橙 / 非監視 = 灰点線 / QoS 不一致 = 赤破線 + 終端 T 字。QoS 不一致は受信側エッジ (topic → sub) に付け、ホバーで理由を表示する。粒は流さない。
- **太さ**: エッジ = `1.5 + 1.2·log10(1 + B/1000)` px (上限 10)、ノード縁取り = `1 + log10(1 + 入出力帯域合計/1000)`。
- **ラベル**: `10.0 Hz · 1.2 KB/s`。cytoscape の `min-zoomed-font-size` でズームアウト時に自動で省略する。
- **一時停止**: 表示中のスナップショットと粒を固定する。裏では受信を続け、再開時に最新へ追従する。
- **フォーカス**: クリックした要素から有向辺をたどった上流・下流以外を薄くする。エッジのクリックはそのトピックの選択として扱う。診断のクリックで対象トピックを選択・フォーカスする。
- **アクセシビリティ / E2E**: 地図の内容を視覚的に隠したリスト (`data-testid="graph-outline"`) としても出力する。

**エコー**: 右ペインでトピックを選ぶと、監視対象 (重い型でない) なら自動で `/ws/echo` を開始する。重い型は「エコーを開始」で明示的に開始する。

**配信とビルド**
- `npm run build` は `ros2_ws/src/roshanavi/roshanavi/static/` (git 管理外) に出力し、`setup.py` が package data としてインストールする → `ros2 run roshanavi server` が `/` で UI を配信する。
- Docker: `docker/Dockerfile` の第 1 段 (`node:24.14.0-bookworm-slim`) で `npm ci` + build し、成果物を `/opt/roshanavi/static` に焼き込む。`lab` はソースを bind mount するため package data に頼らず、`ROSHANAVI_STATIC_DIR` 環境変数 (main.py の `--static-dir` 既定値) で参照する。UI を変更したら `docker compose build lab`。

**実行方法**
```bash
# Docker で UI + デモ
docker compose up -d --build lab demo        # http://localhost:8080
# UI 開発 (ホットリロード; /api と /ws は :8080 にプロキシ)
cd web && npm ci && npm run dev              # http://localhost:5173
# テスト
cd web && npm test                           # vitest (純粋ロジック)
docker compose --profile test run --rm test  # バックエンド pytest
docker compose --profile e2e run --rm e2e    # Playwright (lab + demo 起動中に)。スクリーンショットは docs/screenshots/
```

### 6.3 実装メモ (P3: Launcher)
- **Launcher タブ** (`src/launcher/`): 左にパッケージ一覧 (検索、ワークスペースのパッケージを先頭、「ワークスペース」「システム」「未ビルド」「未 source」バッジ、ビルドボタン)、中央に起動設定フォーム・ビルド結果・起動対象のカード、右にログビューア。上部のプロジェクトバーに保存先、未保存バッジ、保存・読み直しボタン。
  - 起動設定: ノード名、名前空間、パラメータ (名前・値の行。`true`/`false` と数値はその型)、リマップ、パラメータファイル、追加引数 / launch 引数、「開発中 (自分のノード)」、自動起動、自動再起動。クライアント側でもサーバーと同じ規則で先に検査し、平易な文で示す (`launcher/form.ts`)。
  - カード: 状態チップ、起動コマンド、稼働時間・再起動回数、対応づいたノードと「確実 / 推定」バッジ (説明はツールチップ)、起動・停止・再起動・ログ・編集・削除。
  - ログビューア (`/ws/logs/{id}`): 最新に追従、stderr と `[ERROR]`/`error:` 行を強調、検索、エラー・警告だけ表示、クリア。表示は最大 5000 行 (`launcher/logs.ts`)。
  - ビルド結果: 成功 / 失敗、最初のエラー行、再起動したノード、未 source の案内。
- **注入タブ**: 実行中ジョブに「常駐ノードにする」(ノード名を入力、既定 `dummy_<トピック末尾>`)、常駐ダミーノードの一覧 (起動・停止・自動起動・ログ・削除) と launch ファイルへの書き出し。
- **右ペイン (ノード)**: 起動対象、プロセスの状態と pid、対応づけ (確実 / 推定と理由)、稼働時間、再起動ボタン、「ログを開く」(Launcher タブへ)。
- 地図の役割色は P2 の凡例どおり (自分 = 緑、依存 = シアン、ダミー = マゼンタ、その他 = グレー)。注入ジョブの仮想ノードはジョブ ID 付きのラベル、恒久ダミーはノード名で表示する。
- スクリーンショット: `docs/screenshots/launcher.png`, `graph-roles.png`, `graph-node-launcher.png` (`e2e/launcher.spec.ts`)。
- **地図からノードを操作** (`graph/nodeControl.ts` 純関数, `NodeMenu.tsx`, `detail/NodeControls.tsx`): 地図のノードの右クリックメニューと右ペインに 停止 / 再起動 (止まっている起動対象には 起動)。新しい API は作らず既存の `POST /api/targets/{id}/start|stop|restart` と `DELETE /api/inject/{id}` を使う。
  - 対象は roshanavi が起動したものだけ: Launcher の起動対象 (自分 / 依存 / 恒久ダミー) と注入ジョブ。その他のノードはボタンを無効にし、理由 (「roshanavi が起動したノードではないため停止できません…」) を出す。外部のプロセスにはシグナルを送らない。
  - launch ファイルや 1 プロセスに複数ノードがある起動対象 (composable container など) は、対応づけ (§4.9) で分かっている全ノードを確認ダイアログに列挙してから止める。
  - 右クリック (cytoscape `cxttap`) だけを使うので、左クリックの選択とドラッグでの移動はそのまま。メニューは矢印キーで移動、Escape / Tab で閉じる。キーボードだけの操作は右ペインのボタンで行える。

## 7. テスト方針
- unit: expr (許可/拒否ケース, DoS 上限), msgutil (テンプレ・build・エラーパス), traffic 統計計算 (時刻注入で決定的に), scenario schema/判定ロジック。
- 統合 (rclpy, Docker 内): publisher → traffic に Hz が出る / injector periodic → 受信数 / scenario 実行 pass・fail 両方 / API を TestClient で叩く。
- `docker compose run --rm test` 一発で全テスト。

## 8. フェーズ
1. ✅ P1 バックエンド核 + Docker (graph / traffic / msgutil / expr / injector / echo / server + テスト)
2. ✅ P1.5 セキュリティ強化 (Host/Origin/Content-Type)、MessageInfo による Hz・取りこぼし、heavy 型の opt-in
3. ✅ P2 Web UI 基盤 + ライブ通信マップ (§6.1, 診断を含む) + Traffic + Inject
4. ✅ P3 Launcher (§0.1 の 3, §4.9) + プロジェクトファイル + ビルドボタン + 恒久ダミーノード (§4.10)
5. P4 メディア注入 (§4.6.1) + 画像ビューア・音声の波形と再生
6. P5 サンプルノード (`roshanavi_examples`)
7. P6 シナリオ (runner / CLI / JUnit / 記録モード / Scenarios タブ)
8. P7 監査、README (サービス・アクションは今後対応予定と明記)、デモ GIF
