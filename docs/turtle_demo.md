# turtlesim のデモ (turtle_demo)

roshanavi の実演用に作った、小さな ROS 2 のプロジェクトです。**roshanavi のリポジトリには同梱していません。** `turtle_demo` という別のリポジトリです。

> 公開先: https://github.com/shimejilib/turtle_demo (公開の準備中です。公開までは、このページの手順は使えません)

roshanavi 本体を試すだけなら、このデモは要りません。本体に同梱の見本 (`docker compose up -d --build lab demo` で動く talker / listener、画像処理の `perception_demo`、`busy_demo`) で、一通りの機能が試せます ([はじめての起動と画面の見方](guide/getting-started.md))。turtle_demo は、「**すでに動いている普通の ROS 2 のプロジェクトに、roshanavi を後から足す**」ところと、「**普通の Python のクラスをノードにする**」ところを通しで見たいときのものです。

## 何ができるプロジェクトか

turtlesim (ROS に付いてくる亀のシミュレータ) の亀を、ノード `turtle_patrol` が動かします。最初は四角形を描いて歩き回ります。これを題材に、次の 3 つの場面を順に体験できます。

| 場面 | 内容 | くわしい手順 |
|---|---|---|
| ① 既存のシステムに組み込む | docker compose で動いている普通のプロジェクト (シミュレータ `sim` と、コントローラ `patrol`) に、roshanavi を足す。足すのは、イメージの重ね書き、compose のサービス 1 つ、起動の引数 1 行だけで、ノードのコードは 1 行も変えない。地図、トラフィック、ノードごとの停止と再起動、ログが使えるようになる | [Docker で動いている既存のプロジェクトに入れる](guide/docker-integration.md)、[既存の launch ファイルごと roshanavi で動かす](guide/takeover.md) |
| ② 既存の OSS のモジュールを、ROS を学ばずにノードにする | pip でも apt でも入らない OSS の PID 制御ライブラリ ([simple-pid](https://github.com/m-lundberg/simple-pid)) を、git のサブモジュールで取り込む。普通の Python のクラス (`GoToGoal`) を 1 つ書くだけで、ROS のノードとして動かし、亀を目標の座標へ向かわせ、シナリオで確かめる | [自分のコードを関数・クラスノードにする](guide/user-code.md)、[シナリオで確かめる](guide/scenarios.md) |
| ③ PID のつまみを回して、効き方を見る | 動かしたまま、P・I・D の値、速さの上限、位置の遅れ (遅延ノードを地図の上でつなぐ) を画面で変えて、亀の通り道が「ほぼ直進 → 弧 → 周回 → 行き過ぎ → 収まる → 遅れでくねくね」と変わるのを見る | [線でつないで作る](guide/wiring.md)、[ランチャーで自分のノードを動かす](guide/launcher.md) |

## 中身

| ファイル・フォルダ | 内容 |
|---|---|
| `README.md` | プロジェクトの説明 (英語)。構成、ビルドと実行、roshanavi の使い方 |
| `DEMO.md` | 実演の台本 (日本語)。上の ①②③ の 3 部構成で、合わせて 40〜45 分。話す内容、実行するコマンド、画面で見えるもの、失敗したときの代わりの手順、最初の状態に戻す手順、実測の時間 |
| `TRY_IT.md` | 一人で試す練習問題 (日本語)。③ を自分の手でやる。円を描かせる、最短で着くゲインを探す、I を強くして行き過ぎを見る、D で収める、遅延 500 ms でも振動しない設定を探す、自分で `GoToGoal` を書き換える、の 6 問と、実測の答え |
| `ros2_ws/src/turtle_patrol/` | 亀を動かすパッケージ。四角形を歩く `patrol` ノード、PID で目標へ向かう `GoToGoal` のクラス、launch ファイル、テスト |
| `ros2_ws/src/turtle_viz/` | 亀の通り道を画像にするクラス (`TrajectoryCanvas`) |
| `docker/`、`docker-compose.yml` | プロジェクトのイメージ (ROS + turtlesim)、その上に roshanavi を重ねたイメージ、compose の定義 (`dev` が既定。roshanavi なしの元の 2 コンテナは `plain` プロファイル) |
| `third_party/` | `roshanavi` と `simple-pid` の git サブモジュール |
| `demo/scenarios/` | デモで使うシナリオ (`goto_goal` は成功、`goto_goal_broken` はわざと失敗) |
| `scripts/` | 開始状態に戻す (`demo_reset.sh`)、台本どおりの自動リハーサル (`demo_rehearsal.py`) など |

## 動かし方

必要なものは Docker と Docker Compose、git だけです (ROS は要りません)。

### 1. 取ってくる

```bash
git clone --recurse-submodules https://github.com/shimejilib/turtle_demo.git
```

```bash
cd turtle_demo
```

サブモジュールが空のときは、`git submodule update --init` を実行します。

### 2. 起動する

```bash
docker compose up -d --build
```

初回は、プロジェクトのイメージと、その上に roshanavi を重ねたイメージのビルドに、時間がかかります (roshanavi の Web 画面のビルド用に Node.js がイメージの中で使われます。ホストには要りません)。

終わったら、ブラウザで **http://localhost:6872** を開きます。roshanavi の既定のポート 6871 とは、わざと別にしてあります (本体の見本を同時に動かしても、ぶつかりません)。

- 地図に、`/sim` (turtlesim)、`/patrol`、`/turtle_viz` が現れます。亀が四角形を歩いています。
- `ROS_DOMAIN_ID` は `31` に固定してあります。
- 止めるときは `docker compose down` です。

### 3. 台本に沿って試す

- 人に見せるとき: `DEMO.md`。最初に `scripts/demo_reset.sh` で開始状態にし、`[OK]` が並ぶことを確かめます。
- 一人で試すとき: `TRY_IT.md`。準備のコマンドのあと、画面を 2 つのウィンドウで並べて、練習問題を順に進めます。

### roshanavi なしの元の姿を見る

```bash
docker compose stop dev
```

```bash
docker compose --profile plain up -d --build sim patrol
```

ログに `Side N done` が流れるだけの、普通のプロジェクトです。roshanavi を足す前と後を見比べられます。終わったら、`docker compose --profile plain stop sim patrol` と `docker compose --profile plain rm -f sim patrol` のあとで `docker compose up -d dev` に戻します (どちらも同じ亀を動かすので、同時には動かしません)。

## うまくいかないとき

| 症状 | 確かめること |
|---|---|
| `third_party/roshanavi/...: not found` でビルドが止まる | `git submodule update --init` を実行したか |
| 画面が開かない | `docker compose ps` で `dev` が動いているか。ポート 6872 を別のものが使っていないか |
| 亀が動かない・地図が空 | `docker compose logs dev` を見る。`plain` のコンテナが同時に動いていないか |
| デモの途中で状態がおかしくなった | `scripts/demo_reset.sh` で開始状態に戻す。戻らないときは `DEMO.md` の「戻らないとき」の手順 |
| 画面の言葉が、台本の言葉と違う | 台本は、roshanavi の特定の版の画面の言葉で書いてあります。roshanavi を更新したあとは、台本を見直す必要があります |

## 仕組みを知りたい人へ

- launch ファイルを引き取る仕組み: [design/integration.md](design/integration.md)
- クラスノードとコードの置き場所 (B. 登録した場所): [design/user-code.md](design/user-code.md)
- 配線: [design/wiring.md](design/wiring.md)
