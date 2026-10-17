# roshanavi — テスト項目一覧

状態の凡例: ✅ 自動テスト済み / 🟡 実装済み・自動テスト未整備 / ⬜ 未実装 (計画) / 👀 手動確認

自動テストは `docker compose --profile test run --rm test` で実行する。
「動的変化」系は、テスト内で rclpy ノードやプロセスを起動・停止して検証する。

## A. グラフ・トピックの動的変化

| ID | 項目 | 期待結果 | 状態 |
|---|---|---|---|
| A-01 | 起動時に既存ノード・トピックを検出 | /api/graph に全ノード・トピックと pub/sub エッジが出る | ✅ |
| A-02 | 実行中にトピックを **追加** (新 publisher 起動) | 1〜2 秒以内にグラフと traffic に出現し、統計が始まる | 🟡 |
| A-03 | 実行中にトピックを **削除** (publisher / subscriber 全停止) | グラフから消え、traffic の購読が解除される | 🟡 |
| A-04 | 大量のトピックを一括追加・削除 (例: 200 本を作成→破棄) | 取りこぼしなく反映され、購読数がリークしない | ⬜ |
| A-05 | 同名トピックに publisher を追加・削除 (1→3→0) | エッジ数が追従し、Hz が合算・減少する | ⬜ |
| A-06 | ノードの再起動 (同名で落として再起動) | 重複ノードが残らず、統計が継続する | ⬜ |
| A-07 | 同名トピックで型が異なる publisher | `unsupported` として表示し、クラッシュしない | 🟡 |
| A-08 | publisher の QoS が RELIABLE→BEST_EFFORT に変化 | 互換 QoS で再購読し、計測が継続する | 🟡 |
| A-09 | 名前空間・リマップされたトピック (`/robot1/cmd_vel`) | 正しい名前で表示される | ⬜ |
| A-10 | 隠しトピック (`_action/*`, `/rosout`, `/parameter_events`) | 畳み表示・非表示切替が効く | 🟡 |
| A-11 | roshanavi 自身のノード・購読 | 既定で除外し、`--show-self` で表示する | ✅ |
| A-12 | 別コンテナ・別プロセスのノード (同一 DOMAIN_ID) | 検出される / 異なる DOMAIN_ID は見えない | 👀 |
| A-13 | グラフの変化検知 | 変化がなければ WS でグラフを再送しない (hash) | ✅ |
| A-14 | QoS 互換性 (reliability / durability / deadline / liveliness / lease) | 非互換の pub–sub 組が理由付きで `qos_incompatible` に出る | ✅ (unit) |
| A-15 | 診断 (片側のみ・名前の取り違え・型の不一致) | 隠しトピックを除き、決定的な順で警告が出る | ✅ (unit) |
| A-16 | 注入ジョブの仮想ノード | 実行中ジョブが `dummy:<id>` (role dummy) としてグラフに出て、終了で消える | ✅ |

## B. トラフィック計測

| ID | 項目 | 期待結果 | 状態 |
|---|---|---|---|
| B-01 | 10 Hz の publisher | hz ≈ 10 (±5%) | ✅ |
| B-02 | BEST_EFFORT の publisher | 購読でき、hz が出る | ✅ |
| B-03 | 送信時刻ベースの Hz (`hz_basis=source`) | 受信側が遅れても publish 側の周期を出す | ⬜ (P1.5) |
| B-04 | 取りこぼし検出 (連番の欠け) | `dropped` / `drop_ratio` が出る。RMW 非対応なら null | ⬜ (P1.5) |
| B-05 | publisher 停止後の扱い | `last_seen` で停止を判別でき、UI で停止表示 | 🟡 |
| B-06 | 高頻度トピック (1 kHz) | 計測が破綻せず、CPU 負荷が許容範囲に収まる | ⬜ |
| B-07 | 巨大メッセージ (画像 1080p 30 Hz, 点群) | 既定では非監視。有効化すると帯域が出る | ⬜ (P1.5) |
| B-08 | 観測者効果 | roshanavi の有無で対象ノードのレイテンシ・CPU に有意差がない (heavy 除外時) | 👀 |
| B-09 | 統計計算の決定性 | 時刻を注入した unit test で hz / 帯域 / ジッタが一致する | ✅ |
| B-10 | 長時間稼働 (24 h) | メモリが増え続けない (リングバッファ上限) | ⬜ |

## C. ダミー注入

