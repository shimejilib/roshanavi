# roshanavi — ロードマップ

> 未完了の作業・要望・既知の問題は GitHub Issues ([shimejilib/roshanavi](https://github.com/shimejilib/roshanavi/issues)) で管理している。この文書にはフェーズごとの大きな区切りと状態を書く。

## フェーズ
1. ✅ P1 バックエンド核 + Docker (graph / traffic / msgutil / expr / injector / echo / server + テスト)
2. ✅ P1.5 セキュリティ強化 (Host/Origin/Content-Type)、MessageInfo による Hz・取りこぼし、heavy 型の opt-in
3. ✅ P2 Web UI 基盤 + ライブ通信マップ ([ui.md#ライブ通信マップ](../design/ui.md#ライブ通信マップ-graph-タブ), 診断を含む) + Traffic + Inject
4. ✅ P3 Launcher ([vision.md#主要ユーザー体験](vision.md#主要ユーザー体験-ノード単体開発者の-1-日) の 3, [launcher.md#Launcher](../design/launcher.md#launcher-p3)) + プロジェクトファイル + ビルドボタン + 恒久ダミーノード ([nodes.md#恒久ダミーノード](../design/nodes.md#恒久ダミーノード-p3))
5. ✅ P4 メディア注入 ([input-and-media.md#メディアファイル注入](../design/input-and-media.md#メディアファイル注入)、[input-and-media.md#メディア](../design/input-and-media.md#メディア-アダプタファイルソースブラウザ入力ビューア-p4)) + ブラウザ入力 + 録画 ([input-and-media.md#録画](../design/input-and-media.md#録画-p4)) + 画像ビューア・音声の波形と再生
5a. ✅ P4.5a デモ体験・入力ノード・ランチャーの改善・右クリックメニュー・パラメータ・ノードの入出力・更新タイミング ([launcher.md#ノードのパラメータと型の定義](../design/launcher.md#ノードのパラメータと型の定義-p45a)、[launcher.md#デモ構成](../design/launcher.md#デモ構成-p45a)、[ui.md#実装メモ (P4.5a: デモ体験・ランチャー・地図の操作)](../design/ui.md#実装メモ-p45a-デモ体験ランチャー地図の操作))
5b. ✅ P4.5b ノード一覧タブ・launch の分解取り込み・lifecycle・送受信ごとのトラフィック ([launcher.md#lifecycle ノード](../design/launcher.md#lifecycle-ノード-p45b)、[launcher.md#launch の分解取り込み](../design/launcher.md#launch-の分解取り込み-p45b)、[map-and-traffic.md#送受信ごとのトラフィック・遅いトピック](../design/map-and-traffic.md#送受信ごとのトラフィック遅いトピック-p45b)、[ui.md#実装メモ (P4.5b: ノード一覧・lifecycle・launch の取り込み)](../design/ui.md#実装メモ-p45b-ノード一覧lifecyclelaunch-の取り込み)、[ui.md#トラフィックの送受信ごとの表示](../design/ui.md#トラフィックの送受信ごとの表示-p45b))
5c. ✅ P4.6 C++ 計測ノード (`roshanavi_msgs` / `roshanavi_probe`): 送信ノードごとの実測、Python の計測は代替経路に ([measurement.md#C++ 計測ノード](../design/measurement.md#c-計測ノード-roshanavi_probe-p46))
5d. ✅ P4.7 詳細計測モード (LTTng のトレース): 受信・処理の実測、処理時間、処理が追いついていない診断 ([measurement.md#詳細計測モード](../design/measurement.md#詳細計測モード-トレース計測-p47))
6. ✅ P5 サンプルノード (`roshanavi_examples`, [nodes.md#同梱サンプルノード](../design/nodes.md#同梱サンプルノード-roshanavi_examples-p5))・変換ノード ([nodes.md#変換ノード](../design/nodes.md#変換ノード-p5))・パーセプションデモとプロジェクトの切り替え ([launcher.md#プロジェクトファイル](../design/launcher.md#プロジェクトファイル-p3)、[launcher.md#デモ構成](../design/launcher.md#デモ構成-p45a))
6a. ✅ P5.5 初心者向け: データの種類と詳細設定モード ([nodes.md#データの種類](../design/nodes.md#データの種類-ros-のメッセージ型を意識させないp55))・関数ノード ([nodes.md#関数ノード](../design/nodes.md#関数ノード-ふつうの関数をそのままノードにするp55))
6b. ✅ クラスノード (#43): 状態を持つ Python クラスをそのままノードに (`__init__` の引数 = パラメータ、メソッドをトピックや操作ボタンに、単一スレッド、close、ホットリロードでの状態の扱い)、シナリオの `call`、rclpy / lifecycle ノードへのコード書き出し ([nodes.md#クラスノード](../design/nodes.md#クラスノード-状態を持つ処理をそのままノードにする))
7. ✅ P6 シナリオ: runner / CLI / JUnit / Python API (launch_pytest) / 記録モード / Scenarios タブ ([scenarios.md](../design/scenarios.md)、[ui.md#実装メモ (P6: シナリオ)](../design/ui.md#実装メモ-p6-シナリオ))
8. P7 監査、README (サービス・アクションは今後対応予定と明記)、デモ GIF
9. ✅ P8 リソース監視 Lv1 (#32): 同じ PC の CPU・メモリ・ディスク・ネットワーク・GPU、ノード ⇄ プロセスの対応づけ、メモリリークと UDP 受信バッファ溢れの診断、地図のバッジ・リソースタブ、シナリオの `resources` / `mem_growth` ([resources.md](../design/resources.md))。Lv2 (複数 PC・コンテナ) は将来の課題
