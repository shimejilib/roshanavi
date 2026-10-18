# roshanavi — アーキテクチャ

## 技術選定

| 層 | 採用 | 理由 |
|---|---|---|
| ROS | rclpy (Jazzy / Python 3.12、Lyrical / Python 3.14。Kilted は動作確認のみ) | 動的型解決 (`rosidl_runtime_py`) で任意 msg を扱える |
| サーバー | FastAPI + uvicorn (Ubuntu の apt の python3-fastapi / python3-uvicorn。pydantic 1.10 / 2 の差は `pydantic_compat.py`) | REST + WebSocket。pip を使わず apt で揃える |
| フロント | Vite + React + TypeScript, Cytoscape.js (グラフ), uPlot (スパークライン) | ビルド成果物を FastAPI が静的配信 |
| 実行環境 | Docker (`ros:<distro>-ros-base` ベース、`ROS_DISTRO` で切り替え。既定 jazzy) + docker compose | ホストを汚さない。CI 流用 |

## リポジトリ構成

```
roshanavi/
  docker/Dockerfile            # ros:${ROS_DISTRO}-ros-base + fastapi/uvicorn/pytest/demo_nodes_py/rosbag2/ffmpeg/audio_common_msgs
                               # (C++ の計測ノードのビルドに要る ament_cmake / rosidl / rclcpp / gtest は ros-base に含まれる)
  docker-compose.yml           # lab (サーバー, :6871) / demo (外部ノードの例) / test / e2e
  examples/demo_project/       # デモ用プロジェクト (lab が初回に /data/roshanavi.yaml へコピー, docs/design/launcher.md)
  examples/busy_demo/          # MultiThreadedExecutor の空回りの再現 (executor_busy_demo × 3 構成, docs/design/nodes.md)
  examples/perception_demo/    # 認識パイプラインのデモ (動画 → image_filter → blob_detector、音声 → audio_level, docs/design/launcher.md)
  docs/                        # 設計・計画・プロジェクト文書 (docs/README.md が索引)
  ros2_ws/src/roshanavi_msgs/  # ament_cmake: 計測ノードとの内部 msg (ProbeConfig / ProbeStats ほか, docs/design/measurement.md)
  ros2_ws/src/roshanavi_probe/ # ament_cmake (C++17, rclcpp): 計測ノード (docs/design/measurement.md)
  ros2_ws/src/roshanavi_test_nodes/ # ament_cmake: テスト・ベンチマーク用の C++ ノード (rate_talker / slow_listener, docs/design/measurement.md)
  ros2_ws/src/roshanavi_examples_msgs/ # ament_cmake: 中継パイプラインの公開メッセージ (Payload / SinkStats, docs/design/nodes.md)
  ros2_ws/src/roshanavi_examples/   # ament_cmake + ament_cmake_python: 同梱サンプルノード (docs/design/nodes.md)
                               # src/ (C++: image_filter / blob_detector / image_ops)、roshanavi_examples/ (Python:
                               # audio_level / state_machine)、launch/ (ノードごと)、test/test_image_ops.cpp (gtest)
    include/roshanavi_probe/   # stats.hpp (純粋な統計, ROS 非依存) / publisher_directory.hpp (gid → ノード名の対応表, 純粋) / probe_node.hpp
    src/                       # stats.cpp / stats_msg.cpp (msg への変換) / probe_node.cpp / main.cpp
    test/test_stats.cpp        # gtest (統計の計算, 元の実装 reference_stats.hpp との照合)
  ros2_ws/src/roshanavi/       # ament_python パッケージ
    roshanavi/
      ros_runtime.py   # rclpy ノード + MultiThreadedExecutor を専用スレッドで回す。スレッド安全な facade
      graph.py         # グラフスナップショット
      qos_compat.py    # pub × sub の QoS 互換判定 (純関数)
      diagnostics.py   # 初心者向け診断 (純関数)
      traffic.py       # Python の計測 (計測ノードが無いときの代替): 全トピック raw 購読 + 統計
      traffic_select.py # 計測するトピックの選択 (除外・重い型の opt-in・トピックごとの切替。両方の経路で共有)
      traffic_backend.py # 計測の経路の選択 (C++ 計測ノード / Python) と切り替え (docs/design/measurement.md)
      probe_traffic.py # 計測ノードへの設定の送信と統計の受信 (TrafficMonitor と同じ形のエントリ)
      probe_process.py # 計測ノードの子プロセス管理 (起動・再起動・停止)
      tracing/         # 詳細計測モード (docs/design/measurement.md): config / lttng / reader / model / worker / service / merge
      server_tracing.py # /api/tracing
      msgutil.py       # 型解決 / テンプレ生成 / dict⇄msg / 表示用切り詰め
      expr.py          # AST ホワイトリスト式評価器 (eval 禁止)。expr_base.py (エラー・上限) / expr_funcs.py (関数)
      msg_view.py      # 変換ノードの式から読む、受信メッセージの読み取り専用ビュー (docs/design/input-and-media.md)
      transform/       # 変換ノード (docs/design/nodes.md): compute (式) / pipeline (間引き・遅延・結合) / runner (ROS) / preview
      transform_node.py # エントリ: `ros2 run roshanavi transform --config <yaml>`
      server_transforms.py # 変換ノード・試算・プロジェクトの切り替えの REST
      function/        # 関数・クラスノード (docs/design/nodes.md): core / class_core (ノードの中) / loader (import・ホットリロード) /
                       #   scopes・installed・modules・signatures (置き場所 A/B/C と静的な一覧) / code_report (見つからない理由) /
                       #   scaffold (ひな形) / dependencies・node_env・python_env (依存と Python) / codegen (docs/design/user-code.md)
      function_node.py # エントリ: `ros2 run roshanavi function --config <yaml>` (関数ノード・クラスノード)
      server_functions.py # 関数・クラスノード、コードの場所・ひな形・依存の案内の REST
      sample_media.py  # パーセプションデモ用のサンプル動画・音声を ffmpeg で生成 (初回のみ)
      heavy_types.py   # 大きい型 (画像・点群) の一覧
      injector.py      # 注入ジョブ管理
      echo.py          # オンデマンド購読 → 最新メッセージ
      rates.py         # 地図のエッジ用の送信元ごとの Hz (純関数, docs/design/map-and-traffic.md)
      media/           # docs/design/input-and-media.md: adapters/ (型ごとの変換) / ffmpeg / sources / job / capture /
                       #   viewer / recorder / diskguard / camera_info / imaging / options / factory
      server_media.py  # メディア型の判定・ブラウザ入力・ビューア・録画の REST + WS
      launcher/        # docs/design/launcher.md: discovery / validate / command / process / target / manager /
                       #   build / env / schema / project / dummy_config / service / proc_record (#12) / trash (削除)
      launch_import/   # launch の分解取り込み (サンドボックスの子) と引き取り takeover / takeover_plan / skip
                       #   (docs/design/integration.md)。../launch/takeover_rest.launch.py が「残りの部分」
      server_takeover.py # 引き取り・残ったプロセス・削除と元に戻すの REST
      cleanup.py       # エントリ: `ros2 run roshanavi cleanup` (強制終了で残ったノードを止める)
      process_map.py   # ノード ⇄ プロセス対応づけ (再利用可能。リソース監視でも使う)
      resources/       # リソース監視 Lv1: 1 Hz のサンプラー、対応づけ、リーク判定、接続先、GPU (docs/design/resources.md)
      dummy_node.py    # エントリ: `ros2 run roshanavi dummy --config <yaml>` (恒久ダミーノード)
      scenario/        # docs/design/scenarios.md: schema / fields (where) / checks (判定) / buffers (事前購読) /
                       #   runner / procs (setup・起動設定) / hints / result / junit / cli / api / store / service / recorder
      server_scenarios.py # シナリオ・記録モードの REST + /ws/scenarios
      server_resources.py # リソース監視の GET + /ws/resources
      server.py        # FastAPI アプリ (REST + WS)
      server_launcher.py # Launcher / プロジェクト / ビルド / ダミーの REST + /ws/logs
      params.py        # ノードのパラメータサービス (list/describe/get/set) のクライアント (docs/design/launcher.md)
      interfaces.py    # 型の定義 (`ros2 interface show` 相当, docs/design/launcher.md)
      server_nodes.py  # パラメータ・型の定義の REST
      api_errors.py    # 汎用の API エラーと `?window=` の検証
      main.py          # エントリ: `ros2 run roshanavi server`
      static/          # web のビルド成果物 (git 管理外、ビルドで生成)
    test/              # pytest (unit + rclpy 統合)
  web/                 # Vite + React (docs/design/ui.md)。e2e/ は Playwright
  examples/scenarios/  # サンプルシナリオ (examples/launch_pytest/ は launch_pytest から使う例)
```

