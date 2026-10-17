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
| B-03 | 送信時刻ベースの Hz (`hz_basis=source`) | 受信側が遅れても publish 側の周期を出す。落ちた分も連番で送信数に数える | ✅ (Python: `test_traffic_rate.py`, `test_integration_ros.py`。C++: gtest `test_stats.cpp`、`test_probe_ros.py`) |
| B-04 | 取りこぼし検出 (連番の欠け) | `dropped` / `drop_ratio` が出る。RMW 非対応なら null | ✅ (欠番・publisher ごと・連番非対応: `test_traffic_rate.py` と gtest。Fast DDS で 0 件を確認: `test_probe_ros.py`。Cyclone DDS は連番非対応で null: 👀) |
| B-05 | publisher 停止後の扱い | `last_seen` で停止を判別でき、UI で停止表示 | 🟡 |
| B-06 | 高頻度トピック (1 kHz) | 計測が破綻せず、CPU 負荷が許容範囲に収まる | ⬜ |
| B-07 | 巨大メッセージ (画像 1080p 30 Hz, 点群) | 既定では非監視。有効化すると帯域が出る | ⬜ (P1.5) |
| B-08 | 観測者効果 | roshanavi の有無で対象ノードのレイテンシ・CPU に有意差がない (heavy 除外時) | 👀 |
| B-09 | 統計計算の決定性 | 時刻を注入した unit test で hz / 帯域 / ジッタが一致する | ✅ |
| B-10 | 長時間稼働 (24 h) | メモリが増え続けない (リングバッファ上限) | ⬜ |
| B-11 | 計測ノード: 1 トピックに 2 つの送信ノード (5 Hz と 2 Hz) | 送信ノードごとに 5 / 2 Hz (±5%) で `basis: measured`、トピック合計 7 Hz、`gid_resolution: matched` | ✅ (`test_probe_ros.py`) |
| B-12 | 計測ノードの統計 (gtest) | 欠番、複数 publisher の合計、連番非対応で null、送信時刻が無ければ受信側、計算期間の選択、遅いトピックの延長・`too_few`、止まったら 0、publisher ごとの値と停止、リングバッファの上限 | ✅ (`roshanavi_probe/test/test_stats.cpp`) |
| B-13 | 計測ノードが使えないとき | `--probe off` / 未ビルド → Python の計測 (`measurement: python`、理由付き)。繰り返し異常終了 → 5 回で Python に切り替え | ✅ (`test_probe_unit.py`, `test_probe_ros.py`) |
| B-14 | 計測ノードの異常終了 | 再起動され (1 秒後〜)、TRANSIENT_LOCAL の設定を受け取って計測を再開する | ✅ (`test_probe_ros.py`) |
| B-15 | 自分用のトピック | `/roshanavi/_probe/*` と計測ノードは地図・診断・トラフィックに出ない | ✅ (`test_probe_unit.py`, `test_probe_ros.py`) |
| B-16 | gid がグラフと対応しない RMW | `resolved: false` ならトピック合計の分割 (`rates.py`) にフォールバック、UI に案内 | ✅ (判定は `test_probe_unit.py` / `measurement.test.ts`)、Cyclone DDS の実機は 👀 (gid 不一致・連番非対応を確認) |
| B-17 | 送信ノードごとの値 (unit) | 送っていない送信者は 0 Hz の実測、注入ジョブは `exact` のまま、件数未確定のジョブは自分のノードの実測、受信者は実測値の和 | ✅ (`test_probe_unit.py`) |
| B-18 | 計測ノードの負荷 | 10 トピック × 100 Hz、画像 720p 30 Hz で計測ノード + サーバーの CPU が Python の計測より小さい | 👀 (DESIGN §4.3.1 の表: 9.5% 対 32.3%、11.8% 対 17.4%) |
| B-19 | 止まったトピックの Hz 表示 (vitest) | hz 0 / `stale` のとき「(受信時刻で概算)」を付けない | ✅ (`timing.test.ts`) |
| B-20 | 計測の経路の表示・実測バッジ (vitest) | 「計測: C++ 計測ノード (CPU x%)」、再起動中・RMW の制限・Python の理由、`measured` は「実測」 | ✅ (`traffic/measurement.test.ts`) |
| B-21 | E2E: talker + 1 Hz の入力ノードが /chatter | 地図の talker の辺が約 1 Hz で「推定」が付かない。トラフィックタブで talker が約 1 Hz の「実測」、入力ノードが約 1 Hz、ツールバーに「C++ 計測ノード」 | ✅ (`e2e/smoke.spec.ts`) |

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
| F-05 | 主要フロー E2E (Playwright) | グラフ表示 → 注入 → エコーで受信を確認 | ✅ (`scripts/e2e.sh`: 隔離した lab-e2e / demo-e2e に対して実行。利用中の lab と ./data には触れず、前後の sha256 で確認) |
| F-06 | 診断パネル | 平易な日本語で表示され、クリックで対象にフォーカスする | ✅ (文章化は unit、クリックは E2E) |
| F-07 | 一時停止・フィルタ・内部トピック非表示 | 表示が固定 / 絞り込まれる | 🟡 (フィルタは unit、操作は 👀) |
| F-08 | ライト / ダーク表示 | OS 設定に追従する | 👀 |
| F-09 | 送信元ごとの Hz (talker + 注入ジョブが同じトピック) | 注入ジョブのエッジは実送信数。talker は計測ノードの経路では送信ノードごとの実測 (B-11, B-21)、Python の経路では「合計 − 注入」で「推定」。送信元 2 以上ならトピックに合計と送信元数 | ✅ (分配は pytest `test_rates.py` / `test_probe_unit.py`、表示は vitest、talker+ダミーは E2E) |

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
| H-32 | 地図の右クリック / 右ペインから停止・再起動・起動 | roshanavi が起動したノードだけ操作でき、停止前に同時に止まるノードを列挙して確認する | ✅ (可否と確認文は vitest、右クリック → 停止 → 確認 → 地図から消える は E2E) |
| H-33 | roshanavi が起動していないノード | 停止ボタンは無効で、理由を表示する (シグナルを送らない) | ✅ (vitest + E2E) |

