# roshanavi

**ROS 2 のノード開発を、ブラウザひとつで。** ROS をよく知らない人でも、ノードを起動し、入力を流し、出力と通信の様子を見て、テストまでできる開発ツールです。

対応: **ROS 2 Jazzy・Lyrical Luth** に正式対応。Kilted Kaiju は動作確認のみ (継続的な保証なし) です。

名前は「ROS + 花火 (launch = 打ち上げ)」と「ナビ (案内役)」から。既定のポート 6871 も ro(6)s-ha(8)-na(7)-bi(1)。

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
| launch の引き取り | `ros2 run roshanavi server --launch <パッケージ> <launch ファイル>` で、今の launch ファイルのノードを roshanavi が起動し、1 つずつ止める・再起動・ログ。launch ファイルの変更も検出 ([利用ガイド: 既存の launch ファイルごと roshanavi で動かす](docs/guide/takeover.md)) |
| 入力ノード | 文字列・数値・画像・動画・音声・ブラウザのマイク/カメラを、常駐するダミーノードとして送る |
| 変換ノード | 「トピック A を受けて B に出す」ノードを、式を書くだけで作る (未完成のノードの代役にも) |
| 関数・クラスノード | 普通の Python の関数やクラス (状態・パラメータ・リセット付き) を、そのまま ROS ノードとして動かす。置き場所・ひな形・依存の入れ方は [利用ガイド: 自分のコードを関数・クラスノードにする](docs/guide/user-code.md) |
| 録画・再生 | bag に録って、次から同じ入力で再現 |
| シナリオ | 「入力したら、○秒以内にこう出る」を記録して、UI と CLI で自動判定 |
| リソース監視 | ノードごとの CPU・メモリ (地図にバッジ)、PC 全体の CPU・メモリ・ディスク・ネットワーク・GPU、外部との接続先、メモリリークの疑いと UDP 受信バッファ溢れの診断 (この PC のみ) |
| チュートリアル | 画面の見方・入力ノード・QoS の直し方・関数ノード・シナリオを、画面上で操作を案内しながら学べる (⚙ 設定からいつでも) |

![関数ノードの作成](docs/images/function-dialog.png)

MVP の対象はトピックのみです。**サービス・アクションへの対応は今後予定しています。**

## リソース監視とメモリリークの検出

ノードごとの CPU・メモリを地図にバッジで出し、「リソース」タブで PC 全体 (CPU・メモリ・ディスク・ネットワーク・GPU) とプロセス一覧を見られます。roshanavi 自身のプロセスは「roshanavi 自身」という別枠に並びます。**監視できるのは roshanavi が動いている PC のプロセスだけです。**

メモリが増え続けるプロセスは、リーク検出が見つけます。「リーク」を **一定の速さで、減速せずに、長く増え続けるメモリ** と定義し、1 分ごとの中央値から、10 分・1 時間・6 時間の 3 つの時間スケールで同時に判定します。

- 診断パネルに出るのは **リークの疑い**: 「`/detector` のメモリが毎分 0.3 MB で 2 時間増え続けています (減速なし)」のように、速さと継続時間を数値で出します。
- **様子見 (増加中・収束しつつある)** は、リソースタブにだけ出ます: 一度だけの増加の直後や、バッファが埋まって頭打ちになる途中です。
- 誤検出しないパターン (単体テストで確認): 一度だけの段差、頭打ち (バッファが埋まる)、一瞬のスパイク、揺れだけで増えていない場合 (24 時間の実行 400 回で 0 回)。

**検出できる速さと、検出までの時間** (合成データで実際に検出できた最小の速さ。かっこは検出までの時間の中央値 / 最大):

| 時間スケール | 判定できる最短時間 | 揺れが小さい (±1 MB) | 揺れがふつう (±6 MB) | 揺れが大きい (±20 MB) |
|---|---|---|---|---|
| 10 分 | 17 分 | 0.5 MB/分 (17 分 / 17 分) | 1 MB/分 (173 分 / 425 分) | 3 MB/分 (173 分 / 425 分) |
| 1 時間 | 59 分 | 0.07 MB/分 (76 分 / 261 分) | 0.3 MB/分 (106 分 / 416 分) | 1 MB/分 (105 分 / 347 分) |
| 6 時間 | 347 分 (約 6 時間) | 0.01 MB/分 (437 分 / 637 分) | 0.05 MB/分 (347 分 / 381 分) | 0.15 MB/分 (347 分 / 381 分) |

