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
      traffic.py       # 全トピック raw 購読 + 統計
      msgutil.py       # 型解決 / テンプレ生成 / dict⇄msg / 表示用切り詰め
      expr.py          # AST ホワイトリスト式評価器 (eval 禁止)
      injector.py      # 注入ジョブ管理
      echo.py          # オンデマンド購読 → 最新メッセージ
      scenario/        # schema.py / runner.py / junit.py / cli.py
      server.py        # FastAPI アプリ (REST + WS)
      main.py          # エントリ: `ros2 run roshanavi server`
      static/          # web のビルド成果物 (git 管理外、ビルドで生成)
    test/              # pytest (unit + rclpy 統合)
  web/                 # Vite + React
  examples/scenarios/  # サンプルシナリオ
```

## 4. バックエンド詳細

### 4.1 ros_runtime
- 単一ノード `roshanavi` を生成し、`MultiThreadedExecutor` をデーモンスレッドで spin。
- FastAPI (asyncio) からの操作はロックで保護したメソッド経由。購読コールバックは統計更新のみ行い軽量に保つ。
- 自分自身 (ノード名 `roshanavi*`) はグラフ・統計から既定で除外 (`show_self` オプション)。

### 4.2 graph
- `get_node_names_and_namespaces()`, `get_topic_names_and_types()`, `get_publishers_info_by_topic()`, `get_subscriptions_info_by_topic()` から構築。
- 出力: `{nodes:[{id,name,namespace}], topics:[{name,types[]}], edges:[{node,topic,dir:"pub"|"sub",qos:{reliability,durability,history,depth}}]}`
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
| WS | `/ws/live` | 1 秒毎に `{traffic, graph?(変化時), jobs}` を push |
| WS | `/ws/echo/{topic}` | エコー |

- 入力は pydantic モデルで検証。既定 bind は `127.0.0.1` (Docker 内では `0.0.0.0` を明示指定し、ポート公開は compose 側で `127.0.0.1:8080:8080`)。
- エラーは `{error: {code, message}}` で返す。
- ローカル Web からの攻撃対策 (認証なし localhost bind 前提, `security.py` の ASGI ミドルウェア):
  - DNS rebinding: 全 HTTP/WS リクエストの `Host` を許可リスト (`localhost`, `127.0.0.1`, `[::1]` の任意ポート + 繰り返し指定可の `--allowed-host`) で検査。違反は 403 `forbidden_host` (WS は close 1008)。
  - Cross-site WebSocket hijacking: WS ハンドシェイクに `Origin` があれば http(s) origin かつ host が許可リスト内 (または `--allowed-origin` と完全一致) であること。違反は close 1008。Origin 無し (非ブラウザ) は許可。Vite dev (`http://localhost:5173`) は localhost で通る。
  - CSRF: POST/PUT/PATCH/DELETE でボディがある場合 `Content-Type: application/json` 必須、違反は 415 `unsupported_media_type`。ボディ無し DELETE は可。
  - Docker では compose が `127.0.0.1:8080:8080` を公開するためホストからの Host は `localhost:8080`/`127.0.0.1:8080` で許可される。別名でアクセスする場合は `--allowed-host` を足す。

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

タブ: **Graph** / **Traffic** / **Inject** / **Scenarios**。右ペインに選択トピックの詳細 (統計・エコー・注入ショートカット)。
- Graph (**ライブ通信マップ**, §6.1)
- Traffic: ソート可能な表 + 行内 uPlot スパークライン。停止トピック (last_seen > 3 s) を強調。
- Inject: トピック選択 → 型自動入力 → テンプレ YAML エディタ → mode 別フォーム → 開始。実行中ジョブ一覧と停止ボタン。
- Scenarios: examples ディレクトリのシナリオ一覧 / 実行 / ステップ別結果表示。

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

## 7. テスト方針
- unit: expr (許可/拒否ケース, DoS 上限), msgutil (テンプレ・build・エラーパス), traffic 統計計算 (時刻注入で決定的に), scenario schema/判定ロジック。
- 統合 (rclpy, Docker 内): publisher → traffic に Hz が出る / injector periodic → 受信数 / scenario 実行 pass・fail 両方 / API を TestClient で叩く。
- `docker compose run --rm test` 一発で全テスト。

## 8. フェーズ
1. ✅ P1 バックエンド核 + Docker (graph / traffic / msgutil / expr / injector / echo / server + テスト)
2. ✅ P1.5 セキュリティ強化 (Host/Origin/Content-Type)、MessageInfo による Hz・取りこぼし、heavy 型の opt-in
3. P2 Web UI 基盤 + ライブ通信マップ (§6.1, 診断を含む) + Traffic + Inject
4. P3 Launcher (§0.1 の 3) + プロジェクトファイル + ビルドボタン + 恒久ダミーノード
5. P4 メディア注入 (§4.6.1) + 画像ビューア・音声の波形と再生
6. P5 サンプルノード (`roshanavi_examples`)
7. P6 シナリオ (runner / CLI / JUnit / 記録モード / Scenarios タブ)
8. P7 監査、README (サービス・アクションは今後対応予定と明記)、デモ GIF