## I. メディア・ブラウザ入力・録画 (P4)

素材 (testsrc の動画、sine の wav/mp3/flac、単色の PNG/JPEG) はテスト中に ffmpeg で作る (バイナリはコミットしない)。E2E の動画はブラウザの MediaRecorder で作る。

| ID | 項目 | 期待結果 | 状態 |
|---|---|---|---|
| I-01 | アダプタのフィールド対応 (Image / CompressedImage / AudioData / AudioDataStamped / Int16・UInt8・Float32MultiArray) | 値・header・layout が正しく、表示用に元へ戻せる | ✅ (`test_media_adapters.py`) |
| I-02 | 画像のエンコーディング (rgb8 / bgr8 / mono8、JPEG → Image) | 画素の並びと輝度が正しい | ✅ |
| I-03 | CameraInfo (既定・キャリブレーション YAML・大きさに合わせた補正・送り先) | 画像と同じ stamp で兄弟トピック `camera_info` に届く | ✅ |
| I-04 | AudioInfo (名前は audio_capture と同じ兄弟 `audio_info`、変更可) | sample_rate・channels・S16LE・wave が入る | ✅ |
| I-05 | 型の自動判定 (subscriber 優先 → publisher)・型なし・対応外・種類違い | 判定できる / 平易なエラー (bag・録画を案内) | ✅ |
| I-06 | アダプタのプラグイン (entry point) と、型パッケージが無いときの無効化 | テスト内のアダプタが登録される / 壊れたプラグインは無視 | ✅ |
| I-07 | 動画のフレーム分解 (fps・区間・リサイズ・loop、raw / JPEG / PNG の区切り) | 枚数・大きさが正しい | ✅ (`test_media_ffmpeg.py`) |
| I-08 | 音声のサンプルレート・チャンネル変換とチャンク化 | 44.1 kHz stereo mp3 → 16 kHz mono 1024 サンプル、周波数が保たれる | ✅ |
| I-09 | 画像フォルダのスライドショー | 名前順、loop、同じ形式のファイルはそのまま | ✅ |
| I-10 | パス・プロトコルの安全性 | HLS / concat のプレイリスト (http:// や ../ を参照、拡張子の偽装を含む)、`..`・絶対パス・外向き symlink・対応外の拡張子を拒否 | ✅ |
| I-11 | 停止で ffmpeg を終了 | 子プロセスもゾンビも残らない | ✅ |
| I-12 | 実時間ペース (音声、lab + demo 稼働中の実負荷) | AudioDataStamped の stamp 間隔が全て 64 ms ± 20 ms、全体 0.96 s ± 5 %、`late_events` = 0、ペーサースレッドの CPU 時間 < 50 ms (ビジーウェイトなし)。フルスイートを 5 回連続で通す | ✅ (`test_media_job.py`) |
| I-13 | 揺らぎ・欠落の注入 | `dropped` が増え、送信は続く | ✅ |
| I-14 | 動画 → 自動判定した Image + CameraInfo を受信、API の media モード | 全フレームが届く / 不正なオプションは 422 | ✅ |
| I-15 | メディアジョブの恒久ダミーノード化 | 別プロセスのダミーノードが同じ変換で送り続ける | ✅ |
| I-16 | ブラウザ入力 WS: マイク (PCM) → 詰め直し → 受信、カメラ (JPEG) → CompressedImage / Image + CameraInfo | 期待した件数・内容で届く | ✅ (`test_media_capture.py`) |
| I-17 | ブラウザ入力の制限 | 1 トピック 1 つ (409)、不正フレーム・型違い・対応外の型のエラー、fps 上限で間引く、外部 Origin は 1008 | ✅ |
| I-18 | 録画の開始・停止 → 有効な bag (metadata.yaml) → 一覧 → bag モードで再生 → 削除 | すべて成功し、ファイル一覧に bag として出る | ✅ (`test_media_recorder.py`) |
| I-19 | 空き容量の判定 (注入した関数) と自動停止 | 警告・停止の基準どおり。少なくなると `disk_full` で止まる | ✅ |
| I-20 | 録画の入力検証・削除の範囲 | 空 / 不正なトピック・名前、`../` の削除を拒否 | ✅ |
| I-21 | ビューア: 画像の間引き (≤ 10 fps) と縮小 (≤ 640 px)、音声の転送、閉じたら購読解除、対応外の型 | 期待どおり | ✅ (`test_media_viewer.py`) |
| I-22 | UI の純ロジック (PCM のチャンク化・float→int16・レベルメーター・波形・リクエスト生成・録画のプリセット) | unit で一致 | ✅ (vitest) |
| I-23 | E2E: ブラウザのマイク (偽デバイス) → 送信 → 地図にダミーの送信元 → 右ペインに波形 | Playwright で確認 | ✅ (`e2e/media.spec.ts`) |
| I-24 | E2E: 動画ファイルの注入 → 画像ビューアにフレームが出る | Playwright で確認 | ✅ |
| I-25 | E2E: /chatter を録画 → 一覧 → 確認して削除 | Playwright で確認 | ✅ |
| I-26 | E2E: ブラウザのカメラ → Image / CompressedImage | 偽カメラで確認 | 🟡 (WS 経由の JPEG → 送信は pytest、ブラウザ側のカメラ取得は 👀) |
| I-27 | 長時間の動画・音声 (1 時間) のメモリ | 逐次デコードのため増えない | 🟡 (設計上ストリーム。長時間の計測は未実施) |
| I-28 | audio_common_msgs が無い環境 | その型が一覧から消え、配列型で送れる | ✅ (登録の無効化は unit、apt パッケージを外した実行は 👀) |
| I-29 | ペーサー (時計・sleep 差し替え): 絶対時刻、揺らぎの範囲、1 周期ちょうどは遅れ扱いにしない | ドリフトなし、`late_events` / `max_lateness_ms` が正しい | ✅ (`test_media_pacing.py`) |
| I-30 | 遅れた起床の方針 | `shift`: 間隔を保ち再アンカー (まとめ送りなし) / `catch_up`: まとめ送りで元の時刻割りに戻る / `drop`: 遅れた分を捨てる (`late_skipped`) | ✅ |
| I-31 | プレバッファ・先読みキュー (unit) | 指定件数たまるまで待つ / キューが満杯・終端でも待ち続けない / リーダーが止まってもペーサーは詰まらない / 件数と容量の上限 / リーダーの例外は取り出し側で再送出 / close で待機を解除 | ✅ |
| I-32 | デコードの停止 (統合、間隔は ± 20 ms のまま) | 先読みの範囲内の 150 ms 停止は送信に出ない / 最初の停止中は送信を始めない (プレバッファ) | ✅ (`test_media_job.py`) |
| I-33 | 先読みを超える停止 (700 ms) と `late_policy` (3 通り) | `late_events` ≥ 1。`shift` は 1 回・まとめ送りなし、`catch_up` はまとめ送り、`drop` は `sent + late_skipped` = 総数 | ✅ |
| I-34 | Executor がビジーループしない (原因の回帰防止) | トラフィック監視の購読と注入が同じトピックでも、`roshanavi-executor` スレッドの CPU 時間は 0.65 秒の送信中に < 0.15 秒 (以前は 0.3〜0.8 秒) | ✅ (`test_media_job.py` の I-12 のテストに含む) |

## J. デモ体験・地図の操作・パラメータ・更新タイミング (P4.5a)

| ID | 項目 | 期待結果 | 状態 |
|---|---|---|---|
| J-01 | デモ用プロジェクトのコピー (`bootstrap_project`) | ファイルが無いときだけコピー。既存は上書きしない。壊れたテンプレートはコピーしない | ✅ (`test_project.py`) |
| J-02 | 同梱の `examples/demo_project/roshanavi.yaml` | 検証を通り、talker (mine, autostart) / listener (dependency, autostart) | ✅ (`test_project.py`) |
| J-03 | 自動保存 | 起動リスト・入力ノードの追加 / 削除の直後に `dirty: false` でファイルに書かれる | ✅ (`test_project.py`, `test_dummy.py`) |
| J-04 | 読み込みに失敗したプロジェクト | `autosave: false`。自動保存で上書きしない | ✅ |
| J-05 | 入力ノードを 1 リクエストで作成・起動 (`POST /api/dummies?start=true`) | 新しいトピックとノード (role dummy) がグラフに現れ、プロジェクトに保存される | ✅ (`test_dummy.py`) |
| J-06 | 入力ノードの一時停止 (`paused` パラメータ) | true で送信が止まり、false で再開。型違い・終了済みジョブは理由付きで拒否 | ✅ (`test_pause.py`) |
| J-07 | 注入ジョブの一時停止・再開 | periodic は送信数が止まって再開で増える。once は `pausable: false`、存在しないジョブは 404 | ✅ (`test_pause.py`) |
| J-08 | パラメータの値の変換 (unit) | 10 種の型の往復。bool に 1、整数に 1.5 / 2^63、無限大、長すぎる文字列、範囲外のバイトを拒否 | ✅ (`test_params.py`) |
| J-09 | 実ノードのパラメータ (list / describe / get / set) | 一覧に型・値・説明・読み取り専用。変更が反映され、ノードの拒否・読み取り専用・型違いは理由付きのエラー | ✅ (`test_params.py`) |
| J-10 | 応答しないノード | 0.5 秒のタイムアウトで 504 `param_service_unavailable` (サーバーは止まらない) | ✅ |
| J-11 | 外部ノードの変更方針 (REST) | 閲覧は可。変更は `allow_external` なしで 403、ありで反映。グラフに無いノードは 404、roshanavi 自身は 403 | ✅ (`test_params.py`) |
| J-12 | 型の定義 (`ros2 interface show` 相当) | Header に Time の中身が字下げで入る / srv の `---` / 不正な名前は 400、未インストールは 404 | ✅ (`test_interfaces.py`) |
| J-13 | 計算期間 1 / 5 / 10 秒 | 期間ごとに別の平均。10 秒は既定の 5 秒より前のサンプルも使う。`?window=3` は 400、WS は error + close | ✅ (`test_traffic_windows.py`) |
| J-14 | 止まったトピックの Hz | 10 Hz が止まると 1 秒後に 0 (`stale`)、1 Hz は 3 秒後。履歴も 0 | ✅ |
| J-15 | 右クリックメニューの項目 (役割ごと) | 自分 / 依存 / 常駐ダミー / 注入ジョブ / 外部 / トピック / エッジ / 空白で仕様どおり。外部の停止・非ワークスペースのビルドは理由付きで無効 | ✅ (vitest `menuModel.test.ts`) |
| J-16 | 入力ノードのダイアログ → DummySpec | 文字列・式・YAML・メディア・データファイル。`/` の補完、ID の重複回避、編集時の ID 維持、平易なエラー | ✅ (vitest `inputForm.test.ts`) |
| J-17 | ノードの入出力の振り分け | 内部トピックを除く。heavy 型と QoS 不一致を判定。最初の 3 つ (heavy と届かないものを除く) を開く | ✅ (vitest `nodeIO.test.ts`) |
| J-18 | 「入出力だけ表示」「上流・下流だけ表示」 | ノードと直接のトピックだけ / トピックを通る経路だけ | ✅ (vitest `isolate.test.ts`) |
| J-19 | ラベル (最終更新・計算期間・Hz の計測方法)、パラメータ入力、エッジの理由、初回の案内、パッケージの絞り込み | 「最終更新 09:05:07 (2 秒前)」、5 秒超で警告、「直近 5 秒の平均」、受信時刻ベースのときだけ「(受信時刻で概算)」 | ✅ (vitest `timing` / `paramValue` / `edgeInfo` / `guide` / `packages`) |
| J-20 | E2E: 空白の右クリック → 新しいトピックに入力ノードを作る | ノードとトピックが地図に出て、右ペインでエコーが見える。入力ノードのメニューに一時停止・変更 | ✅ (`e2e/ux.spec.ts`) |
| J-21 | E2E: talker のパラメータ / 外部ノード | talker の `use_sim_time` が見えて編集できる。external_talker は停止が無効、パラメータは閲覧のみ | ✅ |
| J-22 | E2E: 型の定義とノードの入出力 | /chatter の定義に `string data`。/listener の「受信しているデータ」に /chatter と Hello World | ✅ |
| J-23 | E2E: 初回の案内 | 起動リストが空なら案内が出て、「試しに talker を起動してみる」で talker が動き、案内が消える | ✅ |
| J-24 | E2E: デモ構成 | talker = 自分、listener = 依存 (lab が起動)、external_talker = その他 (/external/chatter)、ROS 標準パッケージは既定で非表示 | ✅ (`smoke` / `launcher.spec.ts`) |
| J-25 | パラメータの変更を外部ノードで確認ダイアログ経由で行う (UI) | 「変更を許可する」→ 確認 → 編集欄が出る | 🟡 (ロジックは unit、UI 操作は 👀) |
| J-26 | 「ビルドして再起動」を地図から | ワークスペースのパッケージのノードでビルドが始まり、成功後に再起動 | 🟡 (無効化の条件は unit。デモ環境に自分のパッケージが無いため E2E 未整備) |
| J-27 | 最終更新の警告色 (WS の切断) | 5 秒以上フレームが届かないと警告色 | 🟡 (判定は unit、切断の実操作は 👀) |

## K. ノード一覧・lifecycle・launch の分解取り込み・送受信ごとのトラフィック (P4.5b)

| ID | 項目 | 期待結果 | 状態 |
|---|---|---|---|
| K-01 | ノード一覧の集約 (unit) | 実行中のノード ∪ 止まっている起動リスト・常駐ダミー。外部は `control: none` + `reason: external`、設定エラーは `invalid`、注入ジョブは除外、外部より自分の行が先 | ✅ (`test_node_list.py`) |
| K-02 | グループ (unit) | kind launch と 2 ノード以上のプロセスがグループになり、止まった launch もグループを保つ。1 ノードのプロセスはグループにしない | ✅ (`test_node_list.py`) |
| K-03 | 起動元・取り込み元 (unit) | run / launch / dummy (トピック付き) / external、`imported_from` を表示 | ✅ (`test_node_list.py`, vitest `rowText.test.ts`) |
| K-04 | lifecycle ノードの検出 (unit) | `<node>/get_state` が lifecycle_msgs の型のノードだけ。同名でも型が違えば対象外 | ✅ (`test_lifecycle.py`) |
| K-05 | 目標までの遷移 (unit) | unconfigured→active = configure+activate、active→inactive = deactivate、同じ状態や finalized は何もしない、不正な目標は拒否 | ✅ (`test_lifecycle.py`) |
| K-06 | 実 lifecycle ノード (`lifecycle_talker`) | unconfigured → configure → inactive → activate → active → deactivate → cleanup。使えない遷移は 409、shutdown は拒否、状態のキャッシュ | ✅ (`test_lifecycle.py`) |
| K-07 | 応答しない lifecycle ノード | 0.3 秒で 504 `lifecycle_unavailable`、一覧の状態は null (サーバーは止まらない) | ✅ |
| K-08 | lifecycle API の方針 | グラフに `lifecycle: true`。外部は `allow_external` なしで 403、`goal` と `transition` の両方は 400、ありで active。一覧に状態が出る | ✅ (`test_lifecycle.py`) |
| K-09 | パラメータの解決 (unit) | rcl の YAML 規則 (入れ子・相対・`*`・`**`、ワイルドカードが先)、launch の順 (グローバル → dict → ファイル、後勝ち)、scalar と配列などの振り分け、平坦化と復元 | ✅ (`test_launch_params.py`) |
| K-10 | Python の launch の分解 | PushRosNamespace + GroupAction の名前空間、SetRemap + remappings、dict + パラメータファイル + SetParameter、include の中のノード、条件 (if / unless)、引数の変更で結果が変わる | ✅ (`test_launch_import.py`) |
| K-11 | 分解できない部分 | ComposableNodeContainer (中のノード名付き)、ExecuteProcess (**実行されない**: マーカーファイルが作られない)、TimerAction、読めない include がそれぞれ理由コード付きで報告される | ✅ (`test_launch_import.py`) |
| K-12 | XML / YAML の launch | `<push-ros-namespace>`、`<param>`、`<remap>`、`<let>`、`if`、`<executable>` / YAML の `$(var)` と namespace | ✅ (`test_launch_import.py`) |
| K-13 | 必須引数・壊れたファイル・print | 必須引数が無いと評価せず `missing_args`。構文エラーは 422 `launch_eval_failed` (理由付き)。launch ファイルの print は結果を壊さない | ✅ (`test_launch_import.py`) |
| K-14 | 評価のタイムアウト | 60 秒眠る launch ファイルを 2 秒で打ち切り 504 `launch_eval_timeout` (10 秒以内に戻る、プロセスグループごと kill) | ✅ (`test_launch_import.py`) |
| K-15 | 対象ファイルの制限 | ワークスペース外の絶対パス・`..`・外向き symlink・存在しないファイルは拒否。data_dir の下は 403。不正な引数名は拒否 | ✅ (`test_launch_import.py`) |
| K-16 | 取り込み (ノードごと) | 起動リストに `kind: run` で入る。配列パラメータは data_dir の `imported_params/<id>.yaml` に書かれる。2 回目は ID を変える。期限切れの案は 404 | ✅ (`test_launch_import.py`) |
| K-17 | 取り込み (launch 全体) とパッケージの launch | demo_nodes_cpp の talker_listener_launch.py → 2 ノード、全体は `kind: launch`。ワークスペース内の任意のファイルは全体取り込み不可 | ✅ (`test_launch_import.py`) |
| K-18 | 検査に通らないノード | 存在しない実行ファイル・`--ros-args` を含む引数は「取り込めない」(理由コード付き)、取り込みでもエラーとして返る | ✅ (`test_launch_import.py`) |
| K-19 | 取り込み API | `roshanavi/demo_system.launch.py` を robot:=api で解析 → 2 ノード + ExecuteProcess、取り込むとノード一覧に取り込み元付きで出る | ✅ (`test_launch_import.py`) |
| K-20 | 遅いトピックの Hz | 0.5 Hz を 1 秒窓で見ると 10 秒で計算 (`rate_note: extended`, 0.5 Hz)。1 通だけなら `too_few` | ✅ (`test_traffic_windows.py`) |
| K-21 | 受信者ごとの理論値 (unit) | 全送信者が QoS 適合 → トピック全体、一部 → 適合する送信者の和 (分けられなければ null)、適合なし → 0 と `delivered: false`。roshanavi 自身は除外 | ✅ (`test_sub_rates.py`) |
| K-22 | 表の絞り込み・選択・グループ (vitest) | 役割・状態・検索 (AND)、全選択は操作できる行だけ、一部選択、消えた行の選択解除、グループの見出しと一括選択 | ✅ (`nodelist/model.test.ts`) |
| K-23 | 一括操作の計画と確認文 (vitest) | 起動設定ごとに 1 回、一緒に止まるノード (選択外も) を列挙、対象外の理由、lifecycle は activate / deactivate で外部の注意付き | ✅ (`nodelist/bulk.test.ts`) |
| K-24 | lifecycle と取り込みの表示 (vitest) | 遷移の並び・確認文、取り込みの既定の選択・引数の差分・要約・理由文・取り込めない理由 | ✅ (`lifecycleText.test.ts`, `importModel.test.ts`) |
| K-25 | 一時停止中の最終更新・遅いトピックの表示 (vitest) | 一時停止中は警告色にせず「一時停止中 (HH:MM:SS の表示)」。「0.50 Hz (直近 10 秒で計算)」「— (1 秒窓では測定不可)」 | ✅ (`timing.test.ts`) |
| K-26 | 送受信ごとの行・ノード別 (vitest) | 送信 → 受信の順、ノード別のまとめと並び、届いていない・分けられない値、根拠のラベル、すべて展開 | ✅ (`traffic/endpoints.test.ts`, `model.test.ts`) |
| K-27 | E2E: チェックボックスで talker + listener を一括停止・起動 | ↓ キーで次の行へ、確認ダイアログに両方のノード、停止状態の行になり、起動で戻る。外部ノードのチェックは無効で案内が出る | ✅ (`e2e/nodes.spec.ts`) |
| K-28 | E2E: 外部の lifecycle ノード (lc_talker) | configure → activate → deactivate → activate → cleanup。確認ダイアログに外部の注意 | ✅ (`e2e/nodes.spec.ts`) |
| K-29 | E2E: launch の取り込み | roshanavi / demo_system.launch.py を解析 → 2 ノードと ExecuteProcess → 取り込むと一覧に取り込み元付きで出る | ✅ (`e2e/nodes.spec.ts`) |
| K-30 | E2E: トラフィックの展開とノード別 | /chatter を展開して talker (送信・実測) と listener (受信・理論値)、ノード別に切り替えても同じ | ✅ (`e2e/smoke.spec.ts`) |
| K-31 | 一緒に止まる composable container のノード (実機) | container 内の複数ノードが 1 グループになり、確認ダイアログに全ノード | 🟡 (集約・確認文は unit。デモに container が無いため E2E 未整備) |
| K-32 | 地図の右クリック・右ペインからの lifecycle | lifecycle ノードにだけ項目が出て、ダイアログが開く | 🟡 (項目は vitest `menuModel.test.ts`、操作は 👀) |
| K-33 | 取り込んだノードの実起動 | 取り込んだ talker を起動するとノード名・名前空間・リマップ・パラメータファイルどおりに動く | 👀 (demo_system の talker を取り込み起動 → `/demo_robot/imported_talker` が確実で対応づき実行。talker が宣言しないパラメータ `note` は rclcpp の仕様で一覧に出ない) |
| K-34 | 非常に大きい launch (数百ノード) の評価時間 | 20 秒以内に評価が終わる | ⬜ |

## L. 詳細計測モード (トレース, P4.7)

| ID | 項目 | 期待結果 | 状態 |
|---|---|---|---|
| L-01 | 対応づけと窓ごとの値 (unit) | rcl_node_init → rcl_subscription_init → rclcpp_subscription_init → callback_added の連鎖で take・コールバックがノード × トピックに付く。1 / 5 / 10 秒の受信・処理 Hz、処理時間の平均 / p95 / 最大、計測時間が窓より短いときは経過時間で割る (2 秒未満は null) | ✅ (`test_tracing_model.py`) |
| L-02 | プロセスごとの区別・後片付け (unit) | 同じハンドル値でも vpid が違えば混ざらない。init の無いプロセスの記録は `unknown_pids`。終了したプロセスの記録を捨てる。古いサンプルの刈り込み、対にならない callback_end は無視 | ✅ (`test_tracing_model.py`) |
| L-03 | rclpy (unit) | 受信数だけ (`hz_processed` / `cb_ms` は null、`lang: py`) | ✅ (`test_tracing_model.py`) |
| L-04 | バッファの大きさとフィルタ (unit) | 既定 4 MiB/CPU、/dev/shm の空きの半分に収まるよう縮める (64 MB・24 CPU で 1 MiB/CPU)、最小 4 KiB × 2、それも無理なら `ShmTooSmall`。`taken == 1` と自分のプロセスの除外フィルタ、古いセッション名から持ち主の pid | ✅ (`test_tracing_model.py`) |
| L-05 | 交通量への反映 (unit) | 対象ノードの受信行が `measured` (受信・処理・処理時間、理論値は `hz_expected`)。測れ始める前は理論値のまま。届いていない行は `not_delivered` のまま。送信行に `hz_traced` | ✅ (`test_tracing_merge.py`) |
| L-06 | 処理が追いついていない (unit) | 送信側の実測 (または受信数) に対して処理が 10% かつ 0.5 Hz 以上少ない → `behind` と `processing_behind` の診断。0.5 Hz 未満・rclpy は判定しない | ✅ (`test_tracing_merge.py`) |
| L-07 | 測れないノードの理由 (unit) | rclpy → `rclpy`、intra-process → `intra_process`、起動リストのノードでトレース開始前からのプロセス → `restart_needed`、その他 → `not_traced`。roshanavi 自身・注入ジョブは除外 | ✅ (`test_tracing_merge.py`) |
| L-08 | 実ノード: C++ talker / listener と遅いコールバック | API で有効化 → listener の受信 1 Hz・処理 1 Hz・処理関数名。200 ms 眠る slow_listener は送信 10 Hz に対して処理 5 Hz・処理時間 200 ms で `processing_behind`。取りこぼし 0、CPU が出る、ディスク < 32 MB。無効化で理論値に戻る | ✅ (`test_tracing_ros.py`) |
| L-09 | 実ノード: rclpy と開始前からのノード | demo_nodes_py の listener は受信だけ `measured`、理由 `rclpy`。roshanavi より前に起動した listener は `not_traced` で理論値のまま | ✅ (`test_tracing_ros.py`) |
| L-10 | 後片付け | 停止後に解析プロセス・lttng-sessiond / consumerd が残らない (開始前と同じ)、`roshanavi-` のセッションが無い、トレースのディレクトリが消える | ✅ (`test_tracing_ros.py`) |
| L-11 | 取りこぼしの報告 | 8 KiB/CPU のバッファで 2000 件ずつのバーストを送ると `discarded > 0` | ✅ (`test_tracing_ros.py`) |
| L-12 | 解析プロセスの異常終了 | SIGKILL から 5 秒後に起動し直し (`restarts: 1`)、有効化できる | ✅ (`test_tracing_ros.py`) |
| L-13 | API | `--tracing off` は `reason: disabled`、有効化は 409 `tracing_unavailable`、text/plain は 415、余計な項目は 422、/ws/live に `tracing`。lttng が無ければ `not_installed` | ✅ (`test_tracing_api.py`) |
| L-14 | UI の表示 (vitest) | 導入方法の案内、状態の 1 行 (件/秒・取りこぼし・ディスク・CPU)、受信 / 処理 / 処理時間、rclpy は「未対応」、`実測(トレース)` は受信行だけ、追いついていない文言、右ペインの行 | ✅ (`traffic/tracing.test.ts`) |
| L-15 | E2E: 有効化 → listener が実測(トレース) | 説明ダイアログ (対象ノード側・roshanavi 側の負荷) → 有効化 → 状態バー → /chatter の listener 行が `実測(トレース)` と処理の値、ノード別も同じ。無効化で理論値に戻る | ✅ (`e2e/tracing.spec.ts`) |
| L-16 | ベンチマーク (オン・オフ) | 10 トピック × 100 Hz と 720p 画像 30 Hz で、対象ノードの CPU・遅延、roshanavi の CPU、ディスク、件/秒、取りこぼし (DESIGN §4.3.2) | 👀 (`scripts/bench_tracing.py`) |
| L-17 | 別コンテナのノード | demo コンテナの external_listener は `not_traced` | 👀 (ラボで確認) |
| L-18 | 他の RMW (Cyclone DDS) | rmw_take / rmw_publish のトレースポイントがある | ⬜ |
