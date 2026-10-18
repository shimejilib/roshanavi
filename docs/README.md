# roshanavi — ドキュメント索引

各文書が何で、いつ読むかを 1 行ずつ示す。まず [overview/vision.md](overview/vision.md) を読み、あとは必要なページだけ読めばよい。

## guide — 利用ガイド

- [guide/README.md](guide/README.md): 使う人向けの説明の章の一覧。[guide/wiring.md](guide/wiring.md): 線でつないで作る (つなぎ口から線を引く、つなげない組み合わせ、キーボード)。[guide/user-code.md](guide/user-code.md): 自分のコードを関数・クラスノードにする (置き場所 A/B/C、ひな形、依存 ①②、つまずき、サブモジュール)。[guide/takeover.md](guide/takeover.md): 既存の launch ファイルごと roshanavi で動かす (`--launch`、2 つの動かし方、launch ファイルの変更、強制終了の後始末、削除)。

## overview — 全体像

- [overview/vision.md](overview/vision.md): 出発点・対象ユーザー・ユーザー体験 (ノード単体開発者の 1 日)・ゴールと非ゴール。**最初に読む**。
- [overview/architecture.md](overview/architecture.md): 技術選定、リポジトリ構成、サーバー・計測ノード・トレース解析・子ノード・web のつながり。コードのどこに何があるか知りたいとき。
- [overview/roadmap.md](overview/roadmap.md): フェーズ (P1〜P8) と状態。いま何が済んでいて何が残っているかを知りたいとき (未完了の作業は GitHub Issues)。

## design — 設計 (仕様と決定事項)

- [design/map-and-traffic.md](design/map-and-traffic.md): グラフ、診断 (QoS 互換など)、トラフィック統計、レートの意味 (送信者・受信者ごとの行を含む)。地図や Hz の数字を変えるとき。
- [design/measurement.md](design/measurement.md): C++ 計測ノード、詳細計測モード (トレース計測)、ベンチマーク、規模と負荷の限界・重いデータを計測に入れたときの限界 (実測)、トラブルシューティング (CPU が高い: MultiThreadedExecutor の空回り)。計測の仕組みや負荷を調べるとき。
- [design/input-and-media.md](design/input-and-media.md): 注入ジョブ、式 (`${...}`)、メディアファイル・ブラウザ入力・録画・ビューア、送信のペース。データを流す機能を触るとき。
- [design/nodes.md](design/nodes.md): 入力ノード (恒久ダミー)・変換ノード・関数ノード・クラスノード・同梱サンプルノード、中継パイプライン (source / relay / sink と生成器)、データの種類。ノードを自作する機能を触るとき。
- [design/user-code.md](design/user-code.md): 関数・クラスノードのコードの置き場所 (A ワークスペース / B 登録した場所 / C インストール済み)、見つからない理由、「ひな形を作る」、依存ライブラリ (rosdep / venv)、どの Python で動くか。利用者のコードの入口を触るとき。
- [design/launcher.md](design/launcher.md): Launcher、ノード ⇄ プロセスの対応づけ、プロジェクトファイルと切り替え、パラメータ、lifecycle、launch の取り込み、ノード一覧。ノードの起動・管理を触るとき。
- [design/integration.md](design/integration.md): 既存の launch ファイルを引き取って起動する (`--launch`): ノードごと / 全体、残りの部分、引き継ぐもの・元どおりにならないもの、冪等な起動し直し、launch ファイルの変更の検出と取り込み直し。既存プロジェクトへの組み込みを触るとき。
- [design/ui.md](design/ui.md): タブ構成、ライブ通信マップ、右クリックメニュー、各パネルの実装メモ、アプリ内チュートリアル、UI の実行・E2E の方法。画面を触るとき。
- [design/api.md](design/api.md): REST / WebSocket の一覧、既定ポート、入力検証、Host / Origin / Content-Type の検査。API を足すとき。
- [design/security.md](design/security.md): セキュリティ上の判断の索引 (ネットワーク・式・パス・サブプロセス・他人のプロセス)。新しい機能を足す前の確認に。
- [design/scenarios.md](design/scenarios.md): シナリオ (P6): ファイルの形式・判定のルール・CLI / Python API・サーバー・記録モード。
- [design/resources.md](design/resources.md): リソース監視 (Lv1, 同じ PC): ノード ⇄ プロセスの対応づけ、CPU・メモリ・ディスク・ネットワーク・GPU、メモリリークと UDP 受信バッファ溢れの診断、シナリオの `resources` / `mem_growth`。負荷やリークを調べる機能を触るとき。
- [design/wiring.md](design/wiring.md): 地図の上での配線 (つなぎ口、ドラッグとキーボードでつなぐ、種類の互換性の規則、つながっていない口、反映は再起動)、用語集 (ROS の用語 → 平易な言葉) と言葉の総点検、pub/sub の 1 枚絵。地図でつなぐ機能や画面の言葉を触るとき。

## planned — 未実装の設計

- [planned/remote-access.md](planned/remote-access.md): 別マシンからのアクセス (デバイスのペアリング) の設計。
- [planned/integration.md](planned/integration.md): 既存プロジェクトへの組み込み (ネイティブのインストール、サイドカーなど。launch の引き取りは実装済みで design/integration.md)。

## project — 開発の運用

- [project/testing.md](project/testing.md): テスト方針・実行コマンド・テスト項目と状態 (✅ 🟡 ⬜ 👀)。テストを足す・動かすとき。
- [project/dependencies.md](project/dependencies.md): 依存関係 (用途・ライセンス・rosdep キー)。依存を足す・変えるとき。
- [project/distribution.md](project/distribution.md): 配布とインストールの設計 (予定)。パッケージ化を考えるとき。

## images — スクリーンショット

- [images/](images/): UI のスクリーンショット。E2E テスト (`web/e2e/*.spec.ts`) が書き出し、設計文書から参照する。
