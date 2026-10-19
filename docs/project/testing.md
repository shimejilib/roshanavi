# roshanavi — テスト

## テスト方針
- unit: expr (許可/拒否ケース, DoS 上限, 入力メッセージのフィールド参照の境界), msgutil (テンプレ・build・エラーパス), traffic 統計計算 (時刻注入で決定的に), scenario schema/判定ロジック。
- 統合 (rclpy, Docker 内): publisher → traffic に Hz が出る / injector periodic → 受信数 / scenario 実行 pass・fail 両方 / API を TestClient で叩く。
- `docker compose run --rm test` 一発で全テスト (C++ の gtest: `test_stats`・`test_image_ops`、pytest)。

## テストの実行コマンド
ROS はホストに入れず、すべて Docker で動かす (詳細は `CLAUDE.md`)。
- バックエンド全体 (gtest + pytest): `docker compose --profile test run --rm test`
- 1 ファイルだけ: `docker compose --profile test run --rm test python3 -m pytest -p no:cacheprovider -q /ws/src/roshanavi/test/<file>.py -k <expr>`
- Web の単体テスト: `cd web && npm ci && npx vitest run [file]`、型検査は `npx tsc --noEmit`
- E2E (隔離したスタック。利用者のラボには向けない): `scripts/e2e.sh` — 隔離の仕組みは [ui.md#実装メモ (P2)](../design/ui.md#実装メモ-p2)。
- ディストロを選ぶ: どのコマンドも先頭に `ROS_DISTRO=jazzy|lyrical|kilted` を付ける (既定 jazzy、イメージは `roshanavi:dev-<distro>`)。例: `ROS_DISTRO=lyrical docker compose --profile test run --rm test`、`ROS_DISTRO=lyrical scripts/e2e.sh`。利用者のラボ (既定は jazzy) とはイメージもコンテナも別なので止まらない。
- 正式対応は Jazzy と Lyrical。ROS・pydantic・FastAPI に触れる変更は、バックエンド全体を両方で通す。Kilted は動作確認のみ (下の R)。

反復中は変更に関係するテストだけを動かし、バックエンド全体と `scripts/e2e.sh` は最後に 1 回ずつ動かす。実時間のテスト (Hz・ペース・遅延) は、変更と無関係でそのテスト単独なら通る失敗はタイミングの揺れとして報告し、許容幅を緩めて隠さない。新しい機能には単体 + 統合テスト (UI の流れは E2E) を付ける。

## テスト項目一覧

状態の凡例: ✅ 自動テスト済み / 🟡 実装済み・自動テスト未整備 / ⬜ 未実装 (計画) / 👀 手動確認

自動テストは `docker compose --profile test run --rm test` で実行する。
「動的変化」系は、テスト内で rclpy ノードやプロセスを起動・停止して検証する。

### A. グラフ・トピックの動的変化

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
| A-15 | 診断 (片側のみ・名前の取り違え・型の不一致) | 片側だけのトピックは info (警告にしない)。名前が似ている組は警告 (つながっているトピックとの打ち間違いも)。隠しトピックを除き、決定的な順 | ✅ (unit `test_diagnostics.py`) |
| A-15a | 時間のかかる診断 (unit) | `subscriber_lost` / `publisher_lost` (直近 5 分に居た→居ない、3 秒未満の再起動は出さない、戻れば消える、5 分で期限切れ、最初から居なければ出さない、トピックごと消えたら出さない)、`mine_no_input` (ノードが現れて 3 秒後、`mine` のみ、送信元が来れば消える、`publisher_lost` より優先)、インフラのノード (`_ros2cli_*`、roshanavi 自身) は受信者に数えない | ✅ (`test_diag_history.py`) |
| A-15b | 診断の見せ方 (vitest) | バッジ・パネルは warning / error だけ。info は地図のトピックの下に「受信なし」「送信なし」、警告色にしない。`mine_no_input` はノードとトピックを警告色に。新しい 3 種の文 | ✅ (`graph/diagnosticsText.test.ts`、`graph/model.test.ts`) |
| A-15c | インフラを隠す (unit) | `_ros2cli_daemon_*` / `_ros2cli_*` ノード、`*/transition_event`、`*/_action/*` は内部トピック・内部ノードとして地図から隠れ、診断に数えない | ✅ (`test_diagnostics.py`、`lib/topics.test.ts`、`graph/model.test.ts`) |
| A-16 | 注入ジョブの仮想ノード | 実行中ジョブが `dummy:<id>` (role dummy) としてグラフに出て、終了で消える | ✅ |

### B. トラフィック計測

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
| B-12 | 計測ノードの統計 (gtest) | 欠番、複数 publisher の合計、連番非対応で null、送信時刻が無ければ受信側、計算期間の選択、遅いトピックの延長・`too_few`、止まったら 0、publisher ごとの値と停止、リングバッファの上限 (コンパクション後のビュー)。元の実装 (`reference_stats.hpp`) との照合: 乱数の流れ (複数 publisher・欠番・連番非対応・送信時刻なし・停止・遅れて参加・同時刻・窓の境界) × 5 つの窓で、トピック全体と publisher ごとの全項目がビット単位で一致。送信元ノードの対応表を作り直す条件 (グラフ変化・未知の gid を 1 回だけ・5 秒・照会の失敗) | ✅ (`roshanavi_probe/test/test_stats.cpp`) |
| B-13 | 計測ノードが使えないとき | `--probe off` / 未ビルド → Python の計測 (`measurement: python`、理由付き)。繰り返し異常終了 → 5 回で Python に切り替え | ✅ (`test_probe_unit.py`, `test_probe_ros.py`) |
| B-11b | 計測ノード: 後から参加した・入れ替わった送信ノード | グラフ変化時だけの照会 でも、後から同じトピックに publish し始めたノード、別名のノードに置き換わったときも、送信ノード名が付く (`basis: measured`) | ✅ (`test_probe_ros.py`) |
| B-14 | 計測ノードの異常終了 | 再起動され (1 秒後〜)、TRANSIENT_LOCAL の設定を受け取って計測を再開する | ✅ (`test_probe_ros.py`) |
| B-15 | 自分用のトピック | `/roshanavi/_probe/*` と計測ノードは地図・診断・トラフィックに出ない | ✅ (`test_probe_unit.py`, `test_probe_ros.py`) |
| B-16 | gid がグラフと対応しない RMW | `resolved: false` ならトピック合計の分割 (`rates.py`) にフォールバック、UI に案内 | ✅ (判定は `test_probe_unit.py` / `measurement.test.ts`)、Cyclone DDS の実機は 👀 (gid 不一致・連番非対応を確認) |
| B-17 | 送信ノードごとの値 (unit) | 送っていない送信者は 0 Hz の実測、注入ジョブは `exact` のまま、件数未確定のジョブは自分のノードの実測、受信者は実測値の和 | ✅ (`test_probe_unit.py`) |
| B-18 | 計測ノードの負荷 | 10 トピック × 100 Hz、画像 720p 30 Hz (と、大規模を模した 100 × 10 Hz・200 × 1 Hz・2 × 500 Hz: `scripts/bench_probe.py`) で計測ノード + サーバーの CPU が Python の計測より小さい | 👀 ([measurement.md#C++ 計測ノード](../design/measurement.md#c-計測ノード-roshanavi_probe-p46) の表: 9.5% 対 32.3%、11.8% 対 17.4%) |
| B-19 | 止まったトピックの Hz 表示 (vitest) | hz 0 / `stale` のとき「(受信時刻で概算)」を付けない | ✅ (`timing.test.ts`) |
| B-20 | 計測の経路の表示・実測バッジ (vitest) | 「計測: C++ 計測ノード (CPU x%)」、再起動中・RMW の制限・Python の理由、`measured` は「実測」 | ✅ (`traffic/measurement.test.ts`) |
| B-21 | E2E: talker + 1 Hz の入力ノードが /chatter | 地図の talker の辺が約 1 Hz で「推定」が付かない。トラフィックタブで talker が約 1 Hz の「実測」、入力ノードが約 1 Hz、ツールバーに「C++ 計測ノード」 | ✅ (`e2e/smoke.spec.ts`) |
| B-22 | 計測していないトピックは「分けられない」ではない (pytest) | 重い型・オフにしたトピックの送信元は `basis: not_monitored`、受信側の数字なしも `not_monitored`、`heavy` が付く。注入ジョブ・恒久ダミーの既知の値は残る。計測中・`unsupported` は従来の根拠のまま | ✅ (`test_rates.py`, `test_sub_rates.py`) |
| B-23 | 計測していない重いトピックの Hz はトレースから (pytest) | 詳細計測モードで、送信元の行が `traced` の Hz (帯域は null)、全送信元がトレースされたときだけ合計の `hz_traced`、一部だけなら null。受信側はノードの中の受信 Hz。計測中のトピックは変わらない | ✅ (`test_tracing_merge.py`) |
| B-24 | 計測の on/off をプロジェクトに保存 (pytest) | `traffic_monitor` に保存・自動保存、新しい Lab で復元、プロジェクトの切り替え・読み直しで置き換わる、REST の往復、`PUT /api/project` で置き換わる | ✅ (`test_project.py`) |
| B-25 | 地図の「受信なし」は本物の受信側だけで決まる (pytest) | roshanavi 自身 (`roshanavi` / `roshanavi_probe` / `roshanavi_scenario`) の購読は受信側に数えない (`show_self` でも)。本物の受信側がいれば出ない | ✅ (`test_graph_unit.py`) |
| B-26 | 計測していない行の表示 (vitest) | 「計測していません (画像などの重いデータは既定でオフ)」+「計測する」、軽いトピックは理由なし、数字の欄は 0 Hz でなく —、「受信なし」「未受信」「分けられない」が出ない。詳細計測モードは Hz とトレース表記・「— (詳細計測では帯域は測れません)」。計測中で本当に未受信なら「未受信」 | ✅ (`traffic/notMeasured.test.ts`, `graph/model.test.ts`) |
| B-27 | E2E: 画像のトピック | `/e2e_viz/image` (roshanavi の外の画像送信ノード) の行・展開行・詳細に「計測していません (…)」と「計測する」、地図の「受信なし」が出ない → 押すと数字が出る → 別プロジェクトに切り替えると戻り、元に戻すと保存から復元される。詳細計測モードでは中継ノードの出力コピーの Hz がトレースで出て、帯域は「— (詳細計測では帯域は測れません)」 | ✅ (`e2e/monitor.spec.ts`。再起動は「プロジェクトの切り替えで読み直し」で代用。プロセスの再起動は pytest B-21) |

### C. ダミー注入

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

### D. シナリオ (P6)

仕様: [scenarios.md](../design/scenarios.md)。

| ID | 項目 | 期待結果 | 状態 |
|---|---|---|---|
| D-01 | inject → expect pass、CLI と JUnit | `send` → `expect` が成功、CLI は exit 0、JUnit XML (セットアップ + ステップ + ガードの testcase) が読める | ✅ (`test_scenario_ros.py`) |
| D-02 | expect が timeout | 失敗、CLI は exit 1、受信件数・条件に合った件数・最後に届いた値・合わなかった条件と実際の値を出す | ✅ (`test_scenario_unit.py`、`test_scenario_ros.py`) |
| D-03 | send 直後の応答を取りこぼさない | 事前購読 + 直前の入力から数える窓で、すぐ返る応答 (5 回続けて) を受ける。起動直後のノード (launch_pytest) でも取りこぼさない (発見を最大 3 秒待つ) | ✅ (`test_scenario_ros.py`) |
| D-04 | where の op とフィールドのパス | `eq ne lt le gt ge range approx regex contains exists len_eq len_range`、ドット + 配列の番号、bool と数の区別、大きい配列は長さと先頭、無いフィールド・範囲外・配列でないものは平易な理由 | ✅ (`test_scenario_unit.py`) |
| D-05 | rate | `stats.window_rate` と同じ値、範囲内なら成功、止まったら「止まりました」、2 件未満は「測れません」 | ✅ (`test_scenario_unit.py`、`chatter_smoke`) |
| D-06 | setup の起動・wait_for_node・後片付け | 成功・セットアップの失敗 (ノードが現れない・パッケージが無い)・中止のどれでもプロセスが残らない。`cmd` は ros2 run / launch だけ | ✅ (`test_scenario_ros.py`、`test_scenario_unit.py`) |
| D-07 | 不正 YAML / 未知キー | パスと行番号付きの平易なエラー (未知のキー・種類・必須・値の範囲・version・stop の参照・YAML の構文) | ✅ (`test_scenario_unit.py`) |
| D-08 | ディレクトリ一括実行 | 全件を実行し、JUnit にまとめる。1 件でも失敗 (ファイルの誤りを含む) なら exit 1、パスが無ければ 2 | ✅ (`test_scenario_ros.py`) |
| D-09 | throughput / latency (unit) | 比と取りこぼしの説明、header.stamp と受信順 (近似、取りこぼしでずれる) の対応づけ、p95 の上限超え、stamp が合わなければ match: order を案内 | ✅ (`test_scenario_unit.py`) |
| D-10 | ガード | シナリオの間ずっと見張り、wait の途中で破れたらそのステップを中断して失敗、残りは未実行 | ✅ (`test_scenario_unit.py`、`test_scenario_ros.py`) |
| D-11 | サンプルのシナリオが実ノードで通る | chatter_smoke・state_machine・function_shout・perception (throughput + latency を stamp で)・perception_order (受信順、近似) | ✅ (`test_scenario_ros.py`) |
| D-12 | 壊したサンプルが説明付きで失敗する | 期待値の違い (実際は "IDLE")、トピック名の打ち間違い (似た名前の送信者を候補に)、keep_stamp:=false を stamp で対応づけ | ✅ (`test_scenario_ros.py`) |
| D-13 | 原因の候補 (unit) | 送信者がいない (似た名前)・受信者がいない・QoS が合わない・複数の型、型が分からず購読できない | ✅ (`test_scenario_unit.py`、`test_scenario_ros.py`) |
| D-14 | プロジェクトの起動設定 | `start: {target}` / `stop` / `stop: {target}`、終わったら元の状態に戻す、無い ID はエラー | ✅ (`test_scenario_ros.py`) |
| D-15 | launch_pytest から使う | `examples/launch_pytest/` のテストが launch で起動したノードに対して成功する | ✅ (`test_scenario_ros.py`) |
| D-16 | API: ファイル | 保存 (同名は 409)・取得・YAML のまま保存 (コメントを残す)・行番号付きの 422・検査・削除、id の包含 (`..`・symlink で外へ・ほかの種類)、サンプルは読み取り専用、Host / Origin / Content-Type | ✅ (`test_scenario_server.py`) |
| D-17 | API: 実行 | 非同期の実行と途中経過 (`/ws/scenarios`)、履歴と結果のファイル、1 つずつ (409)、中止、失敗の説明と原因の候補、誤ったファイルはエラーの結果 | ✅ (`test_scenario_server.py`) |
| D-18 | 記録モード (API) | 見張るトピックのタイムライン (速いトピックは 10 件の後は毎秒 10 件)、注入の開始・停止の操作、止めた後の操作は記録しない、区間の周期・件数の比の計測 | ✅ (`test_scenario_server.py`) |
| D-19 | 記録モードのロジック (vitest) | フィールドの自動選択 (スカラー eq・小数 approx・番号付きの文字列は正規表現・stamp / カウンタ / 長さの変わる配列 / 大きな配列は外す)、within = max(0.5, 実測 × 3)、操作 → ステップ (stop の対応・QoS)、待ち時間の組み立て、しきい値の提案、編集の補助 | ✅ (`scenarios/record.test.ts`、`scenarios/editSteps.test.ts`、`scenarios/messages.test.ts`) |
| D-20 | E2E: 記録 → 実行 → 壊す | 見張る /shouted を選んで記録 → お試し送信で /chatter に送る → タイムラインの答えをクリック → 「これが来るはず」(data にチェック) → 保存 → 実行で成功 → 期待値をフォームで変えて保存 → 実行で失敗し、届いた値と合わなかった条件が見える。サンプルのシナリオもタブから成功 | ✅ (`e2e/scenario.spec.ts`) |
| D-21 | E2E: 記録モードの区間 | Shift+クリックで区間 → 周期のカードに実測から提案したしきい値、来ないはずのカード、破棄 (throughput / latency の画面操作は未自動化、ロジックと計測 API は自動テスト済み) | ✅ (`e2e/scenario.spec.ts`) |

### E. API・セキュリティ

| ID | 項目 | 期待結果 | 状態 |
|---|---|---|---|
| E-01 | 式評価器の拒否ケース (属性・添字・lambda・`__import__`) | すべて拒否 | ✅ |
| E-02 | DoS 上限 (巨大べき乗・文字列乗算・深いネスト) | 計算前に拒否 | ✅ |
| E-03 | パストラバーサル (`../`, 絶対パス, 外向き symlink) | `forbidden_path` | ✅ |
| E-04 | 不正な Host ヘッダ (DNS rebinding) | 403 | ⬜ (P1.5) |
| E-05 | 外部 Origin からの WebSocket 接続 | 1008 で拒否 | ⬜ (P1.5) |
| E-06 | text/plain の POST (CSRF) | 415 | ⬜ (P1.5) |
| E-07 | 既定の bind が 127.0.0.1 | 外部 IF から到達できない | 👀 |

### F. UI (P2)

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

### G. 互換性

| ID | 項目 | 期待結果 | 状態 |
|---|---|---|---|
| G-01 | rmw_fastrtps_cpp (既定) | 全テストが pass | ✅ |
| G-02 | rmw_cyclonedds_cpp | 全テストが pass (連番非対応時は dropped=null) | ⬜ |
| G-03 | rmw_zenoh_cpp | 基本機能が動く | ⬜ |

### H. Launcher・プロジェクト・恒久ダミー (P3)

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
| H-30 | composable container | コンテナ単位で対応づく (ノード単位にはならない) | ✅ (実コンテナ: `test_container_ros.py`。`launch_ros_<pid>` の誤対応を修正) |
| H-31 | 別コンテナ / 別 PC のノード | 対応づけない (`other`) | 👀 |
| H-32 | 地図の右クリック / 右ペインから停止・再起動・起動 | roshanavi が起動したノードだけ操作でき、停止前に同時に止まるノードを列挙して確認する | ✅ (可否と確認文は vitest、右クリック → 停止 → 確認 → 地図から消える は E2E) |
| H-33 | roshanavi が起動していないノード | 停止ボタンは無効で、理由を表示する (シグナルを送らない) | ✅ (vitest + E2E) |

### I. メディア・ブラウザ入力・録画 (P4)

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

### J. デモ体験・地図の操作・パラメータ・更新タイミング (P4.5a)

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
| J-21 | E2E: talker のパラメータ / 外部ノード | 「ROS の内部のパラメータ」(折りたたみ) を開くと talker の `use_sim_time` が見えて編集できる。external_talker は停止が無効、パラメータは閲覧のみ | ✅ |
| J-22 | E2E: 型の定義とノードの入出力 | /chatter の定義に `string data`。/listener の「受信しているデータ」に /chatter と Hello World | ✅ |
| J-23 | E2E: 初回の案内 | 起動リストが空なら案内が出て、「試しに talker を起動してみる」で talker が動き、案内が消える | ✅ |
| J-24 | E2E: デモ構成 | talker = 自分、listener = 依存 (lab が起動)、external_talker = その他 (/external/chatter)、ROS 標準パッケージは既定で非表示 | ✅ (`smoke` / `launcher.spec.ts`) |
| J-25 | パラメータの変更を外部ノードで確認ダイアログ経由で行う (UI) | 「変更を許可する」→ 確認 → 編集欄が出る | 🟡 (ロジックは unit、UI 操作は 👀) |
| J-26 | 「ビルドして再起動」を地図から | ワークスペースのパッケージのノードでビルドが始まり、成功後に再起動 | 🟡 (無効化の条件は unit。デモ環境に自分のパッケージが無いため E2E 未整備) |
| J-27 | 最終更新の警告色 (WS の切断) | 5 秒以上フレームが届かないと警告色 | 🟡 (判定は unit、切断の実操作は 👀) |
| J-28 | サービスの待ち時間と読み取りのやり直し (unit、偽のクライアント) | 既定の待ち時間は 5 秒 (パラメータ・ライフサイクル)。応答が来ないと一覧・describe・get は 1 回だけやり直して 2 回目の答えを返し、それでも来なければ `param_timeout`。`set_parameters` はやり直さない (1 回だけ呼ぶ)。サービスが無い (`unavailable`) ときはやり直さない。`--service-timeout` は既定 5、0 は拒否 | ✅ (`test_service_call.py`) |
| J-29 | パラメータの並び順 (サーバー) | クラスノードの `GET .../parameters` に `init_order` (`__init__` の引数の書いた順)。クラスでないノード・未登録・読めないモジュールは `null` でエラーにならない | ✅ (`test_params.py`) |
| J-30 | パラメータのダイアログの並べ方・折りたたみ (vitest) | クラスノードは `__init__` の順、引数に無いものは最後に名前順、それ以外のノードは名前順。`use_sim_time`・`start_type_description_service`・`qos_overrides.*` は「ROS の内部のパラメータ」に入り、入力は変わらない | ✅ (`params/paramLayout.test.ts`) |

### K. ノード一覧・lifecycle・launch の分解取り込み・送受信ごとのトラフィック (P4.5b)

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
| K-23 | 一括操作の計画と確認文 (vitest) | 起動設定ごとに 1 回、一緒に止まるノード (選択外も) を列挙、対象外の理由、lifecycle は activate / deactivate で外部の注意付き 。行と計画は同じ `GET /api/node-list` の応答 (`rows` + `targets`) から作る: 停止直後に別の情報源が「動作中」のままでも起動の計画が空にならない | ✅ (`nodelist/bulk.test.ts`) |
| K-24 | lifecycle と取り込みの表示 (vitest) | 遷移の並び・確認文、取り込みの既定の選択・引数の差分・要約・理由文・取り込めない理由 | ✅ (`lifecycleText.test.ts`, `importModel.test.ts`) |
| K-25 | 一時停止中の最終更新・遅いトピックの表示 (vitest) | 一時停止中は警告色にせず「一時停止中 (HH:MM:SS の表示)」。「0.50 Hz (直近 10 秒で計算)」「— (1 秒窓では測定不可)」 | ✅ (`timing.test.ts`) |
| K-26 | 送受信ごとの行・ノード別 (vitest) | 送信 → 受信の順、ノード別のまとめと並び、届いていない・分けられない値、根拠のラベル、すべて展開 | ✅ (`traffic/endpoints.test.ts`, `model.test.ts`) |
| K-27 | E2E: チェックボックスで talker + listener を一括停止・起動 | ↓ キーで次の行へ、確認ダイアログに両方のノード、停止状態の行になり、起動で戻る。外部ノードのチェックは無効で案内が出る 。停止直後の一括起動は **再試行なしで** 1 回のクリックで確認ダイアログが出る | ✅ (`e2e/nodes.spec.ts`) |
| K-28 | E2E: 外部の lifecycle ノード (lc_talker) | configure → activate → deactivate → activate → cleanup。確認ダイアログに外部の注意 | ✅ (`e2e/nodes.spec.ts`) |
| K-29 | E2E: launch の取り込み | roshanavi / demo_system.launch.py を解析 → 2 ノードと ExecuteProcess → 取り込むと一覧に取り込み元付きで出る | ✅ (`e2e/nodes.spec.ts`) |
| K-30 | E2E: トラフィックの展開とノード別 | /chatter を展開して talker (送信・実測) と listener (受信・理論値)、ノード別に切り替えても同じ | ✅ (`e2e/smoke.spec.ts`) |
| K-31 | 一緒に止まる composable container のノード (実機) | container 内の複数ノードが 1 グループになり、確認ダイアログに全ノード | ✅ (実コンテナ: `test_container_ros.py` で全ノードが 1 グループ・確認に列挙するノード一覧・停止で全部止まる。E2E: `e2e/pipeline.spec.ts`) |
| K-32 | 地図の右クリック・右ペインからの lifecycle | lifecycle ノードにだけ項目が出て、ダイアログが開く | 🟡 (項目は vitest `menuModel.test.ts`、操作は 👀) |
| K-33 | 取り込んだノードの実起動 | 取り込んだ talker を起動するとノード名・名前空間・リマップ・パラメータファイルどおりに動く | 👀 (demo_system の talker を取り込み起動 → `/demo_robot/imported_talker` が確実で対応づき実行。talker が宣言しないパラメータ `note` は rclcpp の仕様で一覧に出ない) |
| K-34 | 非常に大きい launch (数百ノード) の評価時間 | 20 秒以内に評価が終わる | ✅ (200 ノードのパイプライン launch、`test_container_ros.py`) |

### L. 詳細計測モード (トレース, P4.7)

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
| L-16 | ベンチマーク (オン・オフ) | 10 トピック × 100 Hz と 720p 画像 30 Hz で、対象ノードの CPU・遅延、roshanavi の CPU、ディスク、件/秒、取りこぼし ([measurement.md#詳細計測モード](../design/measurement.md#詳細計測モード-トレース計測-p47)) | 👀 (`scripts/bench_tracing.py`) |
| L-17 | 別コンテナのノード | demo コンテナの external_listener は `not_traced` | 👀 (ラボで確認) |
| L-18 | 他の RMW (Cyclone DDS) | rmw_take / rmw_publish のトレースポイントがある | ⬜ |
| L-19 | 解析の子プロセス (unit、偽の解析器) | 複数フレームにまたがるイベントの順序と件数、解析エラーは例外で子は続行、子のクラッシュ・30 秒無応答は kill して作り直し、途中で読むのをやめても次のチャンクがずれない、N チャンクごとの入れ替えで漏れる fd が N 本以内、改行入りのパスを拒否 | ✅ (`test_tracing_parser.py`) |
| L-20 | fd を bt2 の裏で閉じない | 実チャンク 16 回の回転で worker の fd が平ら、解析の子は 4 チャンクごとに入れ替わり、子の fd も有界。worker 終了で子も残らない | ✅ (`test_tracing_fds.py`) |

### M. サンプルノード・変換ノード・パーセプションデモ (P5)

| ID | 項目 | 期待結果 | 状態 |
|---|---|---|---|
| M-01 | 画像の純粋な関数 (gtest) | rgb8 / bgr8 の輝度の重み、行の詰め物 (step)、未対応の encoding・足りないバッファは理由付きで失敗。Sobel: 平らなら 0、段差の両側で 255、端は 0、小さすぎる画像は全部 0。塊: 2 つを面積順、しきい値・最小面積・最大数、斜めだけで接する画素は別、100 万画素の塊でも落ちない | ✅ (`roshanavi_examples/test/test_image_ops.cpp`) |
| M-02 | image_filter (実ノード) | 160x120 rgb8 → gray / edges が 160x120 mono8 (step 160)、四角の中は 240・背景 0、縁だけエッジ。`keep_stamp:=true` は入力の stamp (1234.5678)、false はいまの時刻。frame_id は引き継ぐ | ✅ (`test_examples.py`) |
| M-03 | image_filter の遅い処理 | `process_delay_ms:=250` で 20 Hz を送っても出力の間隔の中央値 ≥ 0.2 秒 | ✅ (`test_examples.py`) |
| M-04 | blob_detector (実ノード) | 30x30・20x20・12x12 の四角、`min_area:=200` → 検出 2 件、最大の bbox は中心 (75, 55)・大きさ 30x30、class_id `blob`、score = 240/255、header の stamp は入力のまま | ✅ (`test_examples.py`) |
| M-05 | audio_level の計算 (unit) | 無音・空は -120 dB、16384 一定で -6.02 dB、振幅 0.5 の sine で -9.03 dB。S16LE のバイト列 (奇数の末尾は無視)。ヒステリシス: 2 つのしきい値の間では状態を保つ、逆順のしきい値は拒否 | ✅ (`test_examples.py`) |
| M-06 | audio_level (実ノード) | Int16MultiArray で音 / 無音を 1 秒ずつ → level_db に -9.03 と -120、silence が true と false の両方。AudioDataStamped (既定) で -6.02 dB | ✅ (`test_examples.py`) |
| M-07 | state_machine の遷移 (unit・実ノード) | IDLE → start → RUNNING → stop → IDLE、fault → ERROR、ERROR では start を無視、reset → IDLE、知らないコマンドは無視。実ノードでも /cmd に送ると /state がその値になり、周期の送信でも保たれる | ✅ (`test_examples.py`) |
| M-08 | 式: 入力メッセージのフィールド参照 | `msg.data`、`msg.linear.x * 0.5`、`msg.values[-1]`、計算した添字、`msg.points[1].x`、複数入力 (`msg1` / `msg2` / 任意の別名)、`${msg.header}` は素の dict、`now_stamp()`、upper lower strip replace len clamp | ✅ (`test_expr_fields.py`) |
| M-09 | 式: 安全の境界 | `__class__` `__dict__` `_data` などの `_` 始まり、実在するメソッド名 (`plain` `field`) も辞書の検索だけで no_field。文字列の定数・呼び出しの結果・変数・定数への属性、入力名以外の名前は拒否。getattr / type / vars / `__import__` / メソッド呼び出し、内包表記 (入れ子も)・ジェネレータ・lambda・スライス・タプル添字・文字列の添字・walrus・f-string・star 引数は拒否。巨大な添字 (10**9, 2**1000)・範囲外・bool 添字、文字列の連結・繰り返し・replace の膨張・巨大なべき・長い JSON 化・深い `.a.a.a…` は上限で拒否。注入のペイロード (名前なし) は従来どおり属性・添字をすべて拒否。ビューは変更・削除・反復できない。別名の予約語・形式の検査 | ✅ (`test_expr_fields.py`) |
| M-10 | 変換の仕様の検査 | 既定の別名 (msg / msg1, msg2)、relay は入力 1 つ・式なし・型を変えない、大きい型は relay だけ、trigger・別名の一意と予約語、複数入力は mapping 必須、遅延の範囲、取りこぼし 0〜1、間引き > 0。プロジェクトファイルの往復、targets / dummies / transforms をまたぐ ID の重複 | ✅ (`test_transform_compute.py`) |
| M-11 | 対応づけ・条件・型の変換・入力のままの送信 | upper、条件で捨てる (エラーなし)、`int(msg.data) * 2` で Int32、変換できない値はフィールドの場所付きのエラー、ネストした Twist と clamp、mapping なしは入力をそのまま、コンパイルエラーをフィールドごとに (条件・構文・未知の名前) | ✅ (`test_transform_compute.py`) |
| M-12 | 間引き・遅延・取りこぼし・結合 (unit) | 取りこぼし 30% (乱数の種で 28〜32%)、100 Hz → 10 Hz に間引き (間隔 ≥ 95 ms)、±2 ms の揺らぎでは間引かない、一定の遅延と範囲の遅延 (平均 0.15 秒)、結合は全部が届くまで待ち、trigger の入力でだけ送る、遅延の待ちは期限順・上限で overflow・送信の失敗で止まらない | ✅ (`test_transform_pipeline.py`) |
| M-13 | 変換ノード (実 ROS) | upper と条件、Image (64x48 rgb8) をバイト列のまま中継、50 Hz → 5 Hz の間引き (間隔 ≥ 0.15 秒)、400 ms の遅延 (≥ 0.39 秒)、取りこぼし 50% (30〜70%)、2 入力を trigger で結合、式のエラーでは起動しない | ✅ (`test_transform_ros.py`) |
| M-14 | 変換ノードの実行ファイルと書き出し | `ros2 run roshanavi transform --config` が自分の名前で送る (SIGINT で 0)、式のエラーは終了コード 2。書き出した launch (`executable='transform'`) を `ros2 launch` で動かせる | ✅ (`test_transform_ros.py`) |
| M-15 | 変換ノードの API | `POST /api/transforms?start=true` → kind / role `transform`、自動保存、地図に役割 transform、出力が届く。PUT で変更、入力と同じ出力トピックは 400、削除でプロジェクトから消える | ✅ (`test_transform_ros.py`) |
| M-16 | 試算 (プレビュー) | 出力、届いていない入力は型の既定値 (`templated`)、フィールドのエラー (no_field と fields の一覧)、条件で送らない、型に合わない値は build_ のエラー、仕様のエラー・知らない別名、relay は入力のまま、API は常に 200 (サンプル 9 個・余計な項目は 422) | ✅ (`test_transform_compute.py`) |
| M-17 | プロジェクトの切り替え | サンプルと保存済みを一覧、サンプルは初回だけ data/projects にコピー (編集は上書きされない)、一覧に無い ID (パス) は開けない、API で perception_demo を開くと起動リストが入れ替わり、元のプロジェクトファイルには書かない。同梱の 3 つのプロジェクト (demo_project / perception_demo / busy_demo) が検証を通る (サンプルノードは demo_project では autostart なし)。切り替え後は新しいプロジェクトの autostart が必ず動く (古い起動リストを止めている最中の housekeeping と競合しない) | ✅ (`test_project_catalog.py`, `test_project.py`) |
| M-18 | サンプルの動画・音声の生成 | blobs.mp4 と tone.wav (16 kHz・mono・16 bit・12 秒) を作る、2 回目は作らない (mtime が変わらない)、途中のファイルが残らない | ✅ (`test_project_catalog.py`) |
| M-19 | 編集画面のロジック (vitest) | 既定値 (ノード名・出力トピック・大きい型は relay)、テンプレートから「そのまま写す」対応づけ、仕様の組み立て (条件・遅延・間引き・取りこぼし %)、relay は式を落とす、各エラーの平易な文、プレビュー用の緩い検査、複数入力の別名の振り直しと trigger、編集時の復元 | ✅ (`transform/transformForm.test.ts`) |
| M-20 | 式のエラーの日本語 (vitest) | code と params から文 (フィールドの一覧・関数名・かっこの閉じ忘れ)、知らない code はサーバーの文を添える、条件・フィールド・全体への振り分け | ✅ (`transform/previewText.test.ts`) |
| M-21 | 地図の右クリック (vitest) | トピックに「このトピックを受けて変換するノードを作る」、変換ノードは 起動・停止・再起動・変更・書き出し・ログ・パラメータ・I/O (一時停止とビルドは無い) | ✅ (`graph/menuModel.test.ts`) |
| M-22 | E2E: /chatter → /chatter_upper | トピックの右クリックから作成、入力と型が入っている、`msg.nope` はフィールドの場所に日本語のエラー、プレビューの左に Hello World・右に HELLO WORLD、作成すると地図に役割 transform、エコーが大文字、プロジェクトに保存、ノードのメニューに「変換の内容を変更」 | ✅ (`e2e/transform.spec.ts`) |
| M-23 | E2E: パーセプションデモ | ⚙ からサンプルの perception_demo を開く → image_filter / blob_detector / audio_level / dummy_camera / blob_count (transform) が地図に出る、/camera/gray の画像ビューアが 320 px 幅、/camera/blob_count のエコー。最後に元のプロジェクトに戻す | ✅ (`e2e/perception.spec.ts`) |
| M-24 | 詳細計測モードでのサンプルノード | image_filter / blob_detector は受信・処理・処理時間、`process_delay_ms` を上げると「処理が追いついていません」。audio_level / state_machine / 変換ノードは受信数だけ (rclpy) | 🟡 (仕組みは L-08 / L-09 と同じ。サンプルノードでの確認は未整備) |
| M-25 | 変換ノードの高い入力レート | 数百 Hz の入力で CPU と遅れ (Python の式評価の限界) | ⬜ |
| M-26 | executor_busy_demo の統計 (unit) | 数えた回数 → 毎秒の回数・空振りの割合・CPU% (複数スレッドで 100 超)・窓の切り替え・経過 0 は全部 0。`off` (YAML では false) の受け付け、不正な値は拒否。`PassCounter` (偽の executor) が「コールバックを返した周」と「空の周」を分け、実行中の周は数えない。実物の Single / MultiThreadedExecutor で数が増える | ✅ (`test_executor_busy_demo.py`) |
| M-27 | 空回りの再現 (実ノード、タイミング・環境依存) | `busy_demo_driver` 100 Hz で multi+off と single+default は 1 コールバックあたり 20 回未満の待ち・毎秒 1,500 回未満・処理 ≥ 70/秒。multi+default は空振り > 90%、待ちの回数・空振りの回数・1 コールバックあたりの待ちが multi+off の 10 倍以上 (実測は約 27 倍)、CPU が 2 倍超。再現しない環境 (別の RMW・upstream の修正) では理由を付けて skip し、許容幅は緩めない | ✅ (`test_executor_busy_demo.py`、測定は 3 構成 × 約 10 秒) |
| M-28 | `examples/busy_demo` が検証を通る | 4 つのターゲット (driver + 3 構成)、autostart なし、構成ごとに別のノード名と stats トピック、executor / qos_events の組み合わせ | ✅ (`test_project_catalog.py`) |

### N. データの種類・関数ノード (P5.5)

| ID | 項目 | 期待結果 | 状態 |
|---|---|---|---|
| N-01 | 種類 ↔ 型の対応表 (unit) | 9 種類の型が設計どおり、音声は audio_common_msgs が無ければ Int16MultiArray、未知の種類は `unknown_kind`、互換の型 (Float32 → 数値、Int32 → 整数、*MultiArray → 数値の並び、UInt8MultiArray → バイト列)、専用の型は None、明示の型は種類に合うこと | ✅ (`test_data_kinds.py`) |
| N-02 | 詳細設定モードの並び (unit + API) | よく使う型 → ワークスペースの独自型 → パッケージごと (名前順だけにしない)、`GET /api/types` の `groups`、`GET /api/data-kinds` | ✅ (`test_data_kinds.py`、`test_server.py`) |
| N-03 | Python の値との変換 (unit) | 文字列・数値・整数・ON/OFF・数値の並び・JSON・バイト列の往復、numpy の数値も可、bool を数値として受けない・整数でない float を拒否、互換の型は自分の型のまま、画像 rgb8 / mono8 / bgr8 の往復 (uint8 以外・4 トピックは拒否)、音声 int16、専用の型は dict、型の合わない戻り値は「関数は str を返しました」 | ✅ (`test_data_kinds.py`) |
| N-04 | 入力ノードの種類 (unit + schema) | 種類ごとの中身 (数値・整数・ON/OFF・カンマ区切り・JSON の検査・式 `sin(t)` → `${sin(t)}`)、画像・音声はファイルだけ、種類を変えたら最初の値も変わる (利用者の入力は残す)、`DummySpec.kind` は型に合わないと拒否 | ✅ (`input/inputForm.test.ts`、`test_data_kinds.py`) |
| N-05 | 種類の選択の表示 (vitest) | 既存の型の表示「文字列 (std_msgs/String)」「専用の型: geometry_msgs/Twist」、既存の String を JSON として扱う選択は保つ、検索で型を絞ってもグループの順は変えない、詳細設定モードの記憶 (ストレージが例外を投げても OFF で動く) | ✅ (`datakind/kinds.test.ts`) |
| N-06 | E2E: 文字列の入力ノードを ROS の型を見ずに作る | 新しいトピック → 9 種類が並ぶ、数値を選ぶと値の欄 (YAML なし)、文字列に戻す、画面に `std_msgs` / `/msg/` が出ない、エコーに届く、プロジェクトに `kind: string`、同じトピックでは選択の代わりに「このトピックは 文字列 (std_msgs/String) です」 | ✅ (`e2e/datakind.spec.ts`) |
| N-07 | E2E: 詳細設定モード | ⚙ 設定で ON → 再読み込みしても ON、型の一覧の最初のグループが「よく使う型」で先頭が String、`twist` で検索 → Twist、選ぶと専用の型で YAML テンプレート | ✅ (`e2e/datakind.spec.ts`) |
| N-08 | モジュールの一覧と包含 (unit) | ワークスペースの src の Python パッケージだけ (test・roshanavi は出さない)、外向き symlink のファイル・パッケージは解決も一覧もしない、不正な名前・標準ライブラリ・無いモジュールは拒否 | ✅ (`test_function_unit.py`) |
| N-09 | シグネチャは import せずに読む (unit) | import すると印のファイルを作るモジュールでも作られない、引数・注釈・既定値・戻り値・docstring、注釈から種類の推定、構文エラーはファイル:行 | ✅ (`test_function_unit.py`) |
| N-10 | ホットリロード (unit) | 保存で新しい関数、同じパッケージの補助モジュールも読み直す、構文エラー・import 時の例外・関数の改名は前の関数のまま場所付きのエラー (読み直しの繰り返しにならない)、直すと読み込む、見張りのスレッドが保存を検出 | ✅ (`test_function_unit.py`) |
| N-11 | 呼び出しと値 (unit) | 受信ごと、`None` は送らない、例外は `ファイル:行 (関数名)` 付きで数え、ノードは続く (ログは間引く)、戻り値の型違いは変換のエラー、JSON・画像 (入力の stamp を引き継ぐ)、複数入力は全部そろうまで待ち、trigger の入力だけで呼ぶ、周期は引数なし / 経過秒、読み直しは次のメッセージから | ✅ (`test_function_unit.py`) |
| N-12 | 仕様の検査 (unit) | 呼び出し方と入力の数、周期の rate_hz、roshanavi のモジュールは拒否、専用の型は type 必須、種類に合わない型、trigger は入力のトピック | ✅ (`test_function_unit.py`) |
| N-13 | ROS ノードのコードへの書き出し (unit) | 受信ごと・画像・複数入力 (trigger)・周期 (音声)・専用の型・バイト列の生成コードが `compile()` を通る、周期で経過秒を渡すのは引数があるときだけ、roshanavi が作ったファイルだけ置き換え利用者のファイルは 409、制御文字は拒否 | ✅ (`test_function_unit.py`) |
| N-14 | 実ノード: ホットリロードとエラー | `ros2 run roshanavi function` で /in → /out、ファイルを保存すると同じプロセスのまま新しい関数 (`reloads: 1`)、構文エラーは `reload_error` で前の関数が動き続ける、例外は `last_error` に行番号、ノードは止まらない、ログに「関数を読み直しました」「関数でエラーが起きました」 | ✅ (`test_function_ros.py`) |
| N-15 | 実ノード: 読めないモジュールで起動 | 終了せず `import_error` で待ち、直すと動き出す | ✅ (`test_function_ros.py`) |
| N-16 | API・地図・ノード一覧・プロジェクト | モジュールの一覧に roshanavi_examples.logic、`shout(text: str) -> str`、`POST /api/functions?start=true` → 地図の役割 function、`function_status` (running・シグネチャ・送信数)、ノード一覧の役割と起動元、プロジェクトの `functions:`、無いモジュールは 404、ワークスペースの外への書き出しは `forbidden_path` | ✅ (`test_function_ros.py`) |
| N-17 | 書き出したコードがツールなしで動く | `export-code` の `<name>_node.py` を `python3` で実行 → 同じノード名で /out に大文字 + ! | ✅ (`test_function_ros.py`) |
| N-18 | launch への書き出し・周期のサンプル | launch ファイルに `executable='function'` で `ros2 launch` で動く、`wave` を 20 Hz で呼ぶと -1〜1 の値 | ✅ (`test_function_ros.py`) |
| N-19 | 画面のロジック (vitest) | 引数の数から呼び出し方、注釈から種類と名前 (利用者の選択は上書きしない)、3 つの呼び出し方の仕様、平易なエラー文、編集時の復元、地図の右クリック「関数ノードの設定を変更」、役割 function の表示名 | ✅ (`function/functionForm.test.ts`、`graph/menuModel.test.ts`、`i18n.test.ts`) |
| N-20 | E2E: サンプルのモジュールから関数ノードを作る | モジュール roshanavi_examples.logic → 関数の一覧にシグネチャ → shout → 入力 /chatter は「文字列 (std_msgs/String)」、出力の種類は戻り値の注釈から文字列 → 作成 → 地図に役割 function、エコーに HELLO WORLD!、プロジェクトに保存、右クリックの編集画面に動作状況 (running) と書き出し | ✅ (`e2e/function.spec.ts`) |
| N-21 | 大きい画像を毎秒 30 枚 | numpy 変換と Python の呼び出しの CPU・遅れ | ⬜ |

### O. アプリ内チュートリアル

仕様は [ui.md#実装メモ (アプリ内チュートリアル)](../design/ui.md#実装メモ-アプリ内チュートリアル)。E2E は `web/e2e/tour.spec.ts`: 画面に出ている指示のとおり、`data-tour` の目印だけを使って最後まで操作し、終了後に作ったものが無いことまで確かめる (UI の変更でツアーが壊れると落ちる)。

| ID | 項目 | 期待結果 | 状態 |
|---|---|---|---|
| O-01 | 進行のエンジン (vitest) | 条件を満たした「やる」手順は続けて進み「見る」手順では止まる、最後の手順は自分では離れない、条件が例外を投げても「まだ」、一時停止・準備中は進まない、戻る・進むは範囲内、再読み込み後は続けられる手順まで戻る、目印・セレクタ・関数の指定、目標が無い手順は中央に出して注意を足す、始めてから作ったものだけを片づけの対象にする (もとから在ったものは対象にしない) | ✅ (`tour/engine.test.ts`) |
| O-02 | 進み具合の保存 (vitest) | 完了・初回案内・進行中のツアーが往復する (再読み込みで中断中に戻る)、壊れた JSON・未知のツアー・形の崩れた記録は空として扱う、保存先が無い・例外を投げても動く | ✅ (`tour/progress.test.ts`) |
| O-03 | ツアー定義 (vitest) | 5 つのツアー、手順 id の重複なし、最後は「見る」手順、全手順の文言 (使われない文言も無い)、指している `data-tour` が画面のコードに在る、各ツアーの条件 (`/hello` の書き方の揺れ・開始前から在るノードは数えない・赤い破線の有無・送り手だけを編集したこと・大文字のエコー・保存したシナリオの特定・開始前の実行結果は数えない) | ✅ (`tour/tours.test.ts`) |
| O-04 | 吹き出しの文言は HTML にならない (vitest) | `` `code` `` だけがコード表示、`<img onerror>` などは文字のまま | ✅ (`tour/richText.test.ts`) |
| O-05 | E2E: 初回の案内 | 空のストレージで起動するとカード「チュートリアルを始めますか?」、「あとで」で消え再読み込みしても出ない、⚙ 設定に 5 つのツアー (完了の印なし) | ✅ |
| O-06 | E2E: 画面の見方 | 11 手順 (1 / 11 …、2 つ目は pub/sub の 1 枚絵が地図に出て、次へで消える)、別のタブの手順でタブが切り替わる、Enter で次へ・戻る、Esc で中断 → 再読み込みしても「中断中」→ 続ける → 同じ手順、最後に文書名、完了の印が ⚙ 設定に付く | ✅ |
| O-07 | E2E: はじめての入力ノード | ＋入力ノード → 種類 (文字列) → `/hello` → 作成して起動 → 地図に現れる → ノード → トピックをクリック → エコーに `hello` → 「片づけて終わる」で入力ノードが消える | ✅ |
| O-08 | E2E: 届かない原因を見つけて直す | 学習用の送り手 (BEST_EFFORT) と受け手 (RELIABLE) が API で作られ赤い破線 → 診断の項目 (`BEST_EFFORT` と書いてある) → 右ペインで理由 → 送り手を選ぶ → 編集 → 保存して再起動 → 赤い破線が消える → 終了で 2 つとも消える (「残して終わる」は出ない) | ✅ |
| O-09 | E2E: 関数ノードを作る | `roshanavi_examples.logic` → `shout` → `/chatter` → `/shouted` → 作成 → エコーが大文字 (`HELLO WORLD`) → 終了で関数ノードが消える | ✅ |
| O-10 | E2E: シナリオを記録する | 学習用の関数ノードを用意 → シナリオタブ → 記録して作る → `/tour_out` を見張る → 記録開始 → お試し送信で `/tour_in` に送る → 戻って `HELLO SCENARIO!` をクリック → これが来るはず → 期待を追加 → 止める → 名前 → 保存 → 実行 → 成功 → 終了でシナリオも関数ノードも消える (19 手順) | ✅ |
| O-11 | E2E: 戻る・飛ばす・中断して片づける・目標が見つからない | 「この手順を飛ばす」「戻る」、Esc → ピル → 「やめて片づける」で進行の記録が消え完了にもならない、目印の要素が見えないとき手順は中央に出て「いまの画面に見つかりません」と書く (飛ばせる) | ✅ |
| O-12 | E2E: ダークモード | 吹き出しの背景と文字が本体のダークの色 (`--surface` / `--text`) | ✅ |
| O-13 | 準備に失敗したときの表示 (`demo_nodes_cpp` が無い環境など) | 「準備に失敗しました: …」と出てツアーは始まらず、途中まで作ったものは片づく | ⬜ (実装済み・自動テストなし) |
| O-14 | Chromium 以外 (Firefox / Safari) での見え方・キーボード操作 | 吹き出しの位置・フォーカス・Esc | 👀 (未確認: E2E は Chromium のみ) |

### P. 既知不具合の修正

| ID | 項目 | 期待結果 | 状態 |
|---|---|---|---|
| P-02 | 常駐ダミーのメニューは現在の `paused` に合う方だけ | `paused=false` なら「一時停止」だけ、`true` なら「再開」だけ。状態が取れない間は従来どおり両方 (vitest) / E2E は入力ノードのメニューに「再開」が出ない | ✅ (`graph/menuModel.test.ts`、`e2e/ux.spec.ts`) |
| P-03 | お試し送信のファイル一覧の再取得 | ウィンドウのフォーカス復帰・タブが見える状態に戻ったとき・「ファイル一覧を更新」ボタンで `/api/files` を取り直す (モード切替時の再取得は従来どおり) | ✅ (vitest `lib/refocus.test.ts`、E2E `e2e/media.spec.ts`) |
| P-04 | rosbag2 の `/events/write_split` は内部トピック | 録画するトピックの選択肢・シナリオ記録の候補・地図 (隠すトグル)・診断から外れ、トラフィックの既定の畳み対象 | ✅ (vitest `lib/topics.test.ts`、pytest `test_diagnostics.py::test_hidden_topics`) |
| P-05 | メディア注入の一時停止はソースを保持する | 一時停止中は `sent` が増えず、`count` も消費されない。再開すると残りが `late_events` 無しで送られ `count` ちょうどで終わる。一時停止中でも停止できる | ✅ (`test_media_job.py::test_pausing_a_media_job_holds_the_source_instead_of_dropping_frames` / `test_a_paused_media_job_can_still_be_stopped`) |
| P-06 | ブラウザ入力: 閉じる直前のフレームを失わない | 破棄の前に ack を待つ (順序をフェイクで検証)、閉じる / 停止コマンドの直後でも送ったフレームが全部届く、停止コマンドには処理と drain の後に `stopped` が返る | ✅ (`test_media_capture.py::test_teardown_waits_for_acks_before_destroying_the_publishers` / `test_frames_sent_right_before_the_socket_closes_are_all_published`) |
| P-07 | 「起動中」は地図に対応づくまで | `starting` のターゲットでもノードが対応づいていれば一覧の状態は `running`。対応づいていなければ `starting` のまま、`stopped` は変わらない | ✅ (`test_launcher_process.py::test_service_reports_running_once_the_node_is_mapped_even_within_the_starting_window`) |
| P-08 | 手で動かしたノードの位置はトポロジーが変わっても固定 | ドラッグした位置を記録しレイアウトで戻す。プロジェクトごとに localStorage へ保存 (壊れた JSON・形の崩れ・保存先なし・例外でも動く、件数に上限)。「整列し直す」で全部外れる。E2E: talker をドラッグ → 入力ノードを足してもそのまま → 再読み込みしてもそのまま → 整列し直すで動く | ✅ (vitest `graph/pins.test.ts`、E2E `e2e/ux.spec.ts`) |
| P-09 | 最後に開いたプロジェクトを再起動後も覚える | `<data_dir>/last_project.json` に `id` を保存・起動時に一覧と照合 (サンプルは通常の「開く」と同じくコピー)。壊れた JSON・型違い・一覧に無い id・消えたファイル・書き込めない data_dir は無視して `--project` に戻る。Lab を作り直す (= 再起動) と記憶したプロジェクトで始まり、ファイルを消すと `--project` に戻る。API で切り替えると保存され、失敗した切り替えでは変わらない | ✅ (`test_project_catalog.py`) |
| P-10 | 変換ノードのプレビューは切り詰めない値で計算 | `EchoManager.latest_sample` は 32 個を超える配列も全部返し、サイズの上限を超えると `capped` で表示用の値に戻る。`GET /api/echo/{topic}/sample` (エコー前は `msg: null`)。UI は切り詰めの検出 (配列・文字列・深い所) と全体への差し替え、切り詰めが残るときだけ注意書き。E2E: 40 要素の配列で `len(msg.data)` が 40、注意書きなし | ✅ (pytest `test_integration_ros.py::test_echo_sample_is_not_truncated_up_to_the_size_cap` / `test_server.py::test_echo_sample_endpoint`、vitest `transform/sampleTruncation.test.ts`、E2E `e2e/transform.spec.ts`) |

### Q. リソース監視 (Lv1)

仕様は [resources.md](../design/resources.md)。busy_demo の比較とサンプラーの負荷は実時間の測定 (テスト方針のとおり、余裕を大きくとり、空回りが再現しない環境では理由を付けて飛ばす)。

| ID | 項目 | 期待結果 | 状態 |
|---|---|---|---|
| Q-01 | リーク判定 (合成データ、時刻を注入) | 段差・頭打ち (直線で埋まる / 指数的に飽和)・スパイクは疑いにならず (段差は「様子見」が出て消える)、一定速度 3 MB/分は 20 分以内に疑い (速さ ±25%、継続時間つき)、0.1 MB/分 (揺れ中) は 6 時間スケールで検出、加速する増加も検出、揺れだけは 12 時間 × 3 種類 × 3 回で誤検出なし、増加が止まれば疑いが消える、ウォームアップは起動時刻から数える、プロセスごとに独立、`retain`。揺れの推定は一定の傾き・段差に影響されない。検出できる最小速度の表 (スケール × 揺れ 3 段階) を実測値で固定 (`test_detection_limits`)、その 1/10 では検出しない | ✅ (`test_leak_detector.py`) |
| Q-02 | ノード ⇄ プロセスの対応づけと区分 | Launcher の exact は実行ファイルのプロセス、コンテナの 2 ノードは同じプロセスを共有、他のノードは argv の `__node:=` (ラッパーでなく本体、推定)、argv は Launcher の時刻による推定より優先、プログラム名は 1 つだけのときのみ (他 PC のノードは対応づけない)、Launcher が起動設定しか知らなければ起動設定全体。区分: サーバー (とその `ros2 run` ラッパー)・計測ノード・ビルド・補助・入力ノード (roshanavi 自身)、起動設定 (ROS ノード)、LTTng はトレース中だけ自身 | ✅ (`test_resources_unit.py`) |
| Q-03 | 内訳とノードの値 | PC 全体の CPU を ROS / 自身 / その他に分け、その他の上位の名前、その他は負にならない、起動設定全体の合計と範囲 (`scope`) | ✅ (`test_resources_unit.py`) |
| Q-04 | `/proc` の読み取り (偽の `/proc`) | `stat` の名前に空白や括弧があっても読める、CPU 時間・起動時刻・RSS、自分のユーザーだけ / root は全部、CPU% は差分、I/O の速さ、USS (`smaps_rollup`)、`python3 スクリプト` / `-m モジュール` / 15 文字で切れた名前の表示名 | ✅ (`test_resources_unit.py`) |
| Q-05 | `/proc/net/snmp` と PC 全体 | UDP のカウンタの読み取り、壊れた・無いファイル。コアごとの CPU、loopback を除いた NIC の速さ・取りこぼし、メモリ、ボリュームのデバイス (最長一致、tmpfs は不明)、UDP の直近 60 秒の増加 | ✅ (`test_resources_unit.py`) |
| Q-06 | 診断 (ディスク・UDP・リーク) | 録画と同じしきい値で警告 / 不足 (割合でも)、録画中かどうか。UDP 溢れ + 大きなトピックの取りこぼしで `udp_rcvbuf` (トラフィックは溢れたときだけ読む)、取りこぼしが無ければ診断にしない (件数はリソースタブだけ)、リークの疑いの項目 | ✅ (`test_resources_unit.py`) |
| Q-07 | 接続先 (偽の `/proc`) | アドレスの復号 (IPv4 / IPv6)、LISTEN と未接続の UDP は数だけ、fd とソケットの突き合わせ、表の読み直しはソケットが変わったときと 5 秒ごとだけ、fd のリンク先の読み直しは fd が変わったときと 5 秒ごとだけ、開始・終了のイベント (最初の 1 回は基準)、中身のフィールドを持たない。逆引きは待たずに返し、キャッシュ (失敗もキャッシュ)、loopback は問い合わせない、止められる | ✅ (`test_resources_unit.py`) |
| Q-08 | GPU (偽の NVML) | pynvml が無い / ドライバが無いときは理由付きで無効、デバイスの値とプロセスごとの GPU メモリ、プロセスごとの一覧が空 (WSL2) | ✅ (`test_resources_unit.py`)。実機の NVML は未確認 👀 (Docker には GPU を渡していない) |
| Q-09 | シナリオの `resources` / `mem_growth` (スキーマと判定) | 既定値・相対ノード名・往復、上限が無い / 名前が不正 / 未知のキー / `for` が 10 秒未満は行番号付きの誤り。CPU は平均 (一瞬の負荷では落ちず、最大も報告)、メモリは最大、見つからない、推定の注記、再起動をまたぐ CPU、増え方の合否、途中の再起動は判定しない、要約の文 | ✅ (`test_resources_scenario_unit.py`) |
| Q-10 | 実ノード: Launcher の起動設定が exact で CPU > 0 | `busy_demo_driver` を名前付きで起動 → `/api/resources` で exact・launcher・CPU > 0・スレッド・fd・RSS、ラッパーも同じ起動設定、UDP ソケットの数、自身の区分、履歴と `/ws/live` のバッジ | ✅ (`test_resources_ros.py`) |
| Q-11 | 実ノード: busy_demo の CPU を監視で見る | multi + default と multi + off を順に起動し、1 Hz の値の中央値を比べる: off < 50%、default ≥ 30% かつ off の 3 倍以上 (実測 93% と 8%)。空回りが再現しなければ理由付きで飛ばす | ✅ (`test_resources_ros.py`) |
| Q-12 | サンプラーの負荷 | 50 プロセス (すべて詳しく見る最悪の場合) で 1 コアの 4% 未満 (目標 2% 未満。実測 1.5% 前後。デモのラボでは 0.2%) | ✅ (`test_resources_ros.py`) |
| Q-13 | API と WebSocket はミドルウェアの内側 | 不正な Host は 403、`/ws/resources` は不正な Origin / Host で切断、正しい接続でスナップショットが届く、`scope` の検査 (422)、空のノード名 (400) | ✅ (`test_resources_ros.py`) |
| Q-14 | 実ノード: シナリオの判定 | CLI: talker で `resources` と `mem_growth` が成功 (exact)、`mem_max_mb: 1` で失敗、いないノードは「見つかりませんでした」。サーバー: セットアップのプロセスは exact。サンプル `busy_cpu.yaml` が成功し、`qos_events: default` にすると「CPU が上限を超えました」で失敗 (空回りが再現しなければ飛ばす) | ✅ (`test_resources_ros.py`) |
| Q-15 | 画面の純ロジック (vitest) | 負荷の色分け (40% / 80%)、バッジの文 (推定)、増え方の文、プロセス・接続の持ち主の文、グループ分けと並び、内訳の帯 (100% を超えない)、スパークラインの値、地図の要素に `load` / `leak`、バッジの行が増えたら配置し直し (数字が変わるだけならしない)、`/ws/live` の `resources` を保持、診断の文 (リークは速さと継続時間・roshanavi 自身の書き方、ディスク、UDP)、リークの疑い / 様子見の注記と数字の丸め と選ぶ対象、シナリオのステップの文とラベル | ✅ (`resources/model.test.ts`、`graph/diff.test.ts`、`scenarios/editSteps.test.ts`、`scenarios/messages.test.ts`) |
| Q-16 | E2E: 地図のバッジとリソースタブ | busy_demo の multi + default を起動 → 地図のノードのラベルに `CPU` (推定ではない)、空回りが出れば光の色が mid / high → ノードを選ぶと右ペインに CPU・RSS・スパークライン → リソースタブに PC 全体・「この PC だけ」・ディスク (/data)・GPU・内訳・ROS ノードの行・サーバー本体・計測の負荷 → ノード名で地図に戻る | ✅ (`e2e/resources.spec.ts`、[resources-map.png](../images/resources-map.png)、[resources-tab.png](../images/resources-tab.png)) |
| Q-17 | E2E: リソースのシナリオ | シナリオタブでサンプル `busy_cpu` を実行 → 3 ステップ成功、CPU の平均と MB/分 の説明 | ✅ (`e2e/resources.spec.ts`、[resources-scenario.png](../images/resources-scenario.png)) |
| Q-18 | メモリリークの疑いが地図・診断パネルに出る (実プロセス) | 17 分以上メモリを一定の速さで増やし続けるノードで「リークの疑い」 | ⬜ (判定は Q-01 の単体テストのみ。実時間で 17 分以上かかるため自動テストなし) |
| Q-19 | UDP 受信バッファ溢れの案内 (実環境) | 大きな画像を `--monitor-heavy` で監視し、受信バッファを小さくして溢れさせると `net.core.rmem_max` の案内 | ⬜ (判定は Q-06 の単体テストのみ。E2E のコンテナでは RcvbufErrors が実際に増え、リソースタブに橙色で出ることを目視で確認 👀) |
| Q-20 | 自分以外のユーザーのプロセスを一覧しない (非 root) | 非 root で起動すると他のユーザーのプロセスが一覧に出ない | 🟡 (単体テストの読み取り関数で確認。Docker は root で動くため実機は未確認 👀) |

### R. ディストロ対応

Jazzy・Lyrical が正式対応、Kilted は動作確認のみ (2026-10-18 に 1 回。継続的には確認しない)。版の一覧は [dependencies.md の 0. ディストロごとの主な版](dependencies.md#0-ディストロごとの主な版)。

| ID | 項目 | 期待結果 | 状態 |
|---|---|---|---|
| R-01 | ディストロの切り替え | `ROS_DISTRO` でベースイメージ・`ros-<distro>-*` パッケージ・source する setup が変わり、イメージは `roshanavi:dev-<distro>`。既定 (jazzy) の手順は変わらない | ✅ (jazzy / lyrical / kilted でイメージを作り、テストが通る) |
| R-02 | Jazzy のバックエンド全体 | gtest + pytest がすべて通る | ✅ 2026-10-18: gtest 12 + 11、pytest 1090 passed |
| R-03 | Lyrical のバックエンド全体 | gtest + pytest がすべて通る | ✅ 2026-10-18: gtest 12 + 11、pytest 1088 passed / 2 failed。失敗した `test_function_ros.py::test_module_that_does_not_import_yet_waits_for_a_fix` (関数ノードが SIGINT で止まらず SIGKILL) と `test_scenario_ros.py::test_function_node_example` (2 秒以内に届かず) はどちらも単独で 2 回通る (タイミングの揺れとして報告。前者は Lyrical で 3 回中 1 回) |
| R-04 | Kilted のバックエンド全体 (動作確認のみ) | gtest + pytest が通る | ✅ 2026-10-18: gtest 12 + 11、pytest 1089 passed / 1 failed (`test_scenario_ros.py::test_pre_subscription_catches_an_immediate_response`、0.3 秒の判定。単独で 2 回通る)。この日の途中の版でも 1 回 1082 passed |
| R-05 | E2E (Jazzy / Lyrical) | `scripts/e2e.sh` が両方で通る | ✅ 2026-10-18: Jazzy 39 passed、Lyrical 39 passed (`ROS_DISTRO=lyrical scripts/e2e.sh`。最初は 16 failed: R-12・R-13 で直した) |
| R-06 | pydantic 1.10 / 2 の両対応 | 同じモデル定義で、エラーの種類・文面・場所 (`loc`) が 1.10 系と同じ (上限の値、Literal の選択肢、Union の中の型名を落とす、None、検証関数の ValueError)。正規表現は両方で Python の re (`$` の意味が同じ)。数値を文字列の項目に入れると文字列になる (1.10 系と同じ) | ✅ (`test_pydantic_compat.py` を両方で実行) |
| R-07 | rclpy 10 の `MessageInfo.publisher_gid` (dict) | `{'data': bytes}` の形でも bytes の並びでも gid になる。以前は購読のコールバックで例外になり executor のスレッドが止まった | ✅ (`test_traffic_rate.py`) |
| R-08 | uvicorn 0.29 以降のシグナルの再送 | SIGTERM / SIGINT / SIGHUP でサーバーを止めても Launcher の子が残らない (uvicorn が終了後に同じシグナルを送り直すため、以前は `finally` の前に落ちていた) | ✅ (`test_launcher_shutdown.py` を両方で実行) |
| R-09 | 取り消された WebSocket の後片付け | タスクが取り消し済みでも、画像・音声ビューアとエコーの購読解除、ブラウザ入力の終了が 1 回だけ走る (Starlette 0.50 の TestClient は閉じた直後に取り消す) | ✅ (`test_asyncutil.py`、`test_media_viewer.py`) |
| R-10 | babeltrace2 2.1.2 の metadata の fd | 2.1.2 では解析の子を入れ替えなくても fd が増えない (11 チャンクで 4 本のまま。2.0.5 は 1 チャンクごとに 1 本増える)。入れ替えの仕組みは 2.0.x のために残す | 👀 (2026-10-18 に手動で確認。入れ替えありの回帰テストは `test_tracing_fds.py`) |
| R-12 | rmw の付属トピック (`<topic>/_buf_cpu`) | Lyrical の rmw_fastrtps は、バイト列を持つ型 (AudioDataStamped など) を C++ で購読すると隠しトピック `<topic>/_buf_cpu` を足す。roshanavi はこれを一覧・地図・計測の対象にしない (以前は計測ノードがそれを購読して `/a/_buf_cpu/_buf_cpu/...` が 1 秒に 1 段ずつ増え、名前が長すぎて rclpy が例外を出し、地図の更新が止まった)。問い合わせで例外になるトピックが 1 つあっても地図の更新は続く | ✅ (`test_probe_ros.py::test_rmw_companion_topics_do_not_multiply` は修正前の Lyrical で失敗を確認、`test_graph_unit.py`) |
| R-13 | Lyrical のデモ (`/chatter` が `example_interfaces/msg/String`) | Lyrical の demo_nodes_cpp の talker / listener は std_msgs ではなく example_interfaces の String を使う。example_interfaces の String・Bool・整数・小数も「文字列」などのデータの種類として扱う (型はそのまま)。種類だけの関数ノードの入力 (デモの `text_shout`) は既存のトピックの型を使う。チュートリアル「届かない原因を見つけて直す」は受信側を先に起動し、送信側をその型にそろえる。E2E は `/chatter` の型をサーバーに聞いて使う | ✅ (`test_data_kinds.py`、`test_function_unit.py::test_inputs_with_only_a_kind_adopt_the_existing_topic_type`、vitest `tour/fixtures.test.ts`、E2E) |
| R-11 | Python 3.14 | 式の評価器 (`expr.py`、`msg_view.py`) の許可・拒否のテストが通る (削除された `ast.Num` などは使っていない)。警告なし | ✅ (`test_expr.py`、`test_expr_fields.py`、`test_security.py`) |


### S. クラスノード

仕様は [nodes.md#クラスノード](../design/nodes.md#クラスノード-状態を持つ処理をそのままノードにする)。単体は `test_class_unit.py` (ROS のグラフ不要)、実ノードは `test_class_ros.py`、画面のロジックは `classForm.test.ts`、E2E は `web/e2e/class.spec.ts`。

| ID | 項目 | 期待結果 | 状態 |
|---|---|---|---|
| S-01 | クラス・`__init__`・メソッドの静的な一覧 (unit) | import せずに、`__init__` の引数 (型ヒント・既定値・種類)、公開メソッド (シグネチャ・戻り値・「引数なしで呼べる」)、フックの有無を読む。`_` で始まるメソッドと `staticmethod` は出さない。パラメータにできない型 (画像・バイト列) の引数は種類 `null` | ✅ |
| S-02 | 引数の種類の対応 (unit) | `int` / `float` / `str` / `bool` / `list[float]` → 数値の並び / `list[str]`・`dict` → JSON / `Optional[int] = None` / 型ヒントなし (既定値の型) / 型ヒントも既定値もない → パラメータにしない、の 23 通り | ✅ |
| S-03 | パラメータの値の変換は厳密 (unit) | 整数に小数・bool・文字列、小数に bool、JSON の壊れた文字列、数値の並びに文字列を拒否 (理由は平易な文) | ✅ |
| S-04 | 仕様の検査 (unit) | 何もつながない・メソッドの重複・フックは操作にもつなぎにもできない・入力数・周期の rate_hz・出力のキー (全部に付ける / 重複しない)・入力と同じ出力・`_` で始まるメソッド・roshanavi のモジュールを拒否。設定 YAML の往復 | ✅ |
| S-05 | 受信 → メソッド → 送信 (unit) | 値が積み上がる、`None` は送らない・例外は場所付きで数えノードは続く、戻り値の型違いは変換のエラー、複数入力は最新値を結合 (trigger)、周期は経過秒を引数があるときだけ渡し、遅いメソッドで周期が積み上がらない | ✅ |
| S-06 | dict の戻り値 (unit + 実ノード) | キーごとに別トピック (`RunningStats` の mean / count / max)、無いキー・`None` は送らない、出力に無いキーは `ignored_keys`、dict 以外は変換のエラー | ✅ |
| S-07 | 操作メソッド (unit + 実ノード) | トピック `/<node>/reset` (`std_msgs/Empty`) で呼ばれ、状態に回数・最後の時刻・戻り値・エラー (場所付き) が残る。登録外のメソッドは呼ばない。記録が変わるたびに状態ファイルへ即書く | ✅ |
| S-08 | パラメータ: 宣言と開始値 (unit + 実ノード) | `ros2 param list/get` に `__init__` の引数が出る (spec の値 → 既定値)、`None` の既定値・必須で値なしは未設定、`params` の不正・存在しない名前は警告、必須で値なしは「初期化に失敗」と理由 → パラメータを設定すると動き出す | ✅ |
| S-09 | パラメータの変更 (unit + 実ノード) | `on_param_change` があれば呼ぶ (インスタンスと状態は残り、例外は理由付きで断る)、無ければ新しい値で作り直して状態リセット (古い方に `close()`、画面用の通知 `reset` / `param`)、`__init__` が断る値・型違い (`ros2 param set` の応答) は古いインスタンスのまま | ✅ |
| S-10 | ホットリロード (unit + 実ノード) | 既定はインスタンスを作り直して状態リセット (通知 `reset` / `reload`、古い方に `close()`)、`get_state` / `set_state` があれば引き継ぐ (通知 `kept`)。構文エラー・`__init__` の例外・`get_state` / `set_state` の例外は古いインスタンスのまま `reload_error` と場所、直すと `running`。`__init__` の引数が変わればパラメータを宣言し直す | ✅ |
| S-11 | 起動時の失敗 (unit + 実ノード) | 読めないモジュールは `import_error` で待ち、直すと動く。`__init__` が例外なら `init_error` (場所と理由)。起動直後は `starting`。ノードは終了しない | ✅ |
| S-12 | `close()` / `shutdown()` (unit + 実ノード) | 停止時に呼ぶ (`close` が無ければ `shutdown`)、例外は記録するだけ、**固まった `close()` は 3 秒で諦める** (テストでは 0.3 秒に縮めて確認)。実ノードの停止ログに `Counter stopped at 101` | ✅ |
| S-13 | 呼び出しは 1 本のスレッド (unit) | 6 スレッドから受信・操作・パラメータ変更を同時に浴びせても、利用者のコード (`__init__` / メソッド / `close`) は作業スレッド 1 本だけで、重なりが 0 (テスト用のクラスが数える)。キューが溢れたら捨てて `dropped` に数える | ✅ |
| S-14 | コード書き出し (unit) | 通常の rclpy ノードと lifecycle ノードの両方が、複数のメソッド・dict 出力・複数入力・周期・操作メソッド・パラメータ込みで `compile()` を通る。値は検証済みのものだけを `repr()` で埋め込む (クォートを含む値でも壊れない)、制御文字のディレクトリは拒否、クラス・フックの有無で生成が変わる、利用者のファイルは上書きしない (409) | ✅ |
| S-15 | 書き出したコードがツールなしで動く (実ノード) | 通常のノード: 入力 → 出力 (平均)、`/<node>/reset`、`ros2 param set` (`on_param_change`)。lifecycle: 未設定の間は購読が無く → configure → activate で購読が現れ出力 → deactivate で購読が消え → cleanup → 再 configure / activate でやり直し | ✅ |
| S-16 | API・地図・ノード一覧・プロジェクト (実ノード) | 一覧に `classes[]`、`POST /api/classes?start=true` → 役割 function・種類 class・`classes:` に保存・状態、`POST .../call` で記録 (`count`)・登録外のメソッド 404・不正な名前 422・未登録の id 404・止まっているときは 409 `not_running`、ノード一覧の由来、`/<node>/reset` が診断の「送り手なし」に出ない | ✅ |
| S-17 | launch への書き出し (実ノード) | `executable='function'` の launch でクラスノードが動く | ✅ |
| S-18 | シナリオ `call` ステップと `class` セットアップ (unit + 実ノード) | 文面の検査 (必須・形式・使えないキー、相対名は絶対名に、YAML の往復)、`MovingAverage` で平均 → reset → 平均が最初から、reset を呼ばない版は失敗、存在しないノード・メソッドと、操作メソッドが例外になる場合は平易な説明で止まる。サンプル `class_moving_average.yaml` | ✅ |
| S-19 | 画面のロジック (vitest) | クラス名からノード名 (`MovingAverage` → `moving_average`)・最初のメソッドの仮決め・出力トピックの追従、パラメータの値の検査 (種類ごと、必須、既定値と同じなら保存しない)、dict 出力のキー、メソッドの使い方の切り替え、編集時の復元と往復、平易なエラー文、右クリックの「<メソッド> を呼ぶ」(止まっていれば無効と理由)、シナリオの `call` | ✅ |
| S-20 | E2E: MovingAverage をクラスノードとして作る | 「クラス」→ モジュール → クラス (シグネチャ付き) → `window` は既定値 5 を 3 に → `process` は「トピックにつなぐ」、`reset` は「操作メソッド」→ 作成 → 地図の役割 function、`classes:` に保存 → 数を送ると平均 → 右クリック「reset を呼ぶ」→ 次の値が単独の平均になる → 右ペインのボタンと「最後の呼び出し」。スクリーンショット [`class-node-dialog.png`](../images/class-node-dialog.png) | ✅ |
| S-21 | E2E: 作り直しの通知 | `Counter` のパラメータを変えると右ペインに「状態をリセットしました」、現在値が更新される | ✅ |
| S-22 | Lyrical での実行 | 上の単体・実ノードのテストが Lyrical (rclpy 10、Python 3.14、pydantic 2) でも通る。`LifecycleNode` の API (`create_lifecycle_publisher`、`on_configure` ほか) は Jazzy と同じ | ✅ |
| S-23 | 入力だけ・出力だけのメソッド (API と JSON) | 仕様に `inputs` / `outputs` / `methods` / `actions` の空のリストを `[]` で返す (`GET /api/targets`・`/api/project`)。プロジェクトファイルには書かない。保存 → 読み直しで同じ。pydantic 1 (Jazzy) と 2 (Lyrical) の両方 | ✅ (`test_api_spec.py`) |
| S-24 | 入力だけ・出力だけのメソッドの口 (vitest) | 受けるだけの `on_pose` (入力 1・出力 0) と周期で出す `render` (入力 0・出力 1) の口、リストが丸ごと無い仕様 (古いサーバー)・メソッドも操作も無いクラス・入力の無い関数・入力の無い変換ノードでも落ちない。つなぐ計画も立つ。直す前は `Cannot read properties of undefined (reading 'map')` で 4 件落ちる | ✅ (`wiring/portsEmptyLists.test.ts`) |
| S-25 | E2E: 入力だけのメソッドと周期で出すメソッドを持つクラス | API が `outputs: []` / `inputs: []` を返し、地図が落ちずに `on_pose` の入力口と `render` の出力口が出る (`pageerror` なし) | ✅ (`class-sink-source.spec.ts`) |

### T. 自分のコードを関数・クラスノードにする (置き場所・ひな形・依存)

仕様は [user-code.md](../design/user-code.md)。状況 U1〜U7 の実際のディレクトリ構成を、テストの中で作る (`test/user_code_fixtures.py`: ament_python / ament_cmake_python / flat / src レイアウト / pip が残すのと同じ dist-info 付きの site ディレクトリ / venv (`--system-site-packages --without-pip`) / 拡張モジュール (cc でビルド) / git のサブモジュール (git で作る))。単体は `test_user_code_scopes.py`・`test_user_code_report.py`・`test_user_code_loader.py`・`test_user_code_deps.py`・`test_user_code_scaffold.py`、実ノードと API は `test_user_code_ros.py` (と `test_user_code_scaffold.py` の最後)、画面のロジックは `function/codeLocations.test.ts`、E2E は `web/e2e/usercode.spec.ts`。

| ID | 項目 | 期待結果 | 状態 |
|---|---|---|---|
| T-01 | A: ament_python と ament_cmake_python (unit) | `<pkg>/<pkg>/`、`ament_python_install_package(${PROJECT_NAME})`、`PACKAGE_DIR python/<名前>` のモジュールが一覧・解決・関数の一覧に出る (`scope: workspace`、ワークスペースからの相対パス) | ✅ |
| T-02 | B: flat / src / フォルダ自体がパッケージ (unit + 実ノード) | 登録しなければ出ない。登録すると一覧に出て (`scope: code_path`、実際の絶対パス)、相対パスはワークスペースから。src レイアウトの関数ノードが相対 import 付きで動き、**同じパッケージの別ファイル**を保存すると読み直す。flat のクラスノードが動く | ✅ |
| T-03 | C: インストール済み・名前空間パッケージ・editable・拡張モジュール (unit + 実ノード) | dist-info 付きのパッケージとその下のモジュール、2 か所に分かれた名前空間パッケージ (それ自体は選べない)、setuptools の editable (`MAPPING`) を import せずに見つける。path finder と同じ順 (パッケージ → .so → .py、名前空間は最後)。拡張モジュールだけのものは `listable: false` で関数名を手入力し、実ノードで動く (`HI!!`)。インストール済みは読み直さない (通知) | ✅ |
| T-04 | 名前の衝突 (unit) | A と B、B と C で同じ名前ならソース側 (A → B → C の順) を使い、理由に `name_collision`、C は `shadowed`。標準ライブラリ・ノードが使う名前 (`json`、`numpy`) のパッケージは読まない。pytest が読み込み済みの `pluggy` と同じ名前の B のパッケージはノードの中で拒否 | ✅ |
| T-05 | シンボリックリンク (unit) | A・B とも、根の内側を指すもの (別のパッケージのファイル) は使え、外を指すもの (ファイル・パッケージのフォルダ) は一覧にも解決にも出ない。理由に `outside_symlink` | ✅ |
| T-06 | サーバーは import しない (unit) | A・B・C のモジュールと `__init__.py` の先頭でファイルを書く仕掛けが、一覧・説明・「コードの場所」のどれでも動かない | ✅ |
| T-07 | 見つからない理由の全部 (unit) | `__init__.py` が無い、名前空間パッケージ (A・B)、package.xml の隣の .py、package.xml の無いフォルダ、構文エラー (ファイル・行・内容)、関数もクラスも無い (`if __name__` の中の名前付き)、`_` で始まる名前だけ、外向きのリンク、登録したフォルダが消えた・空、登録したモジュールが無い。理由以外のものは出ない。`.git` (ディレクトリもサブモジュールのファイルも) は辿らない | ✅ |
| T-08 | git のサブモジュール (unit、git で fixture を作る) | `--recurse-submodules` 無しで clone したワークスペースは「中身がありません」とコマンド `git submodule update --init --recursive` と実行する場所。同期済みは普通の ROS パッケージとして一覧に出る。B の中のサブモジュールも同じ。`.gitmodules` の `path` が外を指しても無視。PATH から git を外しても動く (git を実行しない) | ✅ |
| T-09 | コードの場所の登録の検査 (unit + API) | `/`・`/usr`・ホーム・data フォルダ (中・それを含む)・`.git` の中・制御文字・空・存在しないフォルダを拒否 (`invalid_code_path`)。プロジェクトファイルに `code_paths:` / `installed_modules:` を保存・読み込み (空なら書かない)、重複・21 個以上・不正なモジュール名・`roshanavi`・**標準ライブラリ (`os`、`subprocess`、`builtins`)** を拒否 (pydantic 1 / 2) | ✅ |
| T-10 | ひな形 (unit) | 8 つのファイル、package.xml に依存の例 (コメントの中に `--` が無く XML として読める)、関数 `convert(text: str) -> str` とクラス `Processor` が静的に一覧できる。名前の規則 16 通りを拒否、既にあるフォルダ (リンクも) は上書きせず 409、ROS パッケージ・Python パッケージの名前と重なれば 409、途中で書けなくなったら作ったものだけを消して 403 | ✅ |
| T-11 | ひな形 → そのまま動く → ビルド → テスト (実ノード) | 作った直後に (ビルドなしで) 関数ノードとして `HI…`、クラスノードとして `No.1 …` (通し番号が増える)、`colcon build --packages-select` が通り site-packages に入る、生成した pytest が README の手順 (`cd src/<名前> && python3 -m pytest test`) でもワークスペースの根からでも 2 件通る | ✅ |
| T-12 | 足りないライブラリ (unit + 実ノード) | 読み込み時・呼び出し時・`raise ... from` の `ModuleNotFoundError` に `missing_module`、自分のパッケージの中のモジュールが無いときは付けない。実ノード: OpenCV を import するモジュールは `import_error` で場所と `missing_module: cv2`、requirements.txt の照合、直して保存すると動く (numpy は rclpy 自身が使うため、ROS 2 のノードで欠けることは無い) | ✅ |
| T-13 | rosdep の対応づけ (unit、rosdep のデータベース付き) | `numpy` → `python3-numpy`、`cv2` → `python3-opencv` (apt)、無いもの → `not_found` → venv の手順。HOME を空にすると `unavailable` (`no_database`) で未確認の候補と両方の手順、rosdep が無ければ `rosdep_missing`、時間切れ。pip のキーは使わない。結果はキャッシュ。実行するのは `rosdep resolve` だけ (pip は実行しない) | ✅ |
| T-14 | 案内の中身 (unit + API) | ワークスペースのパッケージなら `package.xml` の実際のパス・足す 1 行・既に書いてあるか (コメントは数えない)・`rosdep install --from-paths <実際のパス>`。B なら package.xml は無く apt の 1 行、requirements.txt があれば `pip install -r <実際のパス>`、pip の名前が違えばそう書く、venv の中なら `<その python> -m pip install` | ✅ |
| T-15 | requirements.txt の照合 (unit + 実ノード) | 名前の正規化、足りないもの・版が合わないもの・入っているもの、`-r`・URL・この環境向けでない行は確かめない。packaging が無いときは入っているかだけ。読み込みに失敗したときも照合する | ✅ |
| T-16 | venv で動かす (実ノード) | venv (`--system-site-packages`) が有効な環境の ProcessManager は `ros2 run --prefix <venv>/bin/python3` で起動し、venv にだけ入れたライブラリを関数ノードが使える。ノードの状態に venv の Python、照合で venv のライブラリが入っている。C の場所の解決もノードの Python の検索パスで行う (サーバーの `sys.path` には無い)。venv が無ければコマンドは今までどおり | ✅ |
| T-17 | 通知 (unit) | 読み込みに 1.1 秒 → `slow_import`、rclpy を import → `imports_rclpy`、パッケージの中の .so → `extension_no_reload`、作成画面ではモジュールの `skipped` (`_` / async / `if __name__`) と rclpy の通知 | ✅ |
| T-18 | API と安全の検査 (API) | `locations` の GET / PUT (保存、不正は 4xx)、`modules` の `scope`、`scaffold` 201 → 409 → 不正な名前 400、作った関数と B のモジュールが API から起動して動く、`dependency`。新しいルートも Host / Content-Type の検査の内側 (403 / 415) | ✅ |
| T-19 | 画面のロジック (vitest) | パッケージ名・フォルダ・モジュール名の検査、追加・削除 (元を変えない)、すべての理由と通知に文がある (`{}` が残らない)、設計の表どおりの文、置き場所の文、範囲ごとのグループ、requirements の要約、rosdep の手順 (書いてある / オフライン / package.xml なし / キーなし) | ✅ |
| T-20 | E2E: 理由 → ひな形 → 書き換え → 出力が変わる | `__init__.py` の無いフォルダに理由と実際のパス、置き場所、Python。不正な名前は断られ、`e2e_logic` を作ると関数が選ばれた状態 → `/chatter` で `HELLO WORLD` → テストが `logic.py` を書き換えると `edited: Hello World`。OpenCV を使う関数ノードの右ペインに ① `python3-opencv` と ② venv。スクリーンショット [`user-code-locations.png`](../images/user-code-locations.png)・[`user-code-scaffold.png`](../images/user-code-scaffold.png)・[`user-code-dependency.png`](../images/user-code-dependency.png) | ✅ |
| T-21 | Lyrical での実行 | T の単体・実ノード・API のテストが Lyrical (Python 3.14、pydantic 2) でも通る (77 件) | ✅ |
| T-22 | 登録した場所 (B) をライブラリとして使う (unit + 実ノード) | A の `import <ライブラリ>` が、登録した B (flat・src・フォルダ自体がパッケージ) から動く (関数・クラスとも、実ノードで出力まで確認)。登録を外すと `missing_module` と rosdep / pip の案内 + 「登録すると import できます」、登録済みなのに無ければ「登録した場所 … に見つかりません」(rosdep を尋ねない)、起動後に登録したなら「再起動」。標準ライブラリ・ノードが使う名前 (`json`・`winreg`・`audio_common_msgs`)・`tests` は依存としても出さず、環境のライブラリが先、外向きのシンボリックリンクは拒否、プロジェクトの `.venv` のモジュールは読み直しで外さない。依存ライブラリの書き換えはホットリロードされ (実ノードで `reloads` が増える)、壊れていれば古いまま。C のコードから B のライブラリも使える。サーバーのプロセスに finder は入らない | ✅ |


### U. launch の引き取り (`--launch`)・強制終了の後始末・ノード一覧の削除

仕様は [integration.md](../design/integration.md)、[launcher.md#子プロセスの後始末](../design/launcher.md#子プロセスの後始末-12)。fixture は `test/takeover_fixtures.py` (偽の install に置いた `tk_demo` パッケージ: 引き継ぐもの・元どおりにならないものをすべて含む `tk_full.launch.py` (+ include・パラメータファイル)、ノードだけの `tk_simple.launch.py`、OnProcessExit → Shutdown の `tk_exit.launch.py`)。`test_takeover.py`・`test_leftovers.py`・`test_registry_delete.py`、vitest `takeover/model.test.ts`・`nodelist/remove.test.ts`、E2E `web/e2e/takeover.spec.ts`。

| ID | 項目 | 期待結果 | 状態 |
|---|---|---|---|
| U-01 | ノードごとの引き取り (実ノード) | include 先も含む 4 ノードが `kind: run` (`takeover: true`・`imported_from`)、`--mine` のノードは mine、`respawn` → `auto_restart`、`SetEnvironmentVariable` と `additional_env` → `env`、引数 `rate:=7` とパラメータファイルの値が `params`。残り (TimerAction・イベント・ExecuteProcess) は `takeover_rest.launch.py` 1 つ。報告: 引き継ぎ `env` `respawn`、元どおりにならない `required` (/tk_listener)・`respawn_delay`・`events`・`timer_order`・`conditions_fixed`、`suggest_whole`。すべて起動し、プロジェクトに `takeover:` | ✅ |
| U-02 | 残りの部分は別に起動するノードを起動しない (実プロセス) | 残りの部分のプロセスに TimerAction のノード (`tk_late`) と `sleep 600` があり、`__node:=tk_talker` などは無い。tk_talker のプロセスの環境に `TK_COLOR` / `TK_SHAPE` | ✅ |
| U-03 | 起動し直し (冪等) | 同じファイル・引数で起動し直すと同じ ID・役割のまま (重複なし、`pending` なし)。引数を変えると同じ ID のまま設定が変わる | ✅ |
| U-04 | 止めている間の変更 | 起動し直すと前回の内容で動き、`pending.reason: changed_since_last` (追加 /tk_c・なくなる /tk_b)。適用すると入れ替わり、同じ `preview_id` は 2 回目 404 | ✅ |
| U-05 | 動いている間の変更の検出と取り込み直し | launch ファイルにパラメータとノードを足すと `pending.reason: file_changed`、変わったファイル、追加 /tk_new・変更 /tk_a (`params`)。適用すると tk_a だけ再起動 (tk_b の pid は同じ)、tk_new が起動 | ✅ |
| U-06 | 中身の同じ保存 | `touch` だけでは `pending` にならない (解析し直して差分なし) | ✅ |
| U-07 | 全体モード | `kind: launch` 1 つ (`--mine` で mine)、報告は空。OnProcessExit → Shutdown で launch が終わり `exited` (元どおりに動く) | ✅ |
| U-08 | 入力の検査 | `../etc/passwd`・不正なパッケージ名は拒否、無い launch ファイルは `state: error` (`unknown_launch_file`) | ✅ |
| U-09 | API | `GET /api/takeover`、余計なキーは 4xx、`POST /api/takeover/start` (demo_system → 2 ノード + 残り)、`check` で差分なし、知らない `preview_id` は 404 | ✅ |
| U-10 | SIGKILL → `ros2 run roshanavi cleanup` (実サーバー) | 3 つのターゲット (run・launch・ダミー) を記録してからサーバーを SIGKILL。直接の子は PR_SET_PDEATHSIG で止まり、孫が残る。`--dry-run` は一覧だけ、`cleanup` で全部止まり記録が消える。2 回目は「Nothing to clean up」 | ✅ |
| U-11 | SIGKILL → 次の起動のバナー (実サーバー) | 次に起動したサーバーの `GET /api/leftovers` が残ったプロセスを数え、`POST /api/leftovers/stop` で全部止まり 0 になる | ✅ |
| U-12 | 記録の照合 (unit) | 起動時刻の違う記録 (PID の再利用) は残ったプロセスにせず、ファイルを片付ける。一致すれば残ったプロセスになり止められる。通常の終了で記録が消える | ✅ |
| U-13 | 起動したスレッドが終わっても子は生きる | 短命のスレッドから起動した子が 1 秒後も動いている (PR_SET_PDEATHSIG はスレッドの終了で送られるため、専用のスレッドから起動する) | ✅ |
| U-14 | 削除と元に戻す (unit + API) | 動いている起動設定と止まっているダミーを削除 → 止まって登録から消え自動保存、元に戻すと同じ設定で登録され、動いていたものだけ起動 (別の pid)。2 回目・期限切れは `undo_expired`。知らない ID が混ざると何も消さない。API の不正な ID は 4xx | ✅ |
| U-15 | 画面のロジック (vitest) | バナーの順と「あとで」、引き継ぎ・元どおりにならない動作の文、差分の項目名、削除の計画 (起動設定ごとに 1 回、一緒に止まるノード、外部は削除しない、安全の文、取り込み直すと戻る) | ✅ |
| U-16 | E2E: launch ファイルの変更 → バナー → 差分 → 取り込み直し | E2E のワークスペースにパッケージを書いてビルド、`POST /api/takeover/start`、launch ファイルにノードを足すと「launch ファイルが変更されました。取り込み直しますか?」→ 差分に /e2e_tk_listener → 取り込み直すと一覧に出る。スクリーンショット [`takeover-changed-banner.png`](../images/takeover-changed-banner.png)・[`takeover-diff.png`](../images/takeover-diff.png) | ✅ (全体の実行で 1 回目はビルド前にワークスペースの再走査が無く失敗 → 直して単独で通過) |
| U-17 | E2E: 削除 → 元に戻す | 入力ノードを選んで削除 → 確認に「削除すると止まります」「ソースコード・パッケージ・パラメータファイル・録画は消えません」→ 一覧から消える → 「元に戻す」で戻り動く。外部のノードは選べない。スクリーンショット [`node-list-delete.png`](../images/node-list-delete.png) | ✅ |
| U-18 | Lyrical での実行 | U の pytest (と launch 取り込み・停止・プロセス管理の既存テスト) が Lyrical でも通る (55 件) | ✅ |
| U-19 | turtle_demo を引き取りで動かす | `dev` サービス (`--launch turtle_patrol patrol.launch.py --mine patrol`) で /sim と /patrol が roshanavi のノード (patrol は mine)、API から patrol を止める・起動し直す、ログ、turtle_viz の正方形 | 👀 2026-10-18: 報告は空 (元どおりにならない動作なし)、/sim (dependency)・/patrol (mine)・/turtle_viz が確実で対応づき、patrol の停止で地図から消え、起動・再起動で pid が変わり sim の pid はそのまま、ログに「Side N done」と起動コマンド、`reset` 後 40 秒で正方形 (400×400、外接 136×137 px)。コンテナを再起動しても同じ ID・役割で再利用 (`pending` なし、残ったプロセス 0) |

### V. 地図の上での配線・言葉の総点検・pub/sub の 1 枚絵

仕様は [wiring.md](../design/wiring.md)。互換性の規則はバックエンドと画面の両方を、同じ表 `ros2_ws/src/roshanavi/test/data/wire_compat_cases.json` で検査する。

| ID | 項目 | 期待結果 | 状態 |
|---|---|---|---|
| V-01 | 種類の互換性 (pytest + vitest、共有の表) | 同じ種類はつながる、整数 → 小数・文字列 ↔ JSON は注記つきで許可、小数 → 整数は「小数点以下が失われる」で拒否、専用の型は同じ型だけ、まだ無いトピックは常に可。`GET /api/data-kinds` の `conversions` が同じ表 | ✅ (`test_wiring.py`、`wiring/compat.test.ts`) |
| V-02 | 入力口の変換 (pytest) | 整数のトピック (`Int64`) を小数の入力口が受けると `float` で関数に渡る。出力口は変換できる型を受け付けない (仕様の検査で拒否) | ✅ (`test_wiring.py`) |
| V-03 | つながっていない口 (pytest) | トピック名が空の口は仕様の検査・`validate_function` / `validate_class` を通る、2 つの空の入力は重複にならない、`trigger` にできない、出力が空なら関数は呼ばれて送らない (`skipped`)、コードの書き出しは 409 `unwired_ports` | ✅ (`test_wiring.py`) |
| V-04 | つながっていない口で実際に動く (pytest, ROS) | 出力が空の関数ノードが受信して呼ばれ、送らない。全部空の関数ノードとクラスノードも `running` になる (起動時のログで落ちない) | ✅ (`test_wiring.py`) |
| V-05 | つなぎ口のモデル (vitest) | 関数・クラス・変換・入力ノードだけに口、引数名と種類、クラスはメソッドごと + 操作メソッドのボタン、地図にいないノードは出さない、新しいトピック名の提案 (`/<ノード>/out`、重なれば `_2`)、箱の大きさと線の端 (`tep` / `sep`) | ✅ (`wiring/ports.test.ts`) |
| V-06 | 仕様の書き換え (vitest) | 既存のトピックの型を採用、新しいトピックは種類の既定の型、変換の注記、拒否の理由 (種類・自己ループ・重複・ほかのメソッドの出力・名前)、`trigger` の追従と外したときの `any`、変換ノードは同じ型だけ・入力ノードは同じ種類だけ、変換・入力ノードの口は外せない | ✅ (`wiring/edit.test.ts`) |
| V-07 | 離した先 (vitest) | トピック → つなぐ、空いているところ (出力) → 名前を聞く、入力口を空いているところ・ノードへ → 理由、外部ノード → 「コードの中で決まっている」、出力口 → 入力口はトピックを通す、同じ向きの口どうしは拒否 | ✅ (`wiring/drop.test.ts`) |
| V-08 | キーボードの手順 (vitest) | 一覧は全トピック (つなげないものは理由つきで選べない・後ろ)、出力口は先頭に新しいトピック、つながっていれば「外す」、↑↓ は選べるものだけ、Enter → 確認 → Enter、Esc で戻る・閉じる、新しい名前の編集 | ✅ (`wiring/keyboard.test.ts`) |
| V-09 | 呼ばれ方 (vitest) | 入力 1 つ / 複数 (どれでも・1 つだけ) / 周期 / 変換 / 入力ノードの文、図の行 (呼ぶ・最新の値を使う)、作成画面の値からの組み立て、つながっていない入力はきっかけにできない | ✅ (`wiring/timing.test.ts`) |
| V-10 | 用語集 (vitest) | ROS の用語は公式の言葉 1 つだけ。すべての UI の文言 (ⓘ の説明 `term.*` を除く) と `web/src` のソースに、昔の平易な言葉 (チャンネル・設定値・起動セット・届け方の設定・データの形・名前の付け替え) が出ない (コード表示は除く)。用語集は日本語と英語で同じ構造で、説明は用語で始まる。`<Term>` の説明は用語集から | ✅ (`i18n/glossary.test.ts`) |
| V-11 | 作成画面 (vitest) | トピックが空の口で関数・クラスの仕様が作れる (形の悪い名前は拒否) | ✅ (`functionForm.test.ts`、`classForm.test.ts`) |
| V-12 | E2E: ひな形 → 線でつなぐ → 大文字 | ひな形の関数をトピック空で作る (呼ばれ方「この入力が届くたびに呼ばれます」) → `/chatter` の取っ手から入力口へ引く → 出力口を空いているところへ引き `/wire_fn/out` を作る → エコーと出力口のツールチップに `HELLO WORLD` | ✅ (`e2e/wiring.spec.ts`) |
| V-13 | E2E: 断られる線 | 数値の入力ノードのトピックを文字列の入力口へ引くと「文字列の入力口に、数値 (小数)のトピックはつなげません」、離しても保存されない | ✅ (`e2e/wiring.spec.ts`) |
| V-14 | E2E: キーボード | 入力口で Delete → 外れる (再起動のあともフォーカスは口に戻る)、Enter → 一覧 (数値のトピックは選べず理由つき) → ↓ で `/chatter` → Enter → Enter → つながる | ✅ (`e2e/wiring.spec.ts`) |
| V-15 | E2E: クラスノード・1 枚絵 | デモの `moving_average` に `process` の口と reset ボタン (押すと呼ばれる)、凡例から 1 枚絵が開き Esc で閉じる、チュートリアル「画面の見方」の 2 手順目に 1 枚絵 | ✅ (`e2e/wiring.spec.ts`、`e2e/tour.spec.ts`) |
| V-16 | Chromium 以外・タッチでのドラッグ | Firefox / Safari、タッチ操作 (pointer events) でつなげる | 👀 (未確認: E2E は Chromium のみ) |
| V-17 | スクリーンリーダーの実機確認 | NVDA / VoiceOver でつなぎ口の名前と一覧が読まれる | 👀 (未確認: 読み上げ用の名前は E2E で検査) |
| V-18 | 用語の方針 (pytest `test_wording.py`) | サーバーが画面に返す文 (シナリオのヒント・エラー、クラスノードのパラメータの問題、ひな形の README) に、昔の平易な言葉が出ない | ✅ (`test_wording.py`) |

### W. 中継パイプラインのサンプル・composable container

仕様は [nodes.md#中継パイプライン](../design/nodes.md#中継パイプライン-source--relay--sink51)、[launcher.md#composable container の扱い](../design/launcher.md#composable-container-の扱い-22)、測定は [measurement.md#規模と負荷の限界](../design/measurement.md#規模と負荷の限界-51)。fixture は `test/pipeline_fixtures.py` (生成した spec を書いて launch の起動設定を作る)。

| ID | 項目 | 期待結果 | 状態 |
|---|---|---|---|
| W-01 | ロジックの gtest (ROS なし) | 間引き (`drop_ratio`・`rate_limit_hz`・同じ種で同じ結果)、payload の切り詰め・ゼロ埋め、fan-out (all / round_robin)、連番の欠け、遅延の窓 (p50/p95・上限・古いものの除外) | ✅ (`test_pipeline_logic`、21 件) |
| W-02 | ノードの振る舞い (実プロセス) | stamp・frame_id・連番の引き継ぎ、`payload_bytes`、`rate_limit_hz` で頭打ち、`drop_ratio`、fan-out、合流、`keep_stamp`、sink の遅延・欠落、実行中のパラメータ変更と不正値の拒否、不正な起動値でエラー終了、`count` | ✅ (`test_pipeline_nodes_ros.py`) |
| W-03 | 生成器: 形・規模・配線 | プリセットが 3 / 20 / 200 ノード。どのトピックも送信者 1・受信者 1 以上、段は前向きだけ、パラメータの個数と配線が一致。期待される Hz (合計・drop・rate_limit)。不正な値の拒否 | ✅ (`test_pipeline_gen.py`) |
| W-04 | 生成物の整合 | プロジェクトが roshanavi のスキーマとランチャーの検査を通る。コミットしてある `examples/pipeline_*` が生成器の出力と一致 | ✅ |
| W-05 | launch の組み立て | process は Node が 1 ノードずつ、container は `ComposableNodeContainer` に全ノードを 1 回ずつ (N 個に分割、st / mt、intra-process) | ✅ (`test_pipeline_launch.py`) |
| W-06 | small を両方の方法で起動 | 欠落 0・Hz と遅延が sink で測れる。process は別 pid・`exact`、container は共通の pid・`heuristic`。どちらも 1 グループ | ✅ (`test_pipeline_modes_ros.py`) |
| W-07 | コンテナのノード → コンテナのプロセス、一覧のグループ | 12 ノードが同じ pid・同じグループ | ✅ (`test_container_ros.py`) |
| W-08 | `launch_ros_<pid>` の対応 | コンテナではなく `ros2 launch` のプロセスに対応づく | ✅ (unit + 実機) |
| W-09 | リソースがコンテナ単位 | `component_container` の行が 1 つ、各ノードの値は同じ (`scope: process`) | ✅ |
| W-10 | 確認ダイアログ用の一覧と停止 | `targets.nodes` に全ノード。停止で全部が消えプロセスが残らない。起動し直すと戻る | ✅ |
| W-11 | launch の取り込み | コンテナは「分解できない部分」(中のノード名つき)、全体取り込みが選べる。process モードの同じ launch は全ノードが取り込める。200 ノードの評価が 20 秒以内 (K-34) | ✅ |
| W-12 | 詳細計測モードがコンテナの中のノードごとに測れる | 3 本の列で 20 / 10 / 5 Hz が別々、`unsupported` は `launch_ros_<pid>` だけ | ✅ |
| W-13 | intra-process のコンテナ | 地図・トラフィックには出る (✅)。詳細計測モードは誤って「処理が追いつかない」と出る既知の不具合 (`xfail(strict)` で記録、未修正) | 🟡 |
| W-14 | E2E: medium を開く | 20 ノードが地図に出て、エッジに Hz、実データでも fps > 30 | ✅ (`e2e/pipeline.spec.ts`) |
| W-15 | E2E: コンテナ構成 | 1 グループにまとまり、1 ノードを選んだ停止の確認にコンテナの全ノードが並ぶ | ✅ (`e2e/pipeline.spec.ts`) |
| W-16 | 規模と負荷の限界の測定 (`scripts/bench_pipeline.py`) | 結果の表が measurement.md にある | ✅ (この PC での実測。再実行は手動) |
| W-17 | 重いデータの送受信 (`heavy_source` / `heavy_sink`) | Image / PointCloud2 の型・大きさ・連番、sink の統計 (欠落 0)。不正な `kind` でエラー終了 | ✅ (`test_pipeline_nodes_ros.py`) |
| W-18 | 重いデータを計測に入れたときの限界 (`scripts/bench_heavy.py`、共有メモリ / UDP の 2 通り、件数・大きさ・実物の 4 系列) | 結果の表・probe の費用の近似・目安が measurement.md にある | ✅ (この PC での実測。再実行は手動) |
