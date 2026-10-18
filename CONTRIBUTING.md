# roshanavi への貢献 (Contributing)

roshanavi への関心をありがとうございます。バグの報告、使いにくかった所の指摘、ドキュメントの直し、コードの提案を歓迎します。ROS に詳しくない人が最初につまずく所を減らすのが、このツールの目的です。「ここが分かりにくかった」という報告も、立派な貢献です。

*English summary: Bug reports, usability feedback, docs fixes and pull requests are welcome. Development runs entirely in Docker (ROS is not needed on the host). Please read "テスト" (tests) and "コミットと Pull Request" (commits) below before opening a pull request. The UI is Japanese by default; English is planned (#28). Issues and pull requests in English are fine.*

行動規範は [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)、脆弱性の報告は [SECURITY.md](SECURITY.md) を見てください。脆弱性は、公開の Issue には書かないでください。

## 目次

1. [Issue を書く](#1-issue-を書く)
2. [開発環境 (Docker)](#2-開発環境-docker)
3. [テスト](#3-テスト)
4. [コミットと Pull Request](#4-コミットと-pull-request)
5. [ドキュメントの構成](#5-ドキュメントの構成)
6. [言語 (日本語と英語)](#6-言語-日本語と英語)
7. [コードを書くときの約束](#7-コードを書くときの約束)

## 1. Issue を書く

[Issues](https://github.com/shimejilib/roshanavi/issues) のテンプレートに沿って書いてください。次の情報があると、再現しやすくなります。

- ROS 2 のディストロ (Jazzy / Lyrical / Kilted)
- RMW (`echo $RMW_IMPLEMENTATION`。空なら既定)
- Docker で動かしているか、ネイティブか
- roshanavi のバージョン (またはコミット)
- 手順、期待した動き、実際の動き
- 画面のスクリーンショット、ログ (ランチャーのログや `docker compose logs lab`)

機能の提案は、「何をしたいか」(困っていること) から書いてもらえると助かります。実現方法は、あとで一緒に考えられます。

## 2. 開発環境 (Docker)

**ROS はホストに入れません。** ビルド、テスト、実行のすべてを Docker で行います。必要なものは Docker と Docker Compose、Web 画面の開発をするときは Node.js (npm) です。

```bash
git clone https://github.com/shimejilib/roshanavi.git
```

```bash
cd roshanavi && docker compose up -d --build lab demo
```

ブラウザで http://localhost:6871 を開くと、画面が見えます (`lab` が roshanavi、`demo` が見本のノードです)。

### ROS のディストロを選ぶ

どの `docker compose` のコマンドも、先頭に `ROS_DISTRO=jazzy|lyrical|kilted` を付けられます (既定は `jazzy`。イメージ名は `roshanavi:dev-<distro>`)。

```bash
ROS_DISTRO=lyrical docker compose --profile test run --rm test
```

**Jazzy と Lyrical が正式対応**です。ROS・pydantic・FastAPI に触れる変更は、両方で確かめてください。Kilted は動作確認のみです。pydantic の名前は、`pydantic` から直接ではなく `roshanavi.pydantic_compat` から import します。

### 並行して別の環境を動かすとき

2 つ目のチェックアウトや git worktree で動かすときは、お互いが干渉しないよう、環境変数を分けます。

```bash
export ROSHANAVI_IMAGE=roshanavi:mybranch COMPOSE_PROJECT_NAME=roshanavi-mybranch ROS_DOMAIN_ID=91 E2E_ROS_DOMAIN_ID=92
```

### Web 画面の開発

```bash
cd web && npm ci
```

開発サーバーは `/api` と `/ws` を `:6871` へ中継するので、ホットリロードで画面を直せます ([docs/design/ui.md](docs/design/ui.md))。

### リポジトリの構成

| 場所 | 内容 |
|---|---|
| `ros2_ws/src/roshanavi` | 本体 (Python。FastAPI + rclpy のサーバー、ダミーノード、シナリオ CLI) |
| `ros2_ws/src/roshanavi_msgs`、`roshanavi_probe` | 計測ノード (C++) と、その内部用のメッセージ型 |
| `ros2_ws/src/roshanavi_examples`、`roshanavi_test_nodes` | サンプルのノード、テスト用のノード |
| `web/` | Web 画面 (React + Vite + TypeScript) |
| `docker/`、`docker-compose.yml` | 開発・テスト・E2E の環境 |
| `docs/` | ドキュメント (5 を参照) |
| `examples/` | デモのプロジェクト、サンプルのシナリオ |
| `scripts/` | E2E、ベンチマーク、リリースの作成 |

全体のつながりは [docs/overview/architecture.md](docs/overview/architecture.md) にあります。

## 3. テスト

新しい機能には、テストを付けてください (ユニットテストと統合テスト。画面の操作は E2E)。可能なら、テストを先に書きます。

| 対象 | コマンド |
|---|---|
| バックエンド全体 (gtest + pytest) | `docker compose --profile test run --rm test` |
| 1 ファイルだけ | `docker compose --profile test run --rm test python3 -m pytest -p no:cacheprovider -q /ws/src/roshanavi/test/<file>.py -k <式>` |
| Web の単体テスト | `cd web && npm ci && npx vitest run [file]` |
| 型検査 | `cd web && npx tsc --noEmit` |
| E2E (専用の隔離した環境) | `scripts/e2e.sh` |

### テストの方針

- **反復中は、変更に関係するテストだけ**を動かします。バックエンド全体と `scripts/e2e.sh` は、最後に 1 回ずつ動かします。
- 実時間のテスト (Hz、ペース、遅延) が多いので、マシンが忙しいと揺れます。**変更と無関係で、単独なら通る失敗はタイミングの揺れ**として、Pull Request に書いてください (追いかけなくて構いません)。**許容範囲をゆるめて、本物の遅れを隠さないでください。**
- E2E は、利用者のデータ (`./data`) と動いている `lab` に**触れない**作りです (別の `ROS_DOMAIN_ID`、空の `/data`、ポート非公開)。この性質を壊さないでください。
- セキュリティの境界 (式の評価、パスの検査、`Host` / `Origin` の検査など) を触る変更は、境界を確かめるテスト (拒否されるケース) を必ず付けます。

テスト項目の一覧と状態は [docs/project/testing.md](docs/project/testing.md) にあります。触った節を更新してください。

## 4. コミットと Pull Request

### コミットメッセージ

[Conventional Commits](https://www.conventionalcommits.org/ja/) の形にします。

```
<type>: <説明>

<必要なら本文>
```

`type` は次のいずれかです: `feat` (機能)、`fix` (不具合の修正)、`docs`、`test`、`refactor`、`perf`、`build`、`ci`、`chore`、`style`。範囲を示すときは `docs(guide): ...` のようにします。説明は日本語でも英語でも構いません。

### Pull Request

1. 最新の `main` から作業用のブランチを作ります。
2. 上のテストを通します。画面に関わる変更は、スクリーンショットを添えてください。
3. Pull Request のテンプレートに沿って、何を・なぜ変えたかと、確かめたことを書きます。
4. 関係する Issue があれば `Closes #番号` と書きます。
5. 大きな変更は、先に Issue で相談してください。

依存を足すときは、`package.xml`、`Dockerfile`、`web/package.json` と [docs/project/dependencies.md](docs/project/dependencies.md) を一緒に更新します。**Docker にだけ入っていて `package.xml` に無い依存を作らないでください** (ソースから入れる人が動かなくなります)。

## 5. ドキュメントの構成

`docs/` が唯一の原本です。入口は [docs/README.md](docs/README.md) (全文書の 1 行の説明)。

| フォルダ | 読む人 | 内容 |
|---|---|---|
| `docs/guide/` | roshanavi を使う人 | やりたいことから引ける手順の章。各章は「手順 → うまくいかないとき → 仕組みを知りたい人へ」の順 |
| `docs/overview/` | 初めて読む人 | 出発点と対象ユーザー (vision)、構成 (architecture)、進み具合 (roadmap) |
| `docs/design/` | 開発者 | 機能ごとの設計と決定事項 (仕様の原本) |
| `docs/project/` | 開発者 | テスト、依存関係、配布の設計 |
| `docs/planned/` | 開発者 | 設計済みで未実装のもの |
| `docs/images/` | | 画面のスクリーンショット (E2E が書き出す) |

- 設計 (`docs/design/`) と利用ガイド (`docs/guide/`) で同じ内容を二重に書かず、片方からリンクします。設計へのリンクは、ガイドの章の最後に置きます。
- 画面の文言とガイドの言葉は、ROS の公式の用語 (トピック、パラメータ、launch ファイル、QoS、メッセージ型 …) を主に使い、必要なら短いふつうの言葉の説明を括弧で添えます。
- スクリーンショットは、手で撮らずに E2E (`web/e2e/*.spec.ts`) に書き出させます。
- ドキュメントは MkDocs (Material) でサイトにできます (`mkdocs.yml`)。手元で確かめるには次のとおりです。

```bash
pip install mkdocs-material
```

```bash
mkdocs serve
```

## 6. 言語 (日本語と英語)

- 画面は**日本語が既定**です。英語の画面は予定にあります ([#28](https://github.com/shimejilib/roshanavi/issues/28))。画面の文言は `web/src/i18n/` にまとめてあるので、文言をコードの中に直接書かないでください。
- ドキュメントは日本語です。英語への翻訳の提案は歓迎します (先に Issue で相談してください)。
- Issue と Pull Request は、日本語でも英語でも構いません。
- コード中のコメントと識別子は、英語でも日本語でも構いませんが、1 つのファイルの中ではそろえてください。

## 7. コードを書くときの約束

プロジェクトで過去につまずいたことです。守ってください。

- **`eval` / `exec` で利用者の入力を実行しない。** 式は、許可したノードだけを評価する評価器 (`expr.py`、`msg_view.py`) を通します。
- **サブプロセスは、シェルを使わず、argv のリストで起動する。** 利用者が指定するパスは、`realpath` でワークスペースか data フォルダの中にあることを確かめる。
- **サーバーは既定で `127.0.0.1` だけで待ち受ける。** 新しい REST・WebSocket は、必ず `Host` / `Origin` / `Content-Type` の検査の内側に置く。
- **roshanavi が起動していないプロセスに、シグナルを送らない。**
- `ros_runtime.create_subscription` は、QoS イベントのハンドラを**わざと登録しません** (rclpy の executor が空回りして、CPU を使い切るため)。新しい購読やクライアントでも同じにしてください。
- レート (Hz) の意味は 1 つ (`stats.window_rate`)。画面ごとに別の計算をしない。

セキュリティ上の判断の一覧は [docs/design/security.md](docs/design/security.md) にあります。新しい機能を足す前に、当てはまるものがないか確認してください。

## ライセンス

貢献いただいたものは、このプロジェクトと同じ [MIT ライセンス](LICENSE) で公開されます。
