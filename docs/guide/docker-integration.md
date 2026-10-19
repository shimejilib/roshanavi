# Docker で動いている既存のプロジェクトに入れる

いま Docker (docker compose) で動かしているプロジェクトに、roshanavi を**コンテナ 1 つ足す**だけで入れる方法です。プロジェクトのイメージの上に roshanavi を重ねるので、自分のノードも、自分で定義したメッセージ型も、そのまま使えます。元の起動方法 (roshanavi なし) も残せます。

この章の手順は、小さな実例で確かめたものです (亀のシミュレーター turtlesim を動かす `turtle_patrol` というプロジェクトで、roshanavi が launch ファイルを引き取り、ノードを 1 つずつ操作、関数・クラスノードの追加、シナリオの実行まで通しました)。**手順の一部は手作業が多く、[#42](https://github.com/shimejilib/roshanavi/issues/42) で簡単にする予定です。** 該当する所に「#42 で改善予定」と書いています。

先に、自分の目的に合うか確かめてください。

| こうしたい | 読む章 |
|---|---|
| 手を入れずに、横から見るだけ | [動いているシステムを見るだけ](observe.md) |
| Docker を使わず、自分のパソコンのワークスペースで動かす | [自分のワークスペースに入れる](install.md) |
| Docker のプロジェクトで、ノードの停止・再起動・ビルド・計測までしたい | この章 |

## 全体の形

```
プロジェクトのイメージ (例: myproj:dev)        ← いまのまま
        │ これを土台に重ねる
        ▼
roshanavi 入りのイメージ (例: myproj-roshanavi:dev)
        │ compose のサービス dev として動かす
        ▼
  ros2 run roshanavi app --launch <パッケージ> <launch ファイル>
```

- roshanavi は、プロジェクトのイメージの**上**に別の場所 (`/roshanavi_ws`) へ入れます。プロジェクトの `/ws` には触りません。
- launch ファイルは書き換えません。roshanavi がその中のノードを 1 つずつ起動するので、ノードごとに止める・再起動・ログ・計測ができます ([既存の launch ファイルごと動かす](takeover.md))。
- 元の起動方法は、compose の profile (`plain`) に残して切り替えます。

## 手順

### 1. roshanavi をサブモジュールとして入れる

```bash
cd <自分のプロジェクト>
git submodule add https://github.com/shimejilib/roshanavi.git third_party/roshanavi
git submodule update --init
```

プロジェクトの git に、roshanavi の特定の版が固定されます。他の人は `git submodule update --init` で同じ版が手に入ります。

### 2. roshanavi 入りのイメージを作る (Dockerfile)

`docker/roshanavi.Dockerfile` を作ります。段が 2 つあります。1 つ目は画面 (Web UI) を作るためだけの段で、2 つ目がプロジェクトのイメージに roshanavi を重ねる段です。

```dockerfile
# ---- 段 1: 画面 (Web UI) をビルド (npm はここだけで使う) ----
FROM node:24.14.0-bookworm-slim AS web
WORKDIR /web
COPY third_party/roshanavi/web/package.json third_party/roshanavi/web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY third_party/roshanavi/web/ ./
RUN npx vite build --outDir /out --emptyOutDir

# ---- 段 2: プロジェクトのイメージ + roshanavi ----
FROM myproj:dev
ENV DEBIAN_FRONTEND=noninteractive

COPY third_party/roshanavi/ros2_ws/src/roshanavi       /roshanavi_ws/src/roshanavi
COPY third_party/roshanavi/ros2_ws/src/roshanavi_msgs  /roshanavi_ws/src/roshanavi_msgs
COPY third_party/roshanavi/ros2_ws/src/roshanavi_probe /roshanavi_ws/src/roshanavi_probe
RUN apt-get update \
    && rosdep update --rosdistro "${ROS_DISTRO}" \
    && rosdep install --from-paths /roshanavi_ws/src --ignore-src -y \
         --dependency-types=build --dependency-types=buildtool --dependency-types=exec \
         --skip-keys "ffmpeg" \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/* /root/.ros/rosdep

WORKDIR /roshanavi_ws
RUN . /opt/ros/${ROS_DISTRO}/setup.sh \
    && colcon build --cmake-args -DCMAKE_BUILD_TYPE=Release \
    && rm -rf /roshanavi_ws/log

# 作った画面をイメージに入れ、サーバーに場所を教える
COPY --from=web /out /opt/roshanavi/static
ENV ROSHANAVI_STATIC_DIR=/opt/roshanavi/static \
    ROSHANAVI_WORKSPACE=/ws

COPY docker/roshanavi-entrypoint.sh /roshanavi-entrypoint.sh
RUN chmod +x /roshanavi-entrypoint.sh
WORKDIR /ws
ENTRYPOINT ["/roshanavi-entrypoint.sh"]
CMD ["bash"]
```

- `FROM myproj:dev` を、自分のプロジェクトのイメージ名に変えます。
- 必要な部品 (ROS の依存) は、roshanavi の `package.xml` から `rosdep` が入れます。`ffmpeg` だけは、開発用のヘッダまで入ってしまうので別に入れています。
- **詳細計測モード (トレース) も使うとき**は、`apt-get install` の行に `lttng-tools python3-bt2` を足します。どちらも任意の部品なので、rosdep では入りません (無いと、詳細計測モードの切り替えが押せず、入れ方が表示されます)。
- 段 1 (node) は、**画面のビルド済みファイルがまだ配られていない**ために必要です。**#42 で、ビルド済みの画面を同梱して、この段をなくす予定です。**

`docker/roshanavi-entrypoint.sh` は、ROS → プロジェクト → roshanavi の順に環境を読み込みます。

```bash
#!/bin/bash
set -e
source "/opt/ros/${ROS_DISTRO:?ROS_DISTRO is not set}/setup.bash"
[ -f /ws/install/setup.bash ] && source /ws/install/setup.bash
source /roshanavi_ws/install/setup.bash
exec "$@"
```

### 3. compose にサービスを足す

```yaml
x-ros-common: &ros-common
  image: myproj:dev
  build: { context: ., dockerfile: docker/Dockerfile }
  ipc: shareable
  shm_size: 512m                    # 詳細計測モードに必要 (小さいと何も記録されません)
  environment: &ros-env
    ROS_DOMAIN_ID: "31"

services:
  # プロジェクトのイメージだけをビルドする (roshanavi 入りの土台)。コンテナは起動しない
  base:
    <<: *ros-common
    restart: "no"
    scale: 0
    command: ["true"]

  # 元の起動方法 (roshanavi なし)。使うときだけ --profile plain
  sim:
    <<: *ros-common
    profiles: ["plain"]
    command: ros2 launch myproj bringup.launch.py

  # roshanavi が launch ファイルを引き取って動かす (既定)
  dev:
    <<: *ros-common
    image: myproj-roshanavi:dev
    build:
      context: .
      dockerfile: docker/roshanavi.Dockerfile
      additional_contexts:
        "myproj:dev": "service:base"      # FROM myproj:dev を base のビルド結果にする
    init: true                             # 強制終了されても、コンテナごとやり直せる
    volumes:
      - ./ros2_ws/src:/ws/src              # ランチャー・ビルド・ひな形が、いまのソースを触れる
      - ./.roshanavi:/data                 # プロジェクトの設定・録画・シナリオ結果
    ports:
      - "127.0.0.1:6871:6871"              # 自分のパソコンの中だけ
    command: ["ros2", "run", "roshanavi", "app", "--host", "0.0.0.0",
              "--workspace", "/ws", "--data-dir", "/data", "--project", "/data/roshanavi.yaml",
              "--launch", "myproj", "bringup.launch.py", "--mine", "my_node"]
```

大事な点です。

- **ポートは `127.0.0.1:` を付けて開きます。** コンテナの中で `--host 0.0.0.0` にしているのは、Docker の仕組み上そうしないと外から届かないためで、パソコンの外には出しません。別のマシンから見るときは [SSH のポート転送](remote-ssh.md) を使います。
- **`--launch <パッケージ> <launch ファイル> [引数]`** が引き取る launch ファイルです。`--mine <ノード名>` は自分が開発しているノード (地図で色が変わります)。
- **`./.roshanavi:/data`** は、roshanavi の設定・録画・シナリオ結果の置き場です。`.gitignore` に入れておくと安心です。
- **`additional_contexts`** と `base` サービスは、`FROM myproj:dev` の `myproj:dev` を「いま同じ compose でビルドするイメージ」に結びつけるための仕掛けです。これが無いと、docker はレジストリから `myproj:dev` を探しにいって失敗します。

### 4. 起動する

```bash
git submodule update --init
docker compose up -d --build        # dev (roshanavi) を起動
docker compose logs -f dev           # roshanavi のログ (ノードのログは画面で見ます)
```

http://localhost:6871 を開くと、launch ファイルのノードが全部動いています。以降の使い方は [既存の launch ファイルごと動かす](takeover.md) と同じです。

元の起動方法に戻すときです。同時に両方を動かすと、同じ ROS の名前を取り合うので、片方ずつ動かします。

```bash
docker compose stop dev
docker compose --profile plain up -d --build sim
```

### 5. .dockerignore を整える

`COPY third_party/roshanavi/...` の対象に、`.git` や `node_modules` が混ざると、ビルドが遅くなります。プロジェクトの `.dockerignore` に次を足します。

```
third_party/roshanavi/.git
third_party/roshanavi/data
third_party/roshanavi/docs
third_party/roshanavi/web/node_modules
third_party/roshanavi/web/dist
.roshanavi
```

## 既知の注意点

| 注意 | 内容 |
|---|---|
| `.roshanavi/` が root のファイルになる | コンテナは root で書くため、手元から `roshanavi.yaml` を読もうとすると `Permission denied` になります。中身を見たいときは `curl -s localhost:6871/api/project`。**#42 で改善予定** |
| 画面のビルドボタンの結果が、コンテナを作り直すと消える | ビルドの結果はコンテナの中に作られます。`docker compose up --force-recreate` や、イメージの作り直しで元に戻ります。ソース (`./ros2_ws/src`) は残るので、必要なら画面で再度ビルドします。**#42 で改善予定** |
| イメージのビルド順 | `dev` は `base` (プロジェクトのイメージ) に依存します。`additional_contexts` を書き忘れると、`FROM` が解決できず失敗します |
| 画面 (Web UI) を作る段が必要 | 上のとおり、いまは自分のイメージの中で画面をビルドします。**#42 で不要にする予定** |
| 「自動で起動する」の関数・クラスノードがあると | `docker compose restart dev` のあと、launch ファイルのノードと同じ役のノードが二重に動くことがあります。片方を止めてください |
| launch ファイルの動作が一部元どおりにならない | ノードを 1 つずつ動かすため、`on_exit=Shutdown()` やイベントは働かないことがあります。画面に一覧が出ます。必要なら `--launch-mode whole` ([既存の launch ファイルごと動かす](takeover.md)) |
| ポートの重なり | roshanavi を複数動かすときは、`ports:` と `--port` を別の番号にします。`127.0.0.1:6872:6872` のように両方そろえます |

## うまくいかないとき

| 症状 | 確かめること |
|---|---|
| ビルドが `pull access denied` や `not found` で止まる | `additional_contexts` と `base` サービスがあるか。`docker compose build base` を先に |
| `third_party/roshanavi/...: not found` | `git submodule update --init` を実行したか。`.dockerignore` で除外していないか |
| 画面が真っ白、または API だけ動く | 画面のビルド済みファイルが `/opt/roshanavi/static` に入っているか (`ROSHANAVI_STATIC_DIR`)。段 1 が成功したか |
| 地図が空 | `ROS_DOMAIN_ID` がそろっているか。launch ファイルのノードが起動に失敗していないか (ランチャーのログ) |
| 詳細計測モードが使えない | `lttng-tools` と `python3-bt2` をイメージに入れたか (上の Dockerfile の注を参照)。`shm_size: 512m` を付けたか |
| 独自のメッセージ型の中身が読めない | `FROM` がプロジェクトのイメージになっているか (型が入っているイメージの上に重ねます) |
| roshanavi が強制終了して、ノードが残った | `docker restart <コンテナ>` でコンテナごとやり直します (`init: true` が前提) |

## 仕組みを知りたい人へ

- launch ファイルを引き取る仕組み、Docker の場合: [design/integration.md](../design/integration.md)
- 組み込みの計画と、これからの改善 (#42): [planned/integration.md](../planned/integration.md)
- 配布の設計: [project/distribution.md](../project/distribution.md)