| ID | 項目 | 期待結果 | 状態 |
|---|---|---|---|
| C-01 | once | 1 件届く。subscriber が後から match しても失われない | ✅ |
| C-02 | periodic + count | 指定件数を指定レートで送り、`done` になる | ✅ |
| C-03 | 停止 | DELETE で即停止し、publisher を破棄する | ✅ |
| C-04 | 式 `${i}` `${sin(t)}` `${randint(0,9)}` | 毎回評価され、型が保たれる | ✅ |
| C-05 | JSONL stream / loop | 行順に送信し、loop で繰り返す | ✅ (loop 🟡) |
| C-06 | CSV stream (`a.b.c` ヘッダ) | ネストしたフィールドに入る | ✅ |
| C-07 | bag 再生 (rate / loop / topics) | `ros2 bag play` が起動し、停止で終了する | 🟡 (fixture bag 未作成) |
| C-08 | 任意型・カスタム msg のテンプレ生成 | 既定値の dict が返る | ✅ |
| C-09 | 不正 payload (型違い・存在しないフィールド) | フィールドパス付きエラーで 400 | ✅ |
| C-10 | `header: auto` / `stamp: now` | 現在時刻が入る | 🟡 |
| C-11 | 同時に多数ジョブ (50 本) | 上限超過は 429、既存ジョブに影響しない | 🟡 |
| C-12 | QoS 指定 (best_effort / transient_local) | 指定どおりに publish され、後から来た subscriber が受け取れる (latched) | ⬜ |

## D. シナリオ (P3)

| ID | 項目 | 期待結果 | 状態 |
|---|---|---|---|
| D-01 | inject → expect pass | pass、JUnit XML 出力、exit 0 | ⬜ |
| D-02 | expect が timeout | fail、exit 1、失敗理由 (受信件数・最後の値) を出す | ⬜ |
| D-03 | inject 直後に出る応答を取りこぼさない | 事前購読によって pass する | ⬜ |
| D-04 | where 演算子 (eq/range/approx/regex/exists/配列添字) | 各演算子が正しく判定する | ⬜ |
| D-05 | expect_rate | 範囲内なら pass、外なら fail | ⬜ |
| D-06 | setup プロセス起動・wait_for_node・後片付け | 成功・失敗どちらでもプロセスが残らない | ⬜ |
| D-07 | 不正 YAML / 未知キー | 行番号付きのスキーマエラー | ⬜ |
| D-08 | ディレクトリ一括実行 | 全件を実行し、集計を JUnit に出す | ⬜ |

## E. API・セキュリティ

| ID | 項目 | 期待結果 | 状態 |
|---|---|---|---|
| E-01 | 式評価器の拒否ケース (属性・添字・lambda・`__import__`) | すべて拒否 | ✅ |
| E-02 | DoS 上限 (巨大べき乗・文字列乗算・深いネスト) | 計算前に拒否 | ✅ |
| E-03 | パストラバーサル (`../`, 絶対パス, 外向き symlink) | `forbidden_path` | ✅ |
| E-04 | 不正な Host ヘッダ (DNS rebinding) | 403 | ⬜ (P1.5) |
| E-05 | 外部 Origin からの WebSocket 接続 | 1008 で拒否 | ⬜ (P1.5) |
| E-06 | text/plain の POST (CSRF) | 415 | ⬜ (P1.5) |
| E-07 | 既定の bind が 127.0.0.1 | 外部 IF から到達できない | 👀 |

## F. UI (P2)

| ID | 項目 | 期待結果 | 状態 |
|---|---|---|---|
| F-01 | トピックの追加・削除がグラフにアニメーション反映 | レイアウトが崩れない | 🟡 (差分パッチは unit、ダミーノード出現は E2E、見た目は 👀) |
| F-02 | 200 ノード規模のグラフ | 操作が 30 fps 以上 | ✅ (`e2e/perf.spec.ts`: 180 要素 + 粒で約 60 fps, headless) |
| F-03 | Inject フォームから全 mode を実行 | API と同等に動く | 🟡 (once/periodic は E2E、stream/bag はリクエスト生成の unit のみ) |
| F-04 | WS の切断・再接続 | 自動で再接続し、状態を復元する | 🟡 (バックオフは unit、実接続断は 👀) |
| F-05 | 主要フロー E2E (Playwright) | グラフ表示 → 注入 → エコーで受信を確認 | ✅ (`docker compose --profile e2e run --rm e2e`) |
| F-06 | 診断パネル | 平易な日本語で表示され、クリックで対象にフォーカスする | ✅ (文章化は unit、クリックは E2E) |
| F-07 | 一時停止・フィルタ・内部トピック非表示 | 表示が固定 / 絞り込まれる | 🟡 (フィルタは unit、操作は 👀) |
| F-08 | ライト / ダーク表示 | OS 設定に追従する | 👀 |

## G. 互換性

| ID | 項目 | 期待結果 | 状態 |
|---|---|---|---|
| G-01 | rmw_fastrtps_cpp (既定) | 全テストが pass | ✅ |
| G-02 | rmw_cyclonedds_cpp | 全テストが pass (連番非対応時は dropped=null) | ⬜ |
| G-03 | rmw_zenoh_cpp | 基本機能が動く | ⬜ |

## H. Launcher・プロジェクト・恒久ダミー (P3)