最小の速さ ≈ メモリの自然な揺れ ÷ 観察時間です。遅いリークほど検出は遅くなりますが、見逃しにくくなります (3 MB/分なら 17 分、揺れがふつうのプロセスの 0.1 MB/分は約 6 時間で検出)。測り方と数字の根拠は [docs/design/resources.md](docs/design/resources.md#メモリリークの見せ方-leakpy-45) にあります。

**限界**
- 見ているのは RSS (実際に使っている物理メモリ) です。言語のアロケータが解放したメモリを OS に返さないと、リークでなくても減りません。
- 揺れに埋もれる小さな漏れは、観察時間が短いうちは検出できません (表のとおり)。ゆっくり埋まるバッファは、最初の 20〜40 分ほどリークの疑いに見えることがあります (埋まれば消えます)。
- **どのコードが漏らしているかは分かりません**。原因の特定は各言語のプロファイラ (Python の tracemalloc / memray、C++ の valgrind / heaptrack など) を使ってください。
- 同じ PC のプロセスだけが対象です (他の PC や別コンテナのノードは見えません)。

## 試す (Docker)

ホストに ROS は不要です。Docker と Docker Compose があれば動きます。

```bash
git clone https://github.com/shimejilib/roshanavi.git
```

```bash
cd roshanavi && docker compose up -d --build lab demo
```

ブラウザで http://localhost:6871 を開きます。デモの talker / listener (roshanavi から起動したノード) と、外部ノードの例が表示されます。⚙ 設定 →「プロジェクトを切り替える」から、画像処理のデモ (perception_demo) と、rclpy の MultiThreadedExecutor が CPU を空回りする様子を確かめるデモ (busy_demo) も開けます。

自分のワークスペースで使う手順は [docs/project/distribution.md](docs/project/distribution.md) を参照してください (ソースからのインストール。将来は apt で配布予定)。

## ドキュメント

| ドキュメント | 内容 |
|---|---|
| **使い方** | |
| [docs/guide/README.md](docs/guide/README.md) | 利用ガイド (章の一覧)。最初の章は [自分のコードを関数・クラスノードにする](docs/guide/user-code.md) |
| **まず読むもの** | |
| [docs/overview/vision.md](docs/overview/vision.md) | 出発点、対象ユーザー、ノード開発者の利用の流れ、ゴールと非ゴール |
| [docs/overview/architecture.md](docs/overview/architecture.md) | 技術選定、リポジトリ構成、全体の仕組み |
| [docs/overview/roadmap.md](docs/overview/roadmap.md) | フェーズと進み具合 |
| **機能ごとの設計 (実装済み)** | |
| [docs/design/map-and-traffic.md](docs/design/map-and-traffic.md) | 通信マップ、トラフィック、診断 |
| [docs/design/measurement.md](docs/design/measurement.md) | C++ 計測ノード、詳細計測 (トレース)、ベンチマーク結果 |
| [docs/design/input-and-media.md](docs/design/input-and-media.md) | お試し送信、メディア注入、ブラウザ取り込み、録画 |
| [docs/design/nodes.md](docs/design/nodes.md) | 入力ノード、変換ノード、関数ノード、クラスノード、データの種類 |
| [docs/design/user-code.md](docs/design/user-code.md) | 関数・クラスノードのコードの置き場所 (A/B/C)、見つからない理由、ひな形、依存ライブラリ |
| [docs/design/launcher.md](docs/design/launcher.md) | ランチャー、プロジェクトファイル、パラメータ、lifecycle、launch の取り込み |
| [docs/design/ui.md](docs/design/ui.md) | 画面構成、右クリックメニュー、ノード一覧 |
| [docs/design/api.md](docs/design/api.md) | REST / WebSocket API |
| [docs/design/security.md](docs/design/security.md) | 安全対策 (式評価、パス検査、サブプロセス、launch のサンドボックス、Host/Origin 検査) |
| [docs/design/scenarios.md](docs/design/scenarios.md) | シナリオと記録モード |
| [docs/design/resources.md](docs/design/resources.md) | リソース監視 (CPU・GPU・メモリ・ディスク・ネットワーク)、メモリリーク検出 |
| **設計済み・未実装** | |
| [docs/planned/remote-access.md](docs/planned/remote-access.md) | 別マシンからのアクセス (デバイスのペアリングと権限) |
| **開発・運用** | |
| [docs/project/testing.md](docs/project/testing.md) | テスト方針、テストの実行方法、テスト項目一覧 |
| [docs/project/dependencies.md](docs/project/dependencies.md) | 依存関係 (用途・ライセンス・rosdep キー) |
| [docs/project/distribution.md](docs/project/distribution.md) | 配布形態とインストール |

docs 全体の案内は [docs/README.md](docs/README.md) にもあります。既知の課題と今後の予定は GitHub Issues で管理しています。

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