## 部品のつながり
roshanavi は次のプロセスの組み合わせで動く。詳細は各リンク先を参照。

- **サーバー** (`ros2 run roshanavi server`、FastAPI + uvicorn): REST と WebSocket を提供し ([api.md#server API](../design/api.md#server-api))、web のビルド成果物も静的ファイルとして配信する ([ui.md#実装メモ (P2)](../design/ui.md#実装メモ-p2))。中では rclpy のノード `roshanavi` を専用スレッドの `MultiThreadedExecutor` で回し ([map-and-traffic.md#ros_runtime](../design/map-and-traffic.md#ros_runtime))、グラフ ([map-and-traffic.md#graph](../design/map-and-traffic.md#graph))・トラフィック ([map-and-traffic.md#traffic](../design/map-and-traffic.md#traffic))・注入 ([input-and-media.md#injector](../design/input-and-media.md#injector))・エコー ([input-and-media.md#echo](../design/input-and-media.md#echo)) を受け持つ。既定は `127.0.0.1` に bind し、Host / Origin / Content-Type を middleware で検査する ([api.md#ローカル Web からの攻撃対策](../design/api.md#ローカル-web-からの攻撃対策))。
- **計測ノード** (`roshanavi_probe`、C++): サーバーが子プロセスとして起動・再起動する。`/roshanavi/_probe/config` で受けた設定どおりに購読して統計を計算し、`/roshanavi/_probe/stats` に 1 Hz で返す。ビルドされていないときはサーバー内の Python の計測に切り替わる ([measurement.md#C++ 計測ノード](../design/measurement.md#c-計測ノード-roshanavi_probe-p46))。
- **トレースの解析プロセス** (`tracing/worker.py`): 詳細計測モード用に、サーバーとは別のプロセスで LTTng の記録を読んで集計し、標準入出力の JSON 行でサーバーに渡す ([measurement.md#詳細計測モード](../design/measurement.md#詳細計測モード-トレース計測-p47))。
- **子ノード** (入力ノード・変換ノード・関数ノード・クラスノード): それぞれ独立した ROS ノード (`ros2 run roshanavi dummy | transform | function --config <yaml>`。クラスノードは `function` の設定に `class:` を書く) として動く。Launcher の起動リストで他のノードと同じ形に管理され ([launcher.md#Launcher](../design/launcher.md#launcher-p3))、プロジェクトファイルに保存される ([launcher.md#プロジェクトファイル](../design/launcher.md#プロジェクトファイル-p3))。入力ノードは [nodes.md#恒久ダミーノード](../design/nodes.md#恒久ダミーノード-p3)、変換ノードは [nodes.md#変換ノード](../design/nodes.md#変換ノード-p5)、関数ノードは [nodes.md#関数ノード](../design/nodes.md#関数ノード-ふつうの関数をそのままノードにするp55) を参照。関数ノードの中の利用者のコードは、サーバーの中では実行も import もしない。
- **利用者のノードと依存ノード**: Launcher が `ros2 run` / `ros2 launch` で起動し、ログ・ビルド・再起動を扱う ([launcher.md#Launcher](../design/launcher.md#launcher-p3))。launch ファイルの分解取り込みの評価も別プロセスで行う ([launcher.md#launch の分解取り込み](../design/launcher.md#launch-の分解取り込み-p45b))。
- **外部コマンド**: ffmpeg (メディアのデコード、[input-and-media.md#メディア](../design/input-and-media.md#メディア-アダプタファイルソースブラウザ入力ビューア-p4))、`ros2 bag play` / `ros2 bag record` ([input-and-media.md#injector](../design/input-and-media.md#injector)、[input-and-media.md#録画](../design/input-and-media.md#録画-p4))、`colcon build` ([launcher.md#Launcher](../design/launcher.md#launcher-p3))。いずれも argv のリストで起動する。
- **web** (React + Vite): ブラウザから `/api` と `/ws/*` でサーバーと話す ([ui.md#フロントエンド](../design/ui.md#フロントエンド-タブ構成))。
- **実行環境**: 本番の形はネイティブ実行で、Docker (`docker compose` の `lab` / `demo` / `test` / `e2e`) は開発・CI・デモ用 ([vision.md#主要ユーザー体験](vision.md#主要ユーザー体験-ノード単体開発者の-1-日))。
