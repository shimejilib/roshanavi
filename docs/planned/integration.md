# 既存プロジェクトへの組み込み (設計・一部未実装)

利用者が自分の ROS 2 プロジェクトに roshanavi を入れて使うための設計。配布形態の全体は [distribution.md](../project/distribution.md)、別マシンからのアクセスは [remote-access.md](remote-access.md) を参照。

## 0. 主な組み込み方: launch を引き取る (実装済み)

既存の launch ファイルを roshanavi が引き取って起動する形を主にする (2026-10-18 決定)。実装済みの仕様は [design/integration.md](../design/integration.md)、使い方は [guide/takeover.md](../guide/takeover.md)。強制終了で残ったプロセスの片付け (#12) は [design/launcher.md#子プロセスの後始末](../design/launcher.md#子プロセスの後始末-12)。

## 1. ネイティブ (利用者のワークスペースに入れる)

### インストール
```
cd ~/ros2_ws/src && git clone https://github.com/shimejilib/roshanavi.git
cd ~/ros2_ws && rosdep install --from-paths src --ignore-src -y && colcon build
```
- **npm を要求しない**: Web 画面はビルド済みの静的ファイルを同梱する。リリース時に生成したものをリリースアーカイブ (および配布用ブランチ) に含める。開発者向けには、npm があれば `colcon build` 時に画面もビルドし、無ければ同梱物を使う。どちらも無い場合は、画面なしで API だけ起動し、取得方法を平易に案内する。
- 依存はすべて rosdep キーで解決する ([dependencies.md](../project/dependencies.md))。

### 起動
```
source ~/ros2_ws/install/setup.bash
ros2 run roshanavi app
```
- ワークスペースを自動で認識する (カレントディレクトリ、または `AMENT_PREFIX_PATH` / `COLCON_PREFIX_PATH` から推定。`--workspace` で明示も可)。
- プロジェクトファイルは `<ws>/roshanavi.yaml`、データは `<ws>/.roshanavi/` (録画・シナリオ結果・ログ)。`.roshanavi/` は `.gitignore` に入れるよう案内する (シナリオ `<ws>/scenarios/` はコミット推奨)。
- ブラウザを自動で開く (`--no-browser` で抑止)。
- `ros2 launch roshanavi roshanavi.launch.py` からも起動でき、既存の bringup に組み込める。

### 起動時チェック (平易に案内)
| 検出 | 案内 |
|---|---|
| ワークスペースが source されていない / 未ビルドのパッケージがある | source のコマンドを表示 |
| ROS_DOMAIN_ID・RMW がノードと異なる可能性 | 設定値を表示し、地図に何も出ないときの確認手順を案内 |
| ポート 6871 が使用中 | `--port` を案内 |
| `ROS_LOCALHOST_ONLY` / `ROS_AUTOMATIC_DISCOVERY_RANGE` の設定 | 他 PC のノードが見えない理由として案内 |
| 任意の依存が無い (lttng、audio_common_msgs、colcon、pynvml) | 該当機能が無効であることと導入コマンド |

### テストへの組み込み
- CLI: `ros2 run roshanavi scenario run scenarios/ --junit results.xml` を CI に組み込む例。
- launch_pytest: `roshanavi.scenario.run_scenario()` を既存のテストから呼ぶ例 (`examples/launch_pytest/`)。

## 2. 既存のシステムが Docker で動いている場合

| 方法 | 内容 | できること | 安全性 |
|---|---|---|---|
| **A. サイドカー (既定)** | roshanavi を別コンテナで動かし、同じ ROS ネットワークに参加させる | ROS の通信で済む機能すべて (地図、トラフィック、エコー、入力・変換・関数ノード、シナリオ、録画) | ◎ 既存のコンテナに手を入れない |
| **B. 既存コンテナに入れる** | 利用者のイメージ / devcontainer に roshanavi を追加インストールする | 全機能 (ランチャー、ビルド、リソース監視、詳細計測を含む) | ◎ ネイティブと同じ |
| **C. コンテナ操作 (任意)** | 制限付きの Docker API 中継を経由して、許可したコンテナを起動・停止する | コンテナ単位の起動・停止・ログ | △ 下記の制限が前提 |

### A. サイドカー
- compose の設定例を用意する: `network_mode: host`、`ipc: host` (DDS の発見と共有メモリ通信のため)、同じ `ROS_DOMAIN_ID` / `RMW_IMPLEMENTATION`。
- **独自のメッセージ型**: roshanavi 側でも型を読めないと中身を表示できない。利用者のイメージをベースに roshanavi を重ねる Dockerfile の例 (`FROM <利用者のイメージ>` → roshanavi をビルド) を用意する。
- 起動時チェックで「ホストと別ネットワークのため、ノードが見えない可能性」を検出して案内する (Docker のブリッジネットワーク内で動いているか、発見できたノード数がゼロか)。
- **コンテナ単位のリソース監視**: ホストの cgroup 情報 (`/sys/fs/cgroup`) を読み取り専用でマウントし、コンテナごとの CPU・メモリを出す。Docker ソケットは使わない。
- 詳細計測 (トレース) はコンテナをまたげないため、A では未対応と表示する。

### B. 既存コンテナに入れる
- Dockerfile への追記例と、devcontainer (VS Code) の設定例を用意する。ポート 6871 の転送を含める。

### C. コンテナ操作 (DooD の制限版)
- **Docker ソケット (`/var/run/docker.sock`) を roshanavi に直接渡さない。** ソケットを渡すことはホストの root 権限を渡すのとほぼ同じであり、読み取り専用のマウントでも API 経由で任意の操作ができる。
- 代わりに、許可した API だけを通す中継 (docker-socket-proxy など) を経由する。許可するのは「コンテナの一覧・起動・停止・再起動・ログ」のみ。「exec (コンテナ内でのコマンド実行)」「コンテナ・イメージの作成」「ボリューム」などは通さない。
- 操作できるコンテナを許可リスト (ラベルまたは名前) で限定する。
- 既定は無効。`--remote` (別マシンからのアクセス) 中は、明示的に許可しない限り無効のままにする。
- 地図上では、コンテナの中のノードを「コンテナ単位で操作できるノード」として表示し、停止時は同じコンテナの全ノードが止まることを確認ダイアログで示す。

## 3. 検証
- まっさらな `ros:jazzy` / `ros:lyrical` コンテナで、架空の既存プロジェクト (独自 msg を含むワークスペース) に roshanavi を組み込み、npm なしで画面が出ること、独自型の中身が見えること、ランチャーで利用者のノードを起動できることを確かめる E2E。
- サイドカー構成 (A) の compose で、別コンテナのノードが地図に現れ、シナリオが通ることを確かめる E2E。
