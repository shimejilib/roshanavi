# roshanavi — 依存関係

対象: ROS 2 **Jazzy** (Ubuntu 24.04) と **Lyrical** (Ubuntu 26.04) が正式対応、Kilted (Ubuntu 24.04) は動作確認のみ ([distribution.md の 対応ディストロ](distribution.md#0-対応ディストロ))。最終確認: 2026-10-18。

以下のパッケージ名の `<distro>` は `jazzy` / `lyrical` / `kilted` (例: `ros-<distro>-vision-msgs`)。

方針 ([distribution.md の パッケージ構成](distribution.md#3-パッケージ構成-予定)):
- 実行時の依存は、**すべて rosdep キーで解決できるもの** に限る。pip での追加インストールは要求しない。
- 依存を追加したら、`package.xml` とこの文書を同時に更新する。Docker イメージにだけ入っていて `package.xml` に無い、という状態を作らない (ソースからインストールした場合に壊れるため)。
- 任意の依存が無い場合は、該当機能だけを無効にし、UI で導入方法を案内する。

## 0. ディストロごとの主な版

Docker イメージ (`roshanavi:dev-<distro>`) で 2026-10-18 に確認した版。どれも apt (rosdep キー) から入るもので、pip は使わない。

| | Jazzy | Lyrical | Kilted (確認のみ) |
|---|---|---|---|
| Ubuntu / Python | 24.04 / 3.12.3 | 26.04 / 3.14.4 (GIL あり) | 24.04 / 3.12.3 |
| rclpy / rclcpp | 7.1.12 / 28.1.22 | 10.0.11 / 32.0.3 | 9.1.7 / 29.5.11 |
| launch / rosbag2_py | 3.4.11 / 0.26.11 | 3.9.8 / 0.33.4 | 3.8.8 / 0.32.0 |
| rmw_fastrtps_cpp / tracetools | 8.4.4 / 8.2.6 | 9.4.10 / 8.10.2 | 9.3.5 / 8.6.0 |
| pydantic / FastAPI / Starlette / uvicorn | 1.10.14 / 0.101.0 / 0.31.1 / 0.27.1 | 2.12.5 / 0.118.0 / 0.50.0 / 0.38.0 | Jazzy と同じ |
| httpx / websockets | 0.26.0 / 10.4 | 0.28.1 / 15.0.1 | Jazzy と同じ |
| numpy / Pillow / psutil / PyYAML | 1.26.4 / 10.2.0 / 5.9.8 / 6.0.1 | 2.3.5 / 12.1.1 / 7.1.0 / 6.0.3 | Jazzy と同じ |
| python3-bt2 (babeltrace2) / lttng-tools | 2.0.5 / 2.13.11 | 2.1.2 / 2.14.1 | Jazzy と同じ |
| ffmpeg | 6.1.1 | 8.0.1 | Jazzy と同じ |

ディストロで違いが出た所と対処は [testing.md の R. ディストロ対応](testing.md#r-ディストロ対応-36-37) にまとめた。

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

いずれも `ros:<distro>-ros-base` と ROS 2 の標準インストールに含まれる。C++ コンパイラ (build-essential) が必要。

### 中継パイプラインのサンプル (`roshanavi_examples`、`roshanavi_examples_msgs`、#51)
| パッケージ | 用途 |
|---|---|
| `rosidl_default_generators`, `std_msgs` | 公開メッセージ `Payload` / `SinkStats` の生成 (`roshanavi_examples_msgs`) |
| `rclcpp_components` | source / relay / sink を composable node としても実行ファイルとしても動かす。launch から `component_container` / `component_container_mt` を使う (`exec_depend`) |
| `launch_ros` | `pipeline.launch.py` が `Node` / `ComposableNodeContainer` を作る (既存の依存) |

どれも `ros:<distro>-ros-base` に含まれる (Docker に足したものは無い)。生成器 (`scripts/gen_pipeline.py`) は標準ライブラリだけの Python。

### システム・Python (apt / rosdep キー)
| rosdep キー | 用途 | ライセンス |
|---|---|---|
| `python3-fastapi` | Web API サーバー | MIT |
| `python3-uvicorn` | ASGI サーバー | BSD-3-Clause |
| `python3-websockets` | WebSocket (画面のリアルタイム更新) | BSD-3-Clause |
| `python3-pydantic` | API 入力とプロジェクトファイルの検証。Ubuntu 24.04 は 1.10 系、26.04 は 2 系で、両方で動く (違いは `roshanavi/pydantic_compat.py` が吸収し、エラーの文面も 1.10 系にそろえる) | MIT |
| `python3-yaml` | プロジェクトファイル、シナリオ、テンプレート | MIT |
| `python3-psutil` | プロセス管理、ノードとプロセスの対応づけ、リソース監視 (PC 全体の CPU・メモリ・ディスク・NIC。プロセスごとの値は `/proc` を直接読む) | BSD-3-Clause |
| `python3-numpy` | 音声の PCM 変換 | BSD-3-Clause |
| `python3-pil` (Pillow) | メモリ上の JPEG 変換 (ブラウザのカメラ、画像ビューア) | MIT-CMU (HPND) |
| `ffmpeg` | 動画・音声ファイルのデコード (別プロセスとして起動) | LGPL-2.1+ / GPL-2+ (Ubuntu のビルド) |

ffmpeg は **別プロセスとして起動するだけで、ライブラリとしてリンクしない**。そのため、roshanavi のライセンスに影響しない。

## 2. 実行時の依存 (任意)
| 依存 | 無い場合 | 導入 |
|---|---|---|
| `audio_common_msgs` | 音声の注入先として AudioData 系の型が選べなくなる (std_msgs の配列型は使える) | `sudo apt install ros-<distro>-audio-common-msgs` |
| `colcon` (`python3-colcon-common-extensions`) | ビルドボタンが無効になる | `sudo apt install python3-colcon-common-extensions` |
| `python3-pynvml` (pynvml、BSD-3-Clause。rosdep キー `python3-pynvml` は debian / ubuntu にあり、Ubuntu 24.04 は 12.535.133) | GPU の監視が無効になる (リソースタブに理由と導入方法を出す。他の機能は動く)。NVIDIA のドライバ (NVML) も必要。任意のため `package.xml` と Docker イメージには入れていない (Docker では `--gpus` も要る) | `sudo apt install python3-pynvml` |
| `python3-rosdep` (rosdep、BSD-3-Clause。ROS のイメージには通常入っている) とそのデータベース (`rosdep update`) | 関数・クラスノードで足りないライブラリの rosdep キーを確かめられない。候補のキー (未確認) と venv の手順を出す ([user-code.md#5](../design/user-code.md#5-依存ライブラリ))。roshanavi は `rosdep resolve` を実行するだけで、install はしない | `sudo apt install python3-rosdep && sudo rosdep init && rosdep update` |
| `python3-packaging` (Apache-2.0 / BSD。Ubuntu では pip / setuptools と一緒に入っていることが多い) | requirements.txt の照合で、版の条件と環境マーカーを確かめず、入っているかどうかだけを確かめる | `sudo apt install python3-packaging` |
| `lttng-tools`, `liblttng-ust1t64` (`ros-<distro>-tracetools` の依存で通常は導入済み。26.04 では `liblttng-ust1t64` 2.14), `python3-bt2` | 詳細計測モード (トレース) が無効になる。トグルに導入方法を表示する | `sudo apt install lttng-tools python3-bt2` |

## 3. 開発・テスト用 (利用者には不要)

### Python テスト
| rosdep キー | 用途 |
|---|---|
| `python3-pytest` | テスト |
| `python3-httpx` | FastAPI の TestClient |
| `launch_pytest` (`ros-<distro>-launch-pytest`) | シナリオを launch_pytest から使う例 (`examples/launch_pytest/`) とそのテスト。`package.xml` は `test_depend` |
| `ros-<distro>-demo-nodes-cpp`, `ros-<distro>-demo-nodes-py`, `ros-<distro>-example-interfaces` | テストとデモの相手役ノード |
| `ros-<distro>-lifecycle` | lifecycle ノードのデモとテスト (`lifecycle_talker`) |
| `roshanavi_test_nodes` (同梱の ament パッケージ。rclcpp, std_msgs, sensor_msgs) | トレース計測のテスト用ノード (遅いコールバックなど) |
| `git` (ros のベースイメージに同梱) | 関数・クラスノードのテストで、git のサブモジュール (同期済み・未同期) の fixture を作る (roshanavi 自身は git を実行しない) |
| C コンパイラ (`cc`) と Python のヘッダ (ros のベースイメージに同梱) | 関数・クラスノードのテストで、拡張モジュール (.so) の fixture を作る。無ければそのテストは skip |
| `python3 -m venv` (標準ライブラリ。テストは `--without-pip` なので `python3-venv` は不要) | 関数ノードを venv の Python で動かすテスト |
| `ros-<distro>-rmw-cyclonedds-cpp` (任意、未導入) | Cyclone DDS での計測の自動テスト (現在は手動確認のみ) |

### Web UI (ビルド時のみ。配布物にはビルド済みの静的ファイルを同梱し、利用者に npm を要求しない)
バージョンは `web/package.json` で固定。ホストの npm 設定により、公開から約 2 週間未満のバージョンは使わない。

| パッケージ | バージョン | 用途 | ライセンス |
|---|---|---|---|
| react, react-dom | 19.3.0 | UI | MIT |
| cytoscape | 3.34.3 | 通信マップの描画 | MIT |
| cytoscape-dagre | 4.0.1 | 左→右のレイアウト | MIT |
| uplot | 1.6.32 | スパークライン | MIT |
| js-yaml | 5.4.2 | 注入画面の YAML 編集 | MIT |
| driver.js | 1.8.0 | アプリ内チュートリアルの強調表示と吹き出し ([ui.md#実装メモ (アプリ内チュートリアル)](../design/ui.md#実装メモ-アプリ内チュートリアル)) | MIT |
| vite, @vitejs/plugin-react | 8.3.2, 6.1.1 | ビルド (dev) | MIT |
| typescript | 5.9.3 | 型検査 (dev) | Apache-2.0 |
| vitest | 5.0.3 | 単体テスト (dev) | MIT |
| @playwright/test | 1.63.0 | E2E (dev) | Apache-2.0 |

**チュートリアルのライブラリ選定 (#41)**: roshanavi は MIT なので、MIT / Apache-2.0 など互換のライセンスだけを候補にした (`npm view <pkg> license` で確認、2026-10-17)。

| 候補 | ライセンス | 判断 |
|---|---|---|
| **driver.js** | MIT | **採用**。依存パッケージなし、素の JS (React に依存しない)、配布物は約 83 KB (gzip で JS 約 7 KB + CSS 約 1 KB)。画面の一部を切り抜いて吹き出しを出すだけで、「次へ」の判定は持たない。進行 (いつ次へ進むか) を自前のエンジンで決める作りに合う |
| react-joyride 3.2.0 | MIT | 見送り。10 個の依存パッケージ (配布物 約 720 KB) を連れてくる。「操作したら次へ」を `data-tour` と状態の購読で書く方式では、ライブラリ側の進行管理が邪魔になる |
| Shepherd.js 15.3.0 | **AGPL-3.0** | 使えない (確認した 14.5.1 も AGPL-3.0。MIT のプロジェクトに取り込めない) |
| Intro.js | AGPL-3.0 | 使えない (Issue #41 で禁止) |

固定したバージョンは **1.8.0** (2026-07-17 公開)。最新の 1.10.1 (2026-10-15) と 1.9.0 (2026-10-03) は公開から約 2 週間未満のため使わない。ビルドへの影響 (実測): JS gzip 360.1 → 377.6 KB (driver.js 約 7 KB + チュートリアルの自前コード・文言 約 10 KB)、CSS gzip 8.1 → 9.4 KB。

**地図の上で線を引く部品の選定 (#47)**: 依存を増やさず自前で実装した ([wiring.md#3](../design/wiring.md#3-実装))。

| 候補 | ライセンス | 判断 |
|---|---|---|
| cytoscape-edgehandles 4.0.1 | MIT | 見送り。最後の公開が 2021-07-28 で、その後の更新がない (`npm view cytoscape-edgehandles time`、2026-10-18 に確認)。lodash.memoize / lodash.throttle に依存。線を「ノードとノード」の間に引くだけで、ノードの中のつなぎ口・キーボード操作・読み上げ・理由つきの拒否・「空いているところで新しいチャンネル」を持たない。必要なのはつなぎ口の当たり判定と 1 本の仮の線だけで、つなぎ口はキーボードと読み上げのために DOM のボタンにする必要があった |
| **自前 (`web/src/wiring/`)** | — | **採用**。つなぎ口は cytoscape の上に重ねたボタン、仮の線は SVG、当たり判定は cytoscape の要素の矩形。約 400 行 + 純関数のロジック (vitest) |

Node.js: 開発は v24.14 (ホスト)。jsdom は Node 24.15 以上が必要なため未使用 (コンポーネントテストは対象外)。

## 4. Docker イメージ

全 ROS サービスに `shm_size: 512m` を設定する (LTTng のリングバッファが /dev/shm に置かれ、既定の 64 MB では足りずに何も記録されないため)。

| イメージ | 用途 |
|---|---|
| `ros:<distro>-ros-base` (既定 `ros:jazzy-ros-base`) | lab / demo / test のベース。`ROS_DISTRO` で切り替え、イメージ名は `roshanavi:dev-<distro>` |
| `node:24.14.0-bookworm-slim` | Web UI のビルドステージ |
| `mcr.microsoft.com/playwright:v1.63.0-noble` | E2E テスト |

## 5. roshanavi 自身のライセンス
- **MIT** (リポジトリ直下の `LICENSE`)。`package.xml` の `<license>` も MIT にそろえる。
- 依存はすべて MIT / BSD / Apache-2.0 / HPND、または別プロセスとして起動するもの (ffmpeg、lttng-tools) であり、MIT での配布と両立する。
