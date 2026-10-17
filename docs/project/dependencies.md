# roshanavi — 依存関係

対象: ROS 2 Jazzy / Ubuntu 24.04。最終確認: 2026-10-17。

方針 ([distribution.md の パッケージ構成](distribution.md#3-パッケージ構成-予定)):
- 実行時の依存は、**すべて rosdep キーで解決できるもの** に限る。pip での追加インストールは要求しない。
- 依存を追加したら、`package.xml` とこの文書を同時に更新する。Docker イメージにだけ入っていて `package.xml` に無い、という状態を作らない (ソースからインストールした場合に壊れるため)。
- 任意の依存が無い場合は、該当機能だけを無効にし、UI で導入方法を案内する。

## 1. 実行時の依存 (必須)

### ROS パッケージ
| パッケージ | 用途 |
|---|---|
| `rclpy` | ROS との通信全般 |
| `rosidl_runtime_py` | メッセージ型の動的な解決、dict ⇄ msg の変換 |
| `std_msgs`, `sensor_msgs` | メディア注入 (画像・音声の配列型)、テンプレート |
| `launch_ros` | 恒久ダミーノードの launch ファイル書き出し |
| `ros2run`, `ros2launch` | ランチャー (`ros2 run` / `ros2 launch` の実行) |
| `rcl_interfaces` | パラメータの表示・変更 (パラメータサービスのクライアント) |
| `lifecycle_msgs` | lifecycle ノードの状態取得と状態遷移 |
| `rosidl_default_runtime` | `roshanavi_msgs` の実行時サポート |
| `launch_xml`, `launch_yaml` | XML / YAML 形式の launch ファイルの取り込み (分解) |
| `ros2bag` (+ `rosbag2_storage_default_plugins`) | bag 再生、録画 (mcap 形式) |

### C++ 計測ノード (`roshanavi_probe`) と内部メッセージ (`roshanavi_msgs`) のビルド
| パッケージ | 用途 |
|---|---|
| `ament_cmake`, `rosidl_default_generators` | ビルド、内部メッセージの生成 |
| `rclcpp`, `rmw`, `builtin_interfaces`, `std_msgs` | 計測ノード本体 |
| `ament_cmake_gtest` (テストのみ) | C++ の単体テスト |

いずれも `ros:jazzy-ros-base` と ROS 2 の標準インストールに含まれる。C++ コンパイラ (build-essential) が必要。

### システム・Python (apt / rosdep キー)
| rosdep キー | 用途 | ライセンス |
|---|---|---|
| `python3-fastapi` | Web API サーバー | MIT |
| `python3-uvicorn` | ASGI サーバー | BSD-3-Clause |
| `python3-websockets` | WebSocket (画面のリアルタイム更新) | BSD-3-Clause |
| `python3-pydantic` | API 入力とプロジェクトファイルの検証 (Ubuntu 24.04 の 1.10 系) | MIT |
| `python3-yaml` | プロジェクトファイル、シナリオ、テンプレート | MIT |
| `python3-psutil` | プロセス管理、ノードとプロセスの対応づけ、(P8) リソース監視 | BSD-3-Clause |
| `python3-numpy` | 音声の PCM 変換 | BSD-3-Clause |
| `python3-pil` (Pillow) | メモリ上の JPEG 変換 (ブラウザのカメラ、画像ビューア) | MIT-CMU (HPND) |
| `ffmpeg` | 動画・音声ファイルのデコード (別プロセスとして起動) | LGPL-2.1+ / GPL-2+ (Ubuntu のビルド) |

ffmpeg は **別プロセスとして起動するだけで、ライブラリとしてリンクしない**。そのため、roshanavi のライセンスに影響しない。

## 2. 実行時の依存 (任意)
| 依存 | 無い場合 | 導入 |
|---|---|---|
| `audio_common_msgs` | 音声の注入先として AudioData 系の型が選べなくなる (std_msgs の配列型は使える) | `sudo apt install ros-jazzy-audio-common-msgs` |
| `colcon` (`python3-colcon-common-extensions`) | ビルドボタンが無効になる | `sudo apt install python3-colcon-common-extensions` |
| `pynvml` (P8, 予定) | GPU の監視が無効になる | rosdep キーを実装時に確認する |
| `lttng-tools`, `liblttng-ust1t64` (`ros-jazzy-tracetools` の依存で通常は導入済み), `python3-bt2` | 詳細計測モード (トレース) が無効になる。トグルに導入方法を表示する | `sudo apt install lttng-tools python3-bt2` |

## 3. 開発・テスト用 (利用者には不要)

### Python テスト
| rosdep キー | 用途 |
|---|---|
| `python3-pytest` | テスト |
| `python3-httpx` | FastAPI の TestClient |
| `launch_pytest` (`ros-jazzy-launch-pytest`) | シナリオを launch_pytest から使う例 (`examples/launch_pytest/`) とそのテスト。`package.xml` は `test_depend` |
| `ros-jazzy-demo-nodes-cpp`, `ros-jazzy-demo-nodes-py`, `ros-jazzy-example-interfaces` | テストとデモの相手役ノード |
| `ros-jazzy-lifecycle` | lifecycle ノードのデモとテスト (`lifecycle_talker`) |
| `roshanavi_test_nodes` (同梱の ament パッケージ。rclcpp, std_msgs, sensor_msgs) | トレース計測のテスト用ノード (遅いコールバックなど) |
| `ros-jazzy-rmw-cyclonedds-cpp` (任意、未導入) | Cyclone DDS での計測の自動テスト (現在は手動確認のみ) |

### Web UI (ビルド時のみ。配布物にはビルド済みの静的ファイルを同梱し、利用者に npm を要求しない)
バージョンは `web/package.json` で固定。ホストの npm 設定により、公開から約 2 週間未満のバージョンは使わない。

| パッケージ | バージョン | 用途 | ライセンス |
|---|---|---|---|
| react, react-dom | 19.3.0 | UI | MIT |
| cytoscape | 3.34.3 | 通信マップの描画 | MIT |
| cytoscape-dagre | 4.0.1 | 左→右のレイアウト | MIT |
| uplot | 1.6.32 | スパークライン | MIT |
| js-yaml | 5.4.2 | 注入画面の YAML 編集 | MIT |
| vite, @vitejs/plugin-react | 8.3.2, 6.1.1 | ビルド (dev) | MIT |
| typescript | 5.9.3 | 型検査 (dev) | Apache-2.0 |
| vitest | 5.0.3 | 単体テスト (dev) | MIT |
| @playwright/test | 1.63.0 | E2E (dev) | Apache-2.0 |

Node.js: 開発は v24.14 (ホスト)。jsdom は Node 24.15 以上が必要なため未使用 (コンポーネントテストは対象外)。

## 4. Docker イメージ

全 ROS サービスに `shm_size: 512m` を設定する (LTTng のリングバッファが /dev/shm に置かれ、既定の 64 MB では足りずに何も記録されないため)。

| イメージ | 用途 |
|---|---|
| `ros:jazzy-ros-base` | lab / demo / test のベース |
| `node:24.14.0-bookworm-slim` | Web UI のビルドステージ |
| `mcr.microsoft.com/playwright:v1.63.0-noble` | E2E テスト |

## 5. roshanavi 自身のライセンス
- **MIT** (リポジトリ直下の `LICENSE`)。`package.xml` の `<license>` も MIT にそろえる。
- 依存はすべて MIT / BSD / Apache-2.0 / HPND、または別プロセスとして起動するもの (ffmpeg、lttng-tools) であり、MIT での配布と両立する。
