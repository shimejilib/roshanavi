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
| F-09 | 送信元ごとの Hz (talker + 注入ジョブが同じトピック) | 注入ジョブのエッジは実送信数、talker は「合計 − 注入」で「推定」、送信元 2 以上ならトピックに合計と送信元数 | ✅ (分配は pytest `test_rates.py`、表示は vitest、talker+ダミーは E2E) |

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
