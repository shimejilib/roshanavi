# 自分のワークスペースに入れる

ROS 2 をパソコンに入れて使っている人が、自分のワークスペース (`src/` とビルド結果 `install/` の入ったフォルダ) に roshanavi を入れて、同じ環境で動かす方法です。Docker で動かしているプロジェクトに入れたいときは [Docker で動いている既存のプロジェクトに入れる](docker-integration.md) を見てください。ROS を入れていなくて、まず試したいだけなら [はじめての起動と画面の見方](getting-started.md) の Docker が早いです。

**いまの状態を正直に書きます。** 入れ方は「ソースを取ってきてビルドする」形だけで、手順が整っている途中です。特に **Web 画面 (ブラウザの画面) のビルド済みファイルがまだ配られていない**ため、いまは Node.js (npm) を使って自分で作る一手間があります。これは [#42](https://github.com/shimejilib/roshanavi/issues/42) で、ビルド済みの画面を同梱して**不要にする予定**です (そうなれば npm なしで入ります)。

## 対応している ROS 2

| ディストロ | 扱い |
|---|---|
| Jazzy Jalisco | 正式対応 (Ubuntu 24.04) |
| Lyrical Luth | 正式対応 (Ubuntu 26.04) |
| Kilted Kaiju | 動作確認のみ。継続的には確認していません |

Docker で使うときは、`ROS_DISTRO=lyrical docker compose ...` のようにバージョンを選べます。

## 手順 (いま)

### 1. ソースを取ってくる

```bash
cd ~/ros2_ws/src
git clone https://github.com/shimejilib/roshanavi.git
```

colcon は `src/` の下を奥まで探してパッケージを見つけます。取ってきたリポジトリの中の `ros2_ws/src/` にある 6 つのパッケージが見つかりますが、**使うのに必要なのは 3 つだけ**です (roshanavi 本体 `roshanavi`、計測ノード `roshanavi_probe`、内部用のメッセージ型 `roshanavi_msgs`)。残りはサンプル (`roshanavi_examples`、`roshanavi_examples_msgs`) とテスト用 (`roshanavi_test_nodes`) で、余計な依存が増えるので、以下の手順ではビルドしません。

### 2. 依存を入れる (rosdep)

```bash
cd ~/ros2_ws
rosdep install --ignore-src -y --from-paths src/roshanavi/ros2_ws/src/roshanavi src/roshanavi/ros2_ws/src/roshanavi_msgs src/roshanavi/ros2_ws/src/roshanavi_probe
```

サンプルも試したいときは、`--from-paths src` (全部) にします。

roshanavi が使う部品 (FastAPI、uvicorn、psutil、ffmpeg など) は、`package.xml` に ROS 標準の方法で書いてあるので、rosdep が入れます。pip で入れるものはありません。

### 3. Web 画面を作る (いまだけ必要)

画面は、ソースから作った成果物をパッケージに入れて配る作りです。ビルド済みのものはまだ配っていないので、**colcon でビルドする前に**、次を実行します。Node.js (npm) が必要です。

```bash
cd ~/ros2_ws/src/roshanavi/web
npm ci
npm run build
```

画面のファイルは、取ってきたリポジトリの中の `ros2_ws/src/roshanavi/roshanavi/static/` に書き出されます。次の colcon のビルドで、これがパッケージの一部として一緒にインストールされます。

別の場所で作った画面を使いたいときは、roshanavi の起動時に `--static-dir <フォルダ>` を付けるか、環境変数 `ROSHANAVI_STATIC_DIR` でフォルダ (中に `index.html` があるもの) を指します。Docker のイメージも、この方法で画面を渡しています。

画面が無いまま起動すると、画面は出ず、API だけが動きます (ブラウザで開くと、画面の代わりに API の情報 (JSON) が表示されます)。

### 4. ビルドして起動する

```bash
cd ~/ros2_ws
colcon build --packages-up-to roshanavi
source install/setup.bash
ros2 run roshanavi app
```

`--packages-up-to roshanavi` で、roshanavi と、それが必要とする 2 つのパッケージだけをビルドします。自分のパッケージも一緒にビルドするときは、`colcon build` (全部) でもかまいません (その場合はサンプルの依存も必要です)。

ブラウザで http://localhost:6871 を開きます (いまは、ブラウザが自動では開きません)。

- **必ず、自分のワークスペースを source した端末で起動します。** 自分のパッケージの独自のメッセージ型や、ランチャー、ビルドボタンが、同じ環境で動く必要があるためです。
- 自分のプロジェクトの launch ファイルを引き取って動かすなら `ros2 run roshanavi app --launch <パッケージ> <launch ファイル>` ([既存の launch ファイルごと動かす](takeover.md))。
- 設定の保存先は、`--project` (既定は `<ワークスペース>/roshanavi.yaml`。ワークスペースは `--workspace`、既定はいまのフォルダ)、録画や送るファイルは `--data-dir` (既定は `/data`。ネイティブでは自分で指定してください。例: `--data-dir ~/roshanavi_data`) です。
- ポートを変えるときは `--port`。別のマシンから見るときは [SSH のポート転送](remote-ssh.md) を使います。

## 任意の追加

入れなくても動きますが、入れると使える機能が増えます。

| 入れるもの | 使える機能 |
|---|---|
| `lttng-tools`、`python3-bt2` | 詳細計測モード ([測る](measure.md)) |
| `python3-colcon-common-extensions` | 画面のビルドボタン |
| `ros-<distro>-audio-common-msgs` | 音声の送り先の型の選択肢 |
| `python3-pynvml` | GPU の監視 |

## うまくいかないとき

| 症状 | 確かめること |
|---|---|
| ブラウザで何も出ない | 手順 3 の画面のビルドをしたか。`ros2_ws/src/roshanavi/roshanavi/static/index.html` があるか。無ければ `--static-dir` で指す |
| `ros2 run roshanavi app` が見つからない | ビルドしたワークスペースを `source install/setup.bash` したか |
| `rosdep` が「キーが見つからない」と言う | `rosdep update` を実行したか。ROS のバージョンが対応しているか |
| ビルドが遅い | 計測ノード (C++) のビルドが含まれます。初回は時間がかかります |
| 地図が空 | 見たいノードと `ROS_DOMAIN_ID` が同じか ([動いているシステムを見るだけ](observe.md)) |
| ブラウザで開くと拒否される | 別のマシンのブラウザから直接開いていませんか。roshanavi は安全のため `localhost` からだけ開けます ([SSH のポート転送](remote-ssh.md)) |

## 仕組みを知りたい人へ

- 配布とインストールの設計、ポートの選び方: [project/distribution.md](../project/distribution.md)
- 組み込みの計画 (ビルド済みの画面の同梱、起動時のチェック、`app` の自動設定など): [planned/integration.md](../planned/integration.md)
- 依存関係の一覧: [project/dependencies.md](../project/dependencies.md)
