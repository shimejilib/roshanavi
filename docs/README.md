# roshanavi — ドキュメント索引

各文書が何で、いつ読むかを 1 行ずつ示す。まず [overview/vision.md](overview/vision.md) を読み、あとは必要なページだけ読めばよい。

## overview — 全体像

- [overview/vision.md](overview/vision.md): 出発点・対象ユーザー・ユーザー体験 (ノード単体開発者の 1 日)・ゴールと非ゴール。**最初に読む**。
- [overview/architecture.md](overview/architecture.md): 技術選定、リポジトリ構成、サーバー・計測ノード・トレース解析・子ノード・web のつながり。コードのどこに何があるか知りたいとき。
- [overview/roadmap.md](overview/roadmap.md): フェーズ (P1〜P7) と状態。いま何が済んでいて何が残っているかを知りたいとき (未完了の作業は GitHub Issues)。

## design — 設計 (仕様と決定事項)

- [design/map-and-traffic.md](design/map-and-traffic.md): グラフ、診断 (QoS 互換など)、トラフィック統計、レートの意味 (送信者・受信者ごとの行を含む)。地図や Hz の数字を変えるとき。
- [design/measurement.md](design/measurement.md): C++ 計測ノード、詳細計測モード (トレース計測)、ベンチマーク、トラブルシューティング (CPU が高い: MultiThreadedExecutor の空回り)。計測の仕組みや負荷を調べるとき。
- [design/input-and-media.md](design/input-and-media.md): 注入ジョブ、式 (`${...}`)、メディアファイル・ブラウザ入力・録画・ビューア、送信のペース。データを流す機能を触るとき。
- [design/nodes.md](design/nodes.md): 入力ノード (恒久ダミー)・変換ノード・関数ノード・同梱サンプルノード、データの種類。ノードを自作する機能を触るとき。
- [design/launcher.md](design/launcher.md): Launcher、ノード ⇄ プロセスの対応づけ、プロジェクトファイルと切り替え、パラメータ、lifecycle、launch の取り込み、ノード一覧。ノードの起動・管理を触るとき。
- [design/ui.md](design/ui.md): タブ構成、ライブ通信マップ、右クリックメニュー、各パネルの実装メモ、アプリ内チュートリアル、UI の実行・E2E の方法。画面を触るとき。
- [design/api.md](design/api.md): REST / WebSocket の一覧、既定ポート、入力検証、Host / Origin / Content-Type の検査。API を足すとき。
- [design/security.md](design/security.md): セキュリティ上の判断の索引 (ネットワーク・式・パス・サブプロセス・他人のプロセス)。新しい機能を足す前の確認に。
- [design/scenarios.md](design/scenarios.md): シナリオ (P6): ファイルの形式・判定のルール・CLI / Python API・サーバー・記録モード。

## planned — 未実装の設計

- [planned/resources.md](planned/resources.md): CPU・メモリ・ディスク・ネットワークの監視の設計メモ (優先度低)。
- [planned/remote-access.md](planned/remote-access.md): 別マシンからのアクセス (デバイスのペアリング) の設計。

## project — 開発の運用

- [project/testing.md](project/testing.md): テスト方針・実行コマンド・テスト項目と状態 (✅ 🟡 ⬜ 👀)。テストを足す・動かすとき。
- [project/dependencies.md](project/dependencies.md): 依存関係 (用途・ライセンス・rosdep キー)。依存を足す・変えるとき。
- [project/distribution.md](project/distribution.md): 配布とインストールの設計 (予定)。パッケージ化を考えるとき。

## images — スクリーンショット

- [images/](images/): UI のスクリーンショット。E2E テスト (`web/e2e/*.spec.ts`) が書き出し、設計文書から参照する。
