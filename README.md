# roshanavi

**ROS 2 のノード開発を、ブラウザひとつで。** ROS をよく知らない人でも、ノードを起動し、入力を流し、出力と通信の様子を見て、テストまでできる開発ツールです。

対応: **ROS 2 Jazzy・Lyrical Luth** に正式対応。Kilted Kaiju は動作確認のみ (継続的な保証なし) です。

![通信マップ](docs/images/graph-roles.png)

## なぜ作ったか

ROS 2 の確認・テストの道具 (`ros2 topic hz/echo/pub`、rqt_graph、rqt_publisher、launch_testing、rosbag …) は便利ですが、ばらばらで、それぞれの使い方と組み合わせ方を知っている前提です。roshanavi はそれらを 1 つの画面にまとめ、ROS に詳しくない開発者がつまずく所 (QoS の不一致、受信側がいない、トピック名の打ち間違い …) をツール側から指摘します。

## できること

| 機能 | 内容 |
|---|---|
| ライブ通信マップ | ノードとトピックのつながりを、通信の流れのアニメーション付きでリアルタイム表示。QoS 不一致・似たトピック名 (打ち間違い)・さっきまでいたノードの消失・開発中のノードの入力が空、などを診断。送信だけ・受信だけのトピックは警告にせず、控えめな印だけ |
| トラフィック | ノード × トピック × 向きごとの Hz・帯域・取りこぼし・遅延。C++ 計測ノードで送信元ごとに実測 |
| 詳細計測モード | ROS 2 組み込みのトレース (LTTng) で、受信数・処理数・コールバックの処理時間を実測。ソースの変更は不要 |
| ランチャー | 自分のノードと依存ノードの起動・停止・ログ・ビルド。既存の launch ファイルを分解して取り込み、ノード一覧で一括 ON/OFF |
| launch の引き取り | `ros2 run roshanavi app --launch <パッケージ> <launch ファイル>` で、今の launch ファイルのノードを roshanavi が起動し、1 つずつ止める・再起動・ログ。launch ファイルの変更も検出 ([利用ガイド: 既存の launch ファイルごと roshanavi で動かす](docs/guide/takeover.md)) |
| 入力ノード | 文字列・数値・画像・動画・音声・ブラウザのマイク/カメラを、常駐するダミーノードとして送る |
| 変換ノード | 「トピック A を受けて B に出す」ノードを、式を書くだけで作る (未完成のノードの代役にも) |
| 関数・クラスノード | 普通の Python の関数やクラス (状態・パラメータ・リセット付き) を、そのまま ROS ノードとして動かす。置き場所・ひな形・依存の入れ方は [利用ガイド: 自分のコードを関数・クラスノードにする](docs/guide/user-code.md) |
| 線でつないで作る | 関数・クラス・変換・入力ノードの「つなぎ口」から、地図の上でチャンネル (トピック) へ線を引いてつなぐ (種類が合わない線は理由付きで断る、キーボードでも操作可)。言葉は用語集で統一 (チャンネル (トピック) など)。[利用ガイド: 線でつないで作る](docs/guide/wiring.md) |
| 録画・再生 | bag に録って、次から同じ入力で再現 |
| シナリオ | 「入力したら、○秒以内にこう出る」を記録して、UI と CLI で自動判定 |
| リソース監視 | ノードごとの CPU・メモリ (地図にバッジ)、PC 全体の CPU・メモリ・ディスク・ネットワーク・GPU、外部との接続先、メモリリークの疑いと UDP 受信バッファ溢れの診断 (この PC のみ) |
| チュートリアル | 画面の見方・入力ノード・QoS の直し方・関数ノード・シナリオを、画面上で操作を案内しながら学べる (⚙ 設定からいつでも) |
| 中継パイプラインのサンプル | 受け取って次に送る C++ ノード (処理時間・大きさ・頻度・取りこぼしを調整) を、直列・分岐・合流・格子の形と 3 / 20 / 200 ノードの規模で生成して、別プロセスでも composable container でも動かせる ([利用ガイド: 測る (性能)](docs/guide/measure.md#6-性能-規模と負荷の限界)) |

![関数ノードの作成](docs/images/function-dialog.png)

MVP の対象はトピックのみです。**サービス・アクションへの対応は今後予定しています。**

## 試す (Docker)

ホストに ROS は不要です。Docker と Docker Compose があれば動きます。

```bash
git clone https://github.com/shimejilib/roshanavi.git
```

```bash
cd roshanavi && docker compose up -d --build lab demo
```

ブラウザで http://localhost:6871 を開きます。デモの talker / listener (roshanavi から起動したノード) と、外部ノードの例が表示されます。⚙ 設定 →「プロジェクトを切り替える」から、画像処理のデモ (perception_demo) と、rclpy の MultiThreadedExecutor が CPU を空回りする様子を確かめるデモ (busy_demo) も開けます。

自分のプロジェクトでの使い方は、次の「使い方・組み込み方」を見てください。

## 使い方・組み込み方

詳しい手順は [利用ガイド](docs/guide/README.md) の各章にあります。

| やりたいこと | 方法 | 説明 |
|---|---|---|
| まず画面を見て回る | Docker で起動して、チュートリアルをたどる | [はじめての起動と画面の見方](docs/guide/getting-started.md) |
| 入力を流す | 入力ノード・お試し送信で、文字・画像・動画・音声・マイク・カメラを流す。録画して再現する | [入力を流す](docs/guide/inputs.md) |
| 自分の Python のコードをノードにする | 普通の関数・クラスを「関数・クラスノード」にし、地図の上で線をつなぐ | [自分のコードを関数・クラスノードにする](docs/guide/user-code.md)、[線でつないで作る](docs/guide/wiring.md) |
| 既存の起動セット (launch ファイル) ごと動かす | `ros2 run roshanavi app --launch <パッケージ> <launch ファイル>`。ノードごとに止める・再起動・ログ・計測ができる | [既存の起動セットごと動かす](docs/guide/takeover.md) |
| Docker で動いている既存のプロジェクトに入れる | 既存のイメージの上に roshanavi を重ねたコンテナを 1 つ足し、`--launch` で引き取る | [Docker で動いている既存のプロジェクトに入れる](docs/guide/docker-integration.md) |
| 動いているシステムを、手を入れずに見るだけ | 同じ ROS のネットワーク (ドメイン ID) で起動する。ノードの停止や詳細計測はできない | [動いているシステムを見るだけ](docs/guide/observe.md) |
| テストや CI に組み込む | 画面で記録したシナリオを `ros2 run roshanavi scenario run <ファイル> --junit 結果.xml` で実行。launch_pytest からも呼べる | [シナリオで確かめる・テストに組み込む](docs/guide/scenarios.md) |
| 通信量・処理時間・CPU・メモリを測る | トラフィック、詳細計測モード、リソースタブ | [測る](docs/guide/measure.md) |
| 自分のワークスペースで使う | `src/` に入れてビルドし、`ros2 run roshanavi app` で起動する (Web 画面の作り方など、手順は整備中) | [自分のワークスペースに入れる](docs/guide/install.md) |
| 別のマシンから見る | SSH のポート転送 (`ssh -L 6871:localhost:6871 …`) | [別のマシンから見る (SSH)](docs/guide/remote-ssh.md) |

## 計測の精度と限界

- **メモリリークの検出**: 「一定の速さで、減速せずに、長く増え続けるメモリ」だけを疑いとして出します。一度だけの増加・頭打ち・一瞬のスパイクは出しません。ゆっくりした漏れは検出まで時間がかかり (揺れが ±6 MB のプロセスで 0.05 MB/分なら約 6 時間)、**どのコードが漏らしているかは分かりません**。
- **見えるのは、roshanavi が動いている PC のプロセスだけ**です (CPU・メモリ・リーク)。別の PC や別のコンテナのノードは見えません。詳細計測モードも同じ PC、roshanavi より後に起動したノードが対象で、Python のノードは受信数だけです。
- **規模と負荷**: 80 ノード (128 トピック) まで地図は 1 秒周期のまま、200 ノードでは更新が遅れます。計測ノードの CPU は流量に比例し、メッセージが約 85 KB より大きいとバイト数が、小さいと件数が効きます。4K × 30 Hz のような重いデータは計測を切るか詳細計測モードで。
- 受信側ノードの Hz は、詳細計測モードを使わないときは「理論値」(届くはずの量) です。

表と数字の根拠は [利用ガイド: 測る](docs/guide/measure.md) にあります。

## ドキュメント

- **[利用ガイド](docs/guide/README.md)**: 使い方の章の一覧 (最初に読むもの)
- 全体像: [vision](docs/overview/vision.md) (出発点・対象ユーザー)、[architecture](docs/overview/architecture.md) (技術選定・構成)、[roadmap](docs/overview/roadmap.md) (進み具合)
- 機能ごとの設計 ([docs/design/](docs/design/)): [map-and-traffic](docs/design/map-and-traffic.md)、[measurement](docs/design/measurement.md)、[input-and-media](docs/design/input-and-media.md)、[nodes](docs/design/nodes.md)、[user-code](docs/design/user-code.md)、[launcher](docs/design/launcher.md)、[integration](docs/design/integration.md)、[ui](docs/design/ui.md)、[api](docs/design/api.md)、[security](docs/design/security.md)、[scenarios](docs/design/scenarios.md)、[resources](docs/design/resources.md)、[wiring](docs/design/wiring.md)
- 開発・運用: [testing](docs/project/testing.md)、[dependencies](docs/project/dependencies.md)、[distribution](docs/project/distribution.md)。設計済み・未実装: [remote-access](docs/planned/remote-access.md)、[integration](docs/planned/integration.md)
- 索引: [docs/README.md](docs/README.md)。既知の課題と今後の予定は GitHub Issues で管理しています。

## 開発

```bash
docker compose --profile test run --rm test
```

```bash
cd web && npm ci && npx vitest run
```

```bash
scripts/e2e.sh
```

それぞれ、バックエンドのテスト (gtest + pytest)、Web UI の単体テスト、E2E (専用の環境で実行し、手元の lab には触れない) です。詳しくは [docs/project/testing.md](docs/project/testing.md)。

## ライセンス

[MIT](LICENSE)