| ID | 項目 | 期待結果 | 状態 |
|---|---|---|---|
| H-01 | ワークスペース走査 (demo_nodes_cpp / demo_nodes_py / 自パッケージ) | 実行ファイル・launch ファイルが出る。自パッケージは `workspace` で先頭、`source_dir` 付き | ✅ (`test_launcher_discovery.py`) |
| H-02 | 分離・merged の install、未ビルド・未 source・`COLCON_IGNORE`、再走査 | それぞれ正しく区別され、refresh まではキャッシュ | ✅ |
| H-03 | 未 source パッケージの環境 (colcon の .dsv) | `AMENT_PREFIX_PATH` / `PYTHONPATH` が子プロセスに入り、`ros2 run` / `ros2 launch` できる | ✅ (unit + `test_launcher_build.py`) |
| H-04 | 引数の検証: `;`・`$( )`・`--ros-args`/`--`/`--params-file`/`--prefix`・`__node:=`・制御文字・不正なノード名/名前空間/リマップ | すべて拒否 (400/422)。値はシェルを通らず argv の 1 要素 | ✅ (`test_launcher_validate.py`, API) |
| H-05 | パスの包含 (パラメータファイル・書き出し先: `..`, 絶対パス, 外向き symlink) | `forbidden_path` | ✅ |
| H-06 | 停止のエスカレーション (SIGINT 無視 → SIGTERM、両方無視 → SIGKILL) | 指定時間で次の段に進み、終了コードが -15 / -9 | ✅ (`test_launcher_process.py`) |
| H-07 | プロセスグループごとの停止 (孫プロセス) | 子孫がすべて終了する | ✅ |
| H-08 | サーバー終了時に孤児を残さない (SIGTERM / SIGINT / SIGHUP、run・launch・dummy) | 全ターゲットのプロセスが消える | ✅ (`test_launcher_shutdown.py`) |
| H-09 | 状態 (starting / running / exited / crashed / stopped)、再起動回数、自動再起動とバックオフ | 期待どおり遷移し、ユーザー停止後は再起動しない | ✅ |
| H-10 | run ターゲット (名前なし) | `/talker` が heuristic で対応づき、role `mine` | ✅ (`test_launcher_ros.py`) |
| H-11 | run ターゲット (名前・名前空間・リマップ付き) | exact で対応づき、pid は実行ファイル側。リマップ先のトピックに出る | ✅ |
| H-12 | launch ターゲット (`talker_listener_launch.py`) | 2 ノードとも同じターゲットに対応づく (heuristic) | ✅ |
| H-13 | launch ファイルが `Node(name=…)` を使う場合 | exact で対応づく | ✅ (fixture パッケージ) |
| H-14 | ログ (stream タグ、リングバッファ 5000 行、`/ws/logs/{id}`) | 起動コマンド・stdout/stderr・終了コードが流れる | ✅ |
| H-15 | ビルドボタン成功 (fixture ament_python パッケージ) | `succeeded`、`needs_resource`、走査に反映、実行中ターゲットを再起動 | ✅ (`test_launcher_build.py`) |
| H-16 | ビルド失敗 (壊れた setup.py: colcon は 0 で終わる) | `failed`、最初のエラー行を返す | ✅ |
| H-17 | C++ のコンパイルエラーの抽出 | `file:line:col: error:` から先頭 12 行 | ✅ (unit) / 実パッケージは ⬜ |
| H-18 | プロジェクトファイルの往復 (キー順・空値省略・2 回保存で同一) | 同じ内容・同じテキスト | ✅ (`test_project.py`) |
| H-19 | プロジェクトファイルの検証 (未知キー・型・重複 ID・YAML 構文) | パス付き / 行番号付きのエラー | ✅ |
| H-20 | 原子的な保存、`dirty` 表示、REST GET/PUT/save | 一時ファイルが残らず、保存後は `dirty:false` | ✅ |
| H-21 | 古いプロジェクト (存在しないパッケージ) | `invalid` 状態で一覧に残る | ✅ |
| H-22 | autostart / `--no-autostart` | autostart のものだけ起動し、無効時は何も起動しない | ✅ |
| H-23 | 恒久ダミー実行ファイル | 自分のノード名で publish する。設定エラーは終了コード 2 | ✅ (`test_dummy.py`) |
| H-24 | 注入ジョブ → 恒久ダミー | 同じ内容で起動、元ジョブは停止、地図で role `dummy` (exact) | ✅ |
| H-25 | launch ファイルへの書き出し | `ros2 launch <file>` だけで動き、メッセージが届く | ✅ |
| H-26 | Launcher の REST / WS がセキュリティミドルウェアを通る | 不正 Origin は 1008、text/plain は 415、不正 Host は 403 | ✅ |
| H-27 | UI: Launcher から talker を起動 → 地図で「自分のノード」→ 停止 | E2E で確認 | ✅ (`e2e/launcher.spec.ts`) |
| H-28 | UI: 依存ノード・恒久ダミーの色、右ペインの対応づけ表示とログへのリンク | E2E で確認 | ✅ |
| H-29 | UI: フォームの検証・パッケージ検索・ログの絞り込み | 純ロジックの unit | ✅ (vitest) |
| H-30 | composable container | コンテナ単位で対応づく (ノード単位にはならない) | ⬜ |
| H-31 | 別コンテナ / 別 PC のノード | 対応づけない (`other`) | 👀 |
