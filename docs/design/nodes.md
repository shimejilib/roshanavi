# roshanavi — ノード (入力・変換・関数・クラス・サンプル)

入力ノード (恒久ダミー)、変換ノード、関数ノード、クラスノード、同梱サンプルノード、データの種類 (ROS のメッセージ型を意識させない仕組み)。起動・停止・プロジェクトへの保存は [launcher.md](launcher.md)、画面は [ui.md](ui.md)。

## 恒久ダミーノード (P3)
- `ros2 run roshanavi dummy --config <yaml> --ros-args -r __node:=<name>`: 1 つの注入 (once / periodic / stream、`${}` 式、JSONL / CSV) を **独立した ROS ノード** として実行する。injector をそのまま使い、SIGINT / SIGTERM まで動き続ける (once や count 付きでも、送り終えた後もノードは残る)。設定エラーは終了コード 2、注入エラーは 1。
- Launcher が `kind: dummy` のターゲットとして管理する (役割 `dummy`、ノード名を `__node:=` で渡すので対応づけは exact)。設定 YAML (`{dummy: <DummySpec>, data_dir}`) はサーバーの一時ディレクトリに書く。
- 注入タブの実行中ジョブから「常駐ノードにする」で、同じペイロード・モード・レート・QoS の恒久ダミーを作って起動し、元のジョブは止める (`POST /api/inject/{id}/persist`)。
- **書き出し**: ワークスペース内の指定ディレクトリ (realpath で包含を検査、なければ作る) に `<id>.yaml` と `roshanavi_dummies.launch.py` を書く。`ros2 launch <dir>/roshanavi_dummies.launch.py` で、roshanavi のサーバー / UI なしで動く。ただし roshanavi パッケージのインストールは必要 (各ノードが `roshanavi dummy` を実行するため。生成ファイルの先頭に明記)。ノード名・ID は検証済みの値だけを `repr()` で埋め込む。

## 恒久ダミーの一時停止
- dummy ノードは bool パラメータ `paused` を宣言する。true にすると注入ジョブを一時停止する (ノードは動き続ける)。地図の「一時停止・再開」(メニューを開くとき現在値を取得し、合う方だけを出す) はこのパラメータを [launcher.md#ノードのパラメータと型の定義](launcher.md#ノードのパラメータと型の定義-p45a) の API で変える (`ros2 param set` でも同じ)。

## 変換ノード (P5)
入力ノード (ダミー) は「一方的に送る」だけだった。変換ノードは **トピックを受信し、変換して別のトピックに送る** ノードを、コードを書かずに GUI で作る。ROS 1 の `topic_tools transform` (Python 式で変換) に相当する機能を、安全な式評価 ([input-and-media.md#expr](input-and-media.md#expr-安全な式評価)) と GUI で提供する位置づけ。

用途:
- **未実装・未到着のノードの代役 (モック)**: パイプラインの途中のノードがまだ無いとき、それらしい出力を返す代役を置いて、自分のノードを先に試す。
- **つなぎ合わせ**: 名前や型が合わないトピック同士を変換してつなぐ。
- **意地悪テスト**: 遅延・間引き・取りこぼしを入れて、下流のノードの耐性を確かめる。

| 機能 | 設定 (`TransformSpec`) | 例 |
|---|---|---|
| フィールドの対応づけ (式) | `mapping`: 出力の型のテンプレートに `${...}` を書いたもの | `data: ${upper(msg.data)}`、`linear: {x: ${msg.linear.x * 0.5}}` |
| 条件で送る / 捨てる | `condition` (式。偽なら送らない) | `msg.data != ''` |
| 型の変換 | `output.type` と `mapping` | `std_msgs/String` → `std_msgs/Int32` (`data: ${int(msg.data)}`) |
| そのまま中継 | `mode: relay` (型も中身もそのまま。直列化したまま中継) | 名前だけ変える。画像・点群も可 |
| 入力をそのまま送る | `mode: map` で `mapping` なし (入力 1 つ、同じ型) | 条件・遅延だけ足す |
| 遅延 | `delay: {min_ms, max_ms?}` (一定、または範囲の一様乱数) | `{min_ms: 100, max_ms: 300}` |
| 間引き | `throttle_hz` (最大 N Hz) | `5` |
| 取りこぼし | `drop_ratio` (0〜1) | `0.1` |
| 複数入力 | `inputs` (最大 8) + `alias` + `trigger` (`any` か入力の別名) | `msg1.data + msg2.data` |

**仕様の検査** (`launcher/schema.py TransformSpec`, pydantic): 別名の既定は入力 1 つなら `msg`、複数なら `msg1`, `msg2` …。別名は一意で、`i t now pi e` は使えない。`relay` は入力 1 つ・`mapping` / `condition` なし・型を変えない (出力の型は省略可で入力の型)。大きい型 (`heavy_types.py`: Image / CompressedImage / PointCloud2 / PointCloud) は `relay` だけ (フィールドの式は使わない。中継・遅延・間引き・取りこぼしのみ)。複数入力は `mapping` 必須。`trigger` は `any` か入力の別名。ワークスペースに依存する検査 (`launcher/command.py validate_transform`): ノード名・名前空間、トピックは絶対名、**出力トピックが入力のどれかと同じなら拒否** (自分の出力を受けて無限に回るため)。

**実体** (`transform_node.py` + `transform/`): `ros2 run roshanavi transform --config <yaml> --ros-args -r __node:=<name>` (設定 YAML は `{transform: <TransformSpec>}`)。恒久ダミー ([nodes.md#恒久ダミーノード](nodes.md#恒久ダミーノード-p3)) と同じく `RosRuntime` の上で動く独立したノード。
- 流れ (`transform/pipeline.py`、rclpy なしでテスト): 受信 → (複数入力) 最新値の結合 → 取りこぼし → 条件と対応づけ (map) → 間引き → 遅延 → 送信。取りこぼしを先にして捨てる分の計算を省く。間引きは条件の後 (捨てたメッセージで枠を使わない)。間引きの間隔は 5% の余裕を持たせる (10 Hz を 10 Hz に間引くとき、揺らぎで半分になるのを防ぐ)。遅延は 1 本のスレッドが期限順に送る (`DelayQueue`、待ちは最大 10,000 件で、溢れたら `overflow` に数えて捨てる)。範囲の遅延では後のメッセージが追い越すことがある (実際のネットワークと同じ)。
- 結合 (`Joiner`): 入力ごとに最新の値を持つ。全部の入力が 1 回以上届くまでは送らない (`waiting`)。`trigger: any` はどれかの更新で、別名を指定すればその入力の受信時だけ計算する。
- `relay`: `raw=True` で購読し、受け取ったバイト列をそのまま `publish` する (デシリアライズしない。画像も軽い)。
- `map`: 受信したメッセージを `MsgView` にし、`transform/compute.py Computer` (条件と対応づけを一度だけコンパイル) で出力の素データを作り、`msgutil.build` で出力のメッセージにする。変数は `i` (受信回数、0 始まり)、`t` (起動からの秒)、`now`。式のコンパイルエラーは起動時に終了コード 2 (フィールドの場所付き)。実行時のエラー (範囲外の添字など) はそのメッセージだけ捨てて `errors` に数え、ログは 10 秒に 1 回。
- QoS: 入力は best effort (reliable と best effort のどちらの送信者からも受けられる)、出力は `output.qos` (既定 reliable / volatile / 10)。
- 10 秒ごとに数 (受信・送信・条件で捨てた・取りこぼし・間引き・エラー) をログに出す (変わったときだけ)。

**管理**: プロジェクトファイルの `transforms:` (ダミーの `kind` を増やすのではなく別の一覧にした。`DummySpec` は注入の設定で、入力・出力・式の形がまったく違うため)。Launcher の起動リストで ID を共有し (targets / dummies / transforms で一意)、`kind: transform`、役割 `transform` (地図はダミーと同系統の紫、凡例「変換ノード」、ノード一覧の役割「変換」)。起動・停止・再起動・ログ・自動起動・自動再起動・`launch` への書き出しはダミーと同じ (`POST /api/dummies/export` は変換ノードも書き出し、launch ファイルの Node は `executable='transform'`)。API: `POST /api/transforms` (`?start=true`)、`PUT /api/transforms/{id}`。削除・起動・停止・ログは `/api/targets/{id}`。

**試算 (プレビュー)** (`transform/preview.py`、`POST /api/transforms/preview {spec, samples}`): ノードと同じ `Computer` と `msgutil.build` で、送らずに計算だけする。`samples` は入力の別名ごとの素の dict (UI が `/ws/echo` で受けた最新のメッセージ。届いていなければ省略し、サーバーが入力の型の既定値で代わりに計算して `templated` に別名を返す)。常に 200 で `{ok, passed, output, errors[{path, code, message, params}], templated, relay}` を返す (仕様の検査エラーも `spec_invalid` として同じ形)。`passed: false` かつエラーなしは「条件に合わないので送らない」。出力の型に合わない値は `build_invalid_value` などを、メッセージの先頭のフィールドの場所に付ける。サンプルは最大 8 個、深さ 32 まで。エコーは長い配列を先頭 32 個に切り詰めた形 (`{_truncated, length, head}`、長い文字列は `…(+N chars)`) で送るので、**プレビューの計算にはエコーの値ではなく、切り詰めないメッセージを使う** (#10)。`GET /api/echo/{topic}/sample` が、エコー中のトピックの最新メッセージを `{topic, seq, msg, capped, size_bytes, max_bytes}` で返す (`EchoManager.latest_sample`)。シリアライズ後のサイズが上限 (`echo.MAX_SAMPLE_BYTES` = 256 KiB) までなら `msg` は切り詰めない dict (`msgutil.to_plain`)、超えると `capped: true` で従来の切り詰めた表示用の値に戻る (巨大な画像などで応答とプレビューのリクエストが膨らまないため)。エコーしていないトピック・まだ届いていないときは `msg: null`。UI は、エコーの値に切り詰めがあるトピックだけ 1 秒ごとにこの API を引き、上限内ならそれで計算する。上限を超えたとき (または取得できないとき) は切り詰めた値で計算し、プレビューに「入力のメッセージが大きいため、配列や文字列を途中で切った値で計算しています」と明示する。

**詳細計測モード ([measurement.md#詳細計測モード](measurement.md#詳細計測モード-トレース計測-p47)) での見え方**: 変換ノードは rclpy なので、トレースで測れるのは **受信数だけ** (処理数・処理時間は「未対応」、理由 `rclpy`)。送信は C++ 計測ノード ([measurement.md#C++ 計測ノード](measurement.md#c-計測ノード-roshanavi_probe-p46)) で送信ノードごとに実測される。編集画面にもこの注意を書く。
- 制約: 式は 1 メッセージあたり Python で評価するので、数百 Hz を超える入力や大きい配列のフィールド計算には向かない (大きい型は relay のみ)。

## 同梱サンプルノード (`roshanavi_examples`, P5)
チュートリアル、デモ、自動テストの対象を兼ねる。初めて ROS を触る人が読む前提で、各ファイルの先頭に「何を受けて何を出すか・パラメータ・実行例・なぜその言語か」を書き、処理の中身にもコメントを付ける。各ノードに `launch/<name>.launch.py` (引数でトピックとパラメータを変える) がある。

**言語の分け方**: 画像の 2 つは C++ (rclcpp)、ほかは Python (rclpy)。詳細計測モード ([measurement.md#詳細計測モード](measurement.md#詳細計測モード-トレース計測-p47)) で、C++ のノードは受信・処理・処理時間まで、Python のノードは受信数だけが測れる。その違いを同じデモの中で見比べられるようにわざと混ぜた。画像処理は C++ の方が自然 (1 画素ずつのループ) で、状態遷移や音量の計算は Python の方が短く読みやすい。

| ノード | 言語 | 受信 → 送信 | パラメータ | 詳細計測モードで測れるもの |
|---|---|---|---|---|
| `image_filter` | C++ | `image` (Image: rgb8 / bgr8 / rgba8 / bgra8 / mono8) → `image_gray`、`image_edges` (どちらも mono8、同じ大きさ) | `keep_stamp` (bool, true: 入力の `header.stamp` を引き継ぐ / false: いまの時刻)、`process_delay_ms` (int, 遅い処理の再現) | 受信・処理・処理時間。`process_delay_ms` を大きくすると「処理が追いついていません」 |
| `blob_detector` | C++ | `image` → `detections` (`vision_msgs/Detection2DArray`。bbox の中心・大きさ、`class_id: blob`、`score` = 平均の明るさ / 255、header は入力のまま。見つからなくても空の配列を毎回送る) | `threshold` (0〜255, 200)、`min_area` (30)、`max_detections` (20) | 受信・処理・処理時間 |
| `audio_level` | Python | `audio` (`input_type: stamped` → `audio_common_msgs/AudioDataStamped` の S16LE、`int16` → `std_msgs/Int16MultiArray`) → `level_db` (Float32、RMS の dBFS、無音は -120)、`silence` (Bool) | `input_type`、`silence_below_db` (-45)、`sound_above_db` (-35): 2 つのしきい値の間では状態を変えない (ヒステリシス) | 受信数だけ |
| `state_machine` | Python | `cmd` (String: start / stop / fault / reset、大文字小文字は無視) → `state` (String: IDLE / RUNNING / ERROR) | `initial_state` (IDLE)、`publish_period_sec` (1.0, 0 で変化時だけ) | 受信数だけ |
| `executor_busy_demo` | Python | `/busy_demo/in` (String) → `/busy_demo/stats` (String、JSON を毎秒) | `executor` (single / multi, multi)、`qos_events` (default / off, default)、`work_ms` (5)、`num_threads` (4)、`input_topic`、`stats_topic` | 受信数だけ |

- 画像処理は OpenCV を使わず `include/roshanavi_examples/image_ops.hpp` の純粋な関数 (グレースケール: 整数の BT.601 の重み、エッジ: 3x3 Sobel の |gx|+|gy| を 255 で頭打ち・端は 0、塊: 4 近傍の塗りつぶし (再帰しない)、面積の大きい順) にまとめ、gtest (`test_image_ops`) で ROS なしにテストする。ノードは ROS のメッセージとの変換だけ。パラメータは毎回読むので、実行中の変更 (地図のパラメータ・`ros2 param set`) がすぐ効く。壊れた画像 (大きさが足りない・未対応の encoding) は 5 秒に 1 回の警告で捨てる。
- QoS: 購読は best effort (SensorDataQoS。どの送信者からも受けられる)、送信は reliable (どの購読者でも受けられる)。`state_machine` の `state` は transient local (後から購読したノードにもいまの状態が届く)。
- Python のノードは計算の部分 (`level_db`・`SilenceDetector`・`StateMachine`) を ROS なしのクラス・関数にし、pytest で直接テストする。ROS の import は `main()` の中。
- `audio_common_msgs` は `input_type: stamped` のときだけ必要 (package.xml は exec_depend)。`vision_msgs` は新しい依存 (`ros-jazzy-vision-msgs`)。
- 起動設定の例: `examples/demo_project` (autostart なし)、`examples/perception_demo` ([launcher.md#デモ構成](launcher.md#デモ構成-p45a))、`examples/busy_demo` (executor_busy_demo の 3 構成、autostart なし)。

### executor_busy_demo — MultiThreadedExecutor の空回りを体験する (#40)
**何が起きるか**: rclpy のノードを `MultiThreadedExecutor` + Fast DDS (`rmw_fastrtps_cpp`、Jazzy 既定) で動かすと、仕事をほとんどしていないのに CPU を 1 コア近く使うことがある。rclpy は購読ごとに「QoS が合わない」などを知らせる QoS イベントの待ち受けを自動で付ける。rmw_fastrtps ではそれが購読本体と同じ「データ到着」の目印を共有していて、MultiThreadedExecutor は購読のコールバックを実行中その購読を待ち受けから外すため、その間に届いたメッセージを待ち受けが「あるのに受け取れない」と見て `wait()` がすぐ戻り続ける (ros2/rmw_fastrtps#929、関連 ros2/rclpy#1223)。executor のスレッドが毎秒数千回空回りして GIL を握り、コールバック自体も遅れる。roshanavi 自身の購読に QoS イベントを付けない理由もこれ ([#19](https://github.com/shimejilib/roshanavi/issues/19)、CLAUDE.md)。

**構成**: `busy_demo_driver` が `/busy_demo/in` に 100 Hz (`rate_hz`) で送り、`executor_busy_demo` が受けて `work_ms` (既定 5 ms) だけ sleep する (軽い処理の代わり。sleep は CPU を使わないので、見える CPU は executor 自身の空回り)。`executor_busy_demo` は 1 秒ごとに `stats_topic` へ次の JSON (std_msgs/String) を送り、同じ内容を 1 行でログに出す: `executor`、`qos_events`、`num_threads`、`work_ms`、`wait_passes_per_sec` (executor の待ちの回数)、`empty_passes_per_sec`、`empty_ratio` (空振りの割合)、`callbacks_per_sec`、`passes_per_callback`、`process_cpu_percent` (プロセス全体の CPU 時間 ÷ 経過時間。100 = 1 コア)。

**数え方** (`PassCounter`、monkeypatch なし): rclpy の `Executor` の公開メソッド 2 つを上書きするだけ。executor の待ちのループは 1 周ごとに `get_nodes()` を 1 回呼び、準備できたコールバックを `wait_for_ready_callbacks()` が 1 つずつ返す。したがって 周 = `get_nodes()` の呼び出し、空振りの周 = その周で `wait_for_ready_callbacks()` が何も返さなかった周。`rclpy.executors` の `WaitSet.wait()` を直接数えた値と照合して合った (65,414 周 vs 65,433 回、差は実行中の 1 周分など)。前提は「1 周で `get_nodes()` を 1 回呼ぶ」(rclpy 7.x = Jazzy、rclpy 10.x = Lyrical で確認。`test_executor_busy_demo.py` が両方で通る)。崩れたら単体・統合テストが気づく。

**3 つの構成** (`examples/busy_demo/roshanavi.yaml`、autostart なし。⚙ のプロジェクト切り替えから開き、`busy_demo_driver` を起動してから 1 つずつ起動して比べる。同時に動かすと CPU が混ざる):

| 構成 | 意味 | 結果 |
|---|---|---|
| `multi_default` | `executor: multi` + 既定の QoS イベント | 空回りする (問題) |
| `multi_off` | `executor: multi` + `qos_events: 'off'` (`SubscriptionEventCallbacks(use_default_callbacks=False)`) | 空回りしない (回避策) |
| `single_default` | `executor: single` + 既定の QoS イベント | 空回りしない (コールバックが待ちと同じスレッドで動くので、購読は常に待ち受けに入っている) |

実測値 (Docker、24 コアの PC、`rmw_fastrtps_cpp` 8.4.4、`work_ms` 5、送信 100 Hz、4 スレッド、6 秒間の中央値): [troubleshooting の節](measurement.md#cpu-が高い-multithreadedexecutor-の空回り) の表。

**トレードオフ**: QoS イベントの通知を外すと、購読と送信側の QoS が合わないときに出る「incompatible QoS」の警告ログも出なくなる (データが来ないことで初めて気づく)。CPU が問題になる購読 (高いレート + MultiThreadedExecutor) だけ外すか、通知を残したまま `SingleThreadedExecutor` にする。roshanavi の地図の QoS 診断は roshanavi 自身が見ているので、ノード側で外しても地図には出る。

**落とし穴**: YAML 1.1 では素の `off` は `false` になる (`ros2 param`・launch・プロジェクトファイル)。プロジェクトファイルでは `'off'` と引用符で書く。ノード側は `false` も `off` として受け付け、launch ファイルは `ParameterValue(..., value_type=str)` で文字列のまま渡す。`work_ms` / `rate_hz` は `-p work_ms:=5` が整数で来ても受け付ける (`dynamic_typing`)。

起動: `ros2 launch roshanavi_examples busy_demo.launch.py [executor:=multi] [qos_events:=off] [work_ms:=5.0] [num_threads:=4] [rate_hz:=100.0]`、または `ros2 run roshanavi_examples busy_demo_driver` と `ros2 run roshanavi_examples executor_busy_demo --ros-args -p qos_events:=off`。

## 中継パイプライン (source / relay / sink、#51)
受け取って次に送る C++ のノードを、形 (直列・分岐・合流・格子) と規模 (3 段 / 20 ノード / 200 ノード以上) を指定してつなげるサンプルと生成器。「ノードが多いと地図・計測・リソース監視はどこまで持つか」を測る ([measurement.md#規模と負荷の限界](measurement.md#規模と負荷の限界-51)) のと、**別プロセスと composable container の両方で同じ構成を動かして** composable container の扱いを確かめる ([launcher.md#composable container の扱い](launcher.md#composable-container-の扱い-22)) のが目的。

**メッセージ** (`roshanavi_examples_msgs`、公開。どのノードからも使ってよい)
| 型 | 中身 |
|---|---|
| `roshanavi_examples_msgs/msg/Payload` | `std_msgs/Header header` (`stamp` = source が作った時刻、`frame_id` = source のノード名 = **経路**)、`uint32 seq` (source ごとの連番)、`uint8[] data` (中身は無意味、大きさだけが意味を持つ) |
| `.../msg/SinkStats` | sink が `~/stats` に出す統計: `sink`、`window_sec`、`PathStats[] paths` |
| `.../msg/PathStats` | 経路 (source) ごとの `received` / `lost` (連番の欠け) の累計、窓内の `rate_hz`、`latency_ms_mean` / `p50` / `p95` / `max` |

**3 つのノード** (`roshanavi_examples`、C++/rclcpp。**composable node** (`roshanavi_examples::PipelineSource` / `PipelineRelay` / `PipelineSink`) としても、実行ファイル (`pipeline_source` / `pipeline_relay` / `pipeline_sink`) としても動く。トピック名は相対名で、リマップして使う。1 本目は `in` / `out`、2 本目以降は `in_1` / `out_1` …)

| ノード | 役割 | パラメータ (実行中に変えられるのは ○) |
|---|---|---|
| `pipeline_source` | `rate_hz` で `Payload` を作って `out` (`out_1` …) に送る。`header.stamp` = いま、`frame_id` = 自分のノード名 | `rate_hz` (10) ○、`payload_bytes` (64) ○、`enabled` (true、false で一時停止) ○、`count` (0 = 止まらない)、`num_outputs` (1)、`fanout` (`all`)、`queue_depth` (10) |
| `pipeline_relay` | `in` … の**どれかに**メッセージが来るたびに、間引き → 処理 → 送信 | `process_ms` (0) ○、`process_mode` (`busy` = CPU を使う / `sleep`) ○、`payload_bytes` (-1 = 入力の中身をそのまま、0 以上ならその大きさに切り詰め・ゼロ埋め) ○、`rate_limit_hz` (0 = 入力ごと。0 より大きいと、前に送ってから 1/Hz 経っていない入力は捨てる) ○、`keep_stamp` (true = 入力の `stamp` をそのまま / false = いまの時刻) ○、`drop_ratio` (0..1、確率で捨てる) ○、`num_inputs` / `num_outputs` (1)、`fanout` (`all` = 全部の出力へ / `round_robin` = 1 通ごとに順番に 1 本へ)、`seed` (0 = ノード名から)、`queue_depth`、`log_period_s` (0) |
| `pipeline_sink` | 受けて「いま − `stamp`」を測る。経路 (`frame_id`) ごとに窓 (`window_s`、5 秒) の統計を `~/stats` に出し、`log_period_s` ごとにログにも 1 行出す | `num_inputs` (1)、`window_s` (5)、`stats_period_s` (1、0 で出さない)、`log_period_s` (5)、`max_samples` (50000)、`queue_depth` |

- `header.frame_id` と `seq` はどの relay も入力から引き継ぐ。sink はそれで経路を分け、連番の欠けを `lost` として数える。**`lost` が意味を持つのは経路がほかと混ざらないとき** (直列・分岐・合流・まっすぐな格子)。`fanout: round_robin` を通ると 1 つの source の連番が複数の出口に分かれて飛び飛びになるので、`lost` は見かけ上増える。その場合の欠落率は下の「期待値」との比で出す。
- 遅延は `keep_stamp: true` の relay だけを通ると source からの **端から端まで**になる。`false` の relay では、そこで時計を 0 に戻す (その段の「入ってから出るまで」を sink で見たいとき)。
- 範囲外の値は `ros2 param set` が理由付きで拒否する (`drop_ratio must be between 0 and 1` など)。起動時の値が不正 (`fanout` が `all` / `round_robin` 以外、個数が 1 未満) ならノードは起動せずエラーで終わる。
- 数値のパラメータは整数 (`-p process_ms:=5`) でも小数 (`5.0`) でも受け付ける (動的型付け)。
- 純粋なロジック (`RelayGate` = 間引き、`make_payload`、`FanoutSelector`、`SeqTracker`、`LatencyWindow`) は `include/roshanavi_examples/pipeline_logic.hpp` にあり、ROS なしの gtest (`test/test_pipeline_logic.cpp`) で確かめる。ノードの振る舞いは実プロセスの pytest (`test_pipeline_nodes_ros.py`)。
- 詳細計測モードでは relay・sink ともコールバックの回数と処理時間が測れる (C++)。

**重いデータの送受信** (`heavy_source` / `heavy_sink`、同じ `roshanavi_examples` の C++。composable としても動く。[measurement.md#重いデータの計測の限界](measurement.md#重いデータの計測の限界-51) の測定用): `heavy_source` は `out` に `sensor_msgs/Image` (rgb8、`width` × `height`) または `PointCloud2` (x y z intensity の float32、`points` 点) を `rate_hz` で送る (`kind: image | pointcloud`、`qos: best_effort | reliable`、`depth`)。`header.stamp` = いま、`frame_id` = 連番。`heavy_sink` は `in` を同じ QoS で受けて遅延と連番の欠けを測り、`~/stats` (`SinkStats`、経路名 `heavy`) に出す。データには触らないので、受信側の負担はほぼ無い。

**生成器** `scripts/gen_pipeline.py` (標準ライブラリだけの Python。生成時に ROS を import しない。中身は `roshanavi_examples/pipeline_gen.py`)

```
scripts/gen_pipeline.py --preset medium                    # examples/pipeline_medium/ に書く
scripts/gen_pipeline.py --all                              # 3 つのプリセット
scripts/gen_pipeline.py --shape fanout --stages 5 --width 3 --rate 50 --process-ms 2 --out /tmp/p
```

| 形 (`--shape`) | つながり | ノード数 |
|---|---|---|
| `chain` | src → relay × (stages-2) → sink | stages |
| `fanout` | src → 中継 (`num_outputs` = width、全部へ送る) → width 本の列 (relay × (stages-3) → sink) | 2 + width × (stages-2) |
| `fanin` | width 本の列 (src → relay × (stages-3)) → 合流する relay (`num_inputs` = width) → sink | width × (stages-2) + 2 |
| `grid` | stages 段 × width 列。0 段目は src、最後の段は sink、間は relay。`--links mesh` (既定) は各ノードが同じ列と隣の列へ 1 通ごとに交互に送り (`round_robin`)、上流の 2 つから受ける (どの列のノードも流量は変わらない)。`straight` は独立した列 | stages × width |

| プリセット | 形 | ノード数 |
|---|---|---|
| `small` | `chain` 3 段 | 3 |
| `medium` | `grid` 5 段 × 4 列 | 20 (src 4・relay 12・sink 4、トピック 32) |
| `large` | `grid` 10 段 × 20 列 | 200 (src 20・relay 160・sink 20、トピック 360) |

主なオプション: `--rate` (source ごとの Hz)、`--payload-bytes`、`--process-ms` / `--process-mode`、`--relay-payload-bytes`、`--rate-limit`、`--drop-ratio`、`--no-keep-stamp`、`--mode process|container` (launch ファイルの既定)、`--containers N`、`--container-type st|mt`、`--intra-process`、`--topic-prefix` (既定 `/pipe`)、`--out`。値が不正なら理由を出して終わる (終了コード 2)。

**出力** (`examples/pipeline_<preset>/`。コミットしてあり、テスト `test_committed_examples_are_up_to_date` が生成器の出力と一致していることを確かめる)
| ファイル | 内容 |
|---|---|
| `pipeline.json` | 形・ノード (種類・段・列・パラメータ・リマップ)・トピック (送信ノード・受信ノード・期待される Hz)・**期待値** (`expected.sink_hz` = 何も詰まらないとき各 sink が受けるはずの毎秒の数) |
| `pipeline.launch.py` | `pipeline.json` を隣から読んで起動する launch ファイル。`ros2 launch .../pipeline.launch.py mode:=process` (1 ノード 1 プロセス) / `mode:=container` (`ComposableNodeContainer` に全ノード)。ほかの引数: `containers` (コンテナの数、ノードは段の順に等分)、`container_type` (`st` = `component_container`、`mt` = `component_container_mt`)、`intra_process` (`use_intra_process_comms`) |
| `roshanavi.yaml` | roshanavi のプロジェクト (1 ノード 1 プロセス)。ノードが 60 以下なら 1 ノード 1 つの `kind: run` (リマップ・パラメータ付き。relay は `role: mine`)、それより多いと (プロジェクトの起動設定は 100 まで) `kind: launch` 1 つ |
| `roshanavi_container.yaml` | 同じ構成を composable container で動かすプロジェクト (`kind: launch` 1 つ、`mode:=container`) |

インストールされる `launch/pipeline.launch.py` (`ros2 launch roshanavi_examples pipeline.launch.py spec:=<pipeline.json> mode:=...`) を roshanavi の起動設定 (`package` + `launch_file`) が使う。`pipeline.json` のパスは roshanavi から見えるパスで書く (Docker では `/examples/pipeline_<preset>/pipeline.json`)。

**期待値** (`pipeline_gen._propagate`): source は `rate_hz`、relay は「入力の合計 × (1 - drop_ratio)」を `rate_limit_hz` で頭打ちにし、`round_robin` なら出口の数で割る。sink は入力の合計。測定 ([measurement.md#規模と負荷の限界](measurement.md#規模と負荷の限界-51)) の**欠落率 = 1 - (sink が受けた毎秒の数の合計 / 期待値)**。

**使う**: ⚙ のプロジェクト切り替えから `pipeline_medium` を開くと 20 ノードが起動し、地図に格子が出る (エッジの Hz は各トピック 5 Hz = 10 Hz の送信元を 2 つの出口に交互に送るため)。composable container で動かすには `roshanavi_container.yaml` を `/data/roshanavi.yaml` に置くか、起動設定に `roshanavi_examples` の `pipeline.launch.py` を `spec:=…` `mode:=container` で追加する。

## データの種類 (ROS のメッセージ型を意識させない、P5.5)
**課題**: 入力ノード・変換ノードなどの型選択が、ROS のメッセージ型の名前順の一覧だった。ROS を知らない人はメッセージ型を意識しないし、選べない。

**方針**: 既定では **データの種類** を選ばせ、ROS の型は裏で決める。**詳細設定モード** を ON にしたときだけ、ROS のメッセージ型を直接選べる。

| データの種類 (表示) | id | ROS の型 (裏側) | 関数ノードでの Python の値 |
|---|---|---|---|
| 文字列 | `string` | `std_msgs/String` | `str` |
| 数値 (小数) | `float` | `std_msgs/Float64` | `float` |
| 整数 | `int` | `std_msgs/Int64` | `int` |
| ON / OFF | `bool` | `std_msgs/Bool` | `bool` |
| 数値の並び | `numbers` | `std_msgs/Float64MultiArray` | `list` of float |
| JSON (複数の値をまとめて) | `json` | `std_msgs/String` (JSON) | `dict` / `list` (構造化) |
| 画像 | `image` | `sensor_msgs/Image` | numpy 配列 (高さ×幅×3 = rgb8 / 高さ×幅 = mono8) |
| 音声 | `audio` | `audio_common_msgs/AudioDataStamped` (無ければ `std_msgs/Int16MultiArray`) | numpy int16 (サンプル、または サンプル×トピック) |
| バイト列 (生データ) | `bytes` | `std_msgs/UInt8MultiArray` | `bytes` |
| 専用の型 (詳細設定モード) | `message` | 指定した任意の型 | メッセージ全体の dict 表現 |

- **対応表は 1 か所** (`roshanavi/data_kinds.py`): 種類 ↔ 型、インストールされている型の選択 (音声の代替)、既存の型 → 種類 (互換の型: `Float32` → 数値 (小数)、`Int8`〜`UInt64` → 整数、各種 `*MultiArray` → 数値の並び、`AudioData` → 音声、`example_interfaces/msg/String` などの example_interfaces の 1 項目の型 → 対応する種類 (Lyrical のデモの talker が使う)。型はそのまま使う)、Python の値との変換 (`to_python` / `from_python`、画像・音声はメディアのアダプタ [input-and-media.md#メディア](input-and-media.md#メディア-アダプタファイルソースブラウザ入力ビューア-p4) 経由で変換は型ごとに 1 つ)、詳細設定モードの並び (`type_groups`)。入力ノード・変換ノード・関数ノード・メディアのアダプタ (`/api/media/types` の `data_kind`) が共有する。`GET /api/data-kinds` は `{kinds[{id, type, available, python}], type_kinds, common_types, conversions}` (`conversions` は地図の配線で許す種類の変換、[wiring.md](wiring.md))。表示名は UI の i18n (`i18n/messagesKinds.ts`)。
- 変換は厳密: 数値に `bool` や文字列は渡さない、整数は整数値の float まで、画像は uint8 で 2 次元か 3 トピック、音声は int16。合わないときは「出力の種類 int には int が必要ですが、関数は str を返しました」のように型名付きのエラー (`KindError`)。
- **既存のトピックに送る場合は、型を選ばせない** (相手が決まっているため)。自動で検出し、「このトピックは 文字列 (std_msgs/String) です」のように、データの種類と ROS の型を併記する。上の表に無い型なら「専用の型: geometry_msgs/Twist」と表示し、テンプレートで入力させる。型が複数あるトピックはどれに合わせるかだけを選ぶ。既存の `String` のトピックを JSON として扱う選択は保つ。
- 新しいトピックでは種類を選ぶ。ROS の型名は画面に出さない (E2E `datakind.spec.ts` で `std_msgs` が見えないことを確認)。
- **詳細設定モード** の型一覧の並び順 (`GET /api/types` の `groups`): ① よく使う型 (std_msgs の基本型、`geometry_msgs/Twist`・`Pose`・`PoseStamped`、`sensor_msgs/Image`・`LaserScan`・`PointCloud2`・`Imu`・`JointState`) → ② ワークスペースの独自型 (ワークスペースのパッケージ) → ③ その他 (パッケージごとにまとめ、検索で絞る)。名前順の単純な一覧にはしない。
- 詳細設定モードの ON/OFF は画面右上の **⚙ 設定** に置き、ブラウザに記憶する (`localStorage` の `roshanavi.advancedMode`。読めない・書けない環境では例外を出さず OFF のまま)。
- 入力ノードの中身は種類ごと: 文字列 (そのまま / 式)、数値・整数 (値 / 式。`sin(t)` は `${sin(t)}` として値の型のまま送る)、ON / OFF (選択 / 式)、数値の並び・バイト列 (カンマ区切り)、JSON (テキスト。式を含まないときは JSON として検査)、画像・音声 (data ディレクトリのファイルだけ)、専用の型 (YAML テンプレート)。UI で選んだ種類は `DummySpec.kind` に保存する (任意。型に合わなければ拒否)。

## 関数ノード (ふつうの関数を、そのままノードにする、P5.5)
**目的**: ROS を知らない人でも、**ROS のコードを書かずに**自分のロジックをノードとして動かせるようにする。利用者は普通の Python 関数を書くだけで、受信・呼び出し・送信は roshanavi が受け持つ。

```python
# my_pkg/logic.py — ROS を import しない、普通の関数
def shout(text: str) -> str:
    return text.upper() + "!"
```
roshanavi で「＋ 関数・クラスノードを作る」→「関数」→ モジュール `my_pkg.logic`、関数 `shout`、入力 `/chatter`、出力 `/shouted` を選ぶだけで、ノードとして動く。

| 呼び出し方 (`call`) | 内容 |
|---|---|
| 受信のたびに呼ぶ (`on_message`) | 入力 1 つ。届いた値を引数にして関数を呼び、戻り値を出力トピックに送る |
| 一定周期で呼ぶ (`periodic`、`rate_hz`) | 入力なし。引数なしで (必須の引数が 1 つなら起動からの経過秒を渡して) 周期的に呼ぶ (センサーの代役など) |
| 複数入力 (`multi_input`、`trigger`) | 入力 2〜8 つ。各入力の最新値を入力の順に引数へ渡す (変換ノードと同じ結合ルール `transform/pipeline.Joiner`: 全部の入力が 1 回届くまで呼ばない、`trigger` は `any` か入力のトピック) |

- 戻り値が `None` のときは送らない (条件付きで出したいとき用、`skipped` に数える)。
- **つながっていない口** (地図の上での配線、[wiring.md](wiring.md)): 入力・出力のトピック名は空 (`''`) でもよい。空の入力は購読せず、空の出力には送らない (関数は呼ばれ、戻り値は `skipped` に数える)。空の口は重複・自己ループの検査から外し、`trigger` にはできない。クラスノードの口も同じ。コードの書き出しは全部の口がつながっているときだけ (409 `unwired_ports`)。
- **入力口の変換**: 入力口は、種類が変換できる型のトピックも購読できる (`data_kinds.accepts`。整数のトピックを `kind: float` の口で受けると `float()` で渡す)。変換の表 (`CONVERSIONS`: 整数 → 小数、文字列 ↔ JSON) は地図の配線の互換性の規則 (`wire_compat`) と同じ。
- 入力に種類 (`kind`) だけを書いて型 (`type`) を省いたときは、起動の時点で地図にあるそのトピックの型のうち、その種類を運べるものが 1 つだけならその型で購読する (`function/core.adopt_topic_types`。例: Lyrical のデモの `/chatter` は `example_interfaces/msg/String` なので、`kind: string` の `text_shout` もそれを購読する)。トピックがまだ無い・候補が複数なら種類の既定の型 (`std_msgs/msg/String` など)。書かれた型は常にそのまま使う。
- 例外が起きたら、そのメッセージは送らず、ログと画面に「関数でエラーが起きました」と **ファイル:行番号 (関数名)** 付きで出す (利用者のパッケージ内でいちばん深いフレーム。ログは 5 秒に 1 行まで、抑えた件数を添える)。ノードは止めない。値の変換の失敗 (戻り値の型が合わない、届いた JSON が読めない) も同じ扱い。
- 値の受け渡しは [nodes.md#データの種類](nodes.md#データの種類-ros-のメッセージ型を意識させないp55) の表 (入力側も同じ)。関数には ROS のメッセージではなく Python の値を渡す。詳細設定モードの「専用の型」では、メッセージ全体を dict で受け取り、dict で返す。画像・音声の出力には、呼び出しのきっかけになった入力の `header.stamp` を引き継ぐ (latency を測れるように。無ければいまの時刻)。
- 地図上の役割は `function` (変換・ダミーと同じ系統の色で、ピンク。凡例「関数・クラスノード」、ノード一覧の役割「関数・クラス」、右クリック「関数ノードの設定を変更」。クラスノードも同じ役割)。プロジェクトの `functions:` に保存し ([launcher.md#プロジェクトファイル](launcher.md#プロジェクトファイル-p3))、自動起動・自動再起動・停止・ログ・launch への書き出し (`executable='function'`) はダミー・変換ノードと同じ。

**実行と安全**
- 関数は独立したノードのプロセス (`ros2 run roshanavi function --config <yaml>`、設定は `{function: <FunctionSpec>, workspace: <root>, status_file?: <path>}`) で動く。**roshanavi のサーバーの中では実行も import もしない**。サーバーはモジュールの一覧と関数のシグネチャを **`ast` の静的解析だけ** で作る (`function/modules.py`: トップレベルの公開 `def`、引数・注釈・既定値の有無・戻り値の注釈・docstring の最初の段落・行番号。注釈から種類を推す: `str` → 文字列、`np.ndarray` → 画像 …)。
- **コードの置き場所・見つからない理由・ひな形・依存ライブラリ**は [user-code.md](user-code.md) (A: ワークスペースの ROS パッケージ、B: 登録した場所 `code_paths:`、C: インストール済みのモジュール `installed_modules:`)。以下は A の規則 (B・C は同じ考え方で根が違う)。
- **import できる範囲** (`modules.resolve_module`): `<workspace>/src` の ROS パッケージ (package.xml) の直下にある Python パッケージ (`__init__.py` のあるディレクトリ) のモジュールだけ。モジュール名は `[A-Za-z_][A-Za-z0-9_]*` の最大 8 段。解決したファイルの realpath が `<workspace>/src` の内側で通常ファイルであること (内向きの symlink は使え、外向きは拒否。以前は Python パッケージの内側に限っていた)。標準ライブラリやノードが使うライブラリと同じ名前のパッケージは読まない ([user-code.md#2](user-code.md#2-置き場所-探す範囲))。`roshanavi` 自身は拒否。data_dir は使わない。import は `sys.path` を触らず、パッケージの `__init__.py` から `spec_from_file_location` で読み、import 後に `__file__` が解決したファイルと一致することを確かめる。利用者自身のコードなので、信頼の水準は自分でノードを起動するのと同じ (サンドボックスはしない)。
- 追加・変更の時点 (`command.validate_function`) でモジュールが解決できなければ 404 `unknown_module`。起動後に import が失敗したときはプロセスを終わらせず、状態 `import_error` で待ち、ファイルが直ったら読み込む。

**ホットリロード (決定: プロセス内で新しく import し直す)** (`function/loader.py`)
- ファイルの保存を 0.5 秒ごとの mtime + サイズの見張りで検出し (書き込みが落ち着くまで 0.2 秒待つ)、利用者のパッケージのモジュールを `sys.modules` から外して **パッケージごと新しく import し直す**。関数はメッセージごとにローダーから読むので、次のメッセージから新しい関数になる。
- 理由: (1) `importlib.reload` は 1 つのモジュールしか読み直さず、同じパッケージの補助モジュールや他のモジュールが持つ古い参照が残る。新しい import ならパッケージ全体が揃う。(2) 新しい import が失敗したら (構文エラー・import 時の例外・関数の名前が変わった)、外したモジュールを戻して **前の関数のまま動き続け**、エラーを場所付きで出す (状態 `reload_error`)。直して保存すれば読み込む。(3) ノード・購読・送信者はそのままなので、DDS の再発見の待ち (プロセスの再起動なら毎回 1 秒程度 + 発見) が無く、複数入力の最新値も失わない。(4) inotify は bind mount や WSL では届かないことがあり、依存も増えるので、ポーリングにした。
- バイトコードは読まず書かない (`sys.dont_write_bytecode`、`pycache_prefix` は空の一時ディレクトリ): 同じ秒・同じサイズの編集でも古い `.pyc` を読まず、利用者のソースに `__pycache__` を作らない。
- 制約: モジュールの大域変数は読み直しのたびに初期化される。C 拡張と、利用者のパッケージの外のモジュールは読み直さない。ただし登録した場所 (B) から import したライブラリは「利用者のパッケージ」と同じに扱い、一緒に読み直す ([user-code.md#2](user-code.md#2-置き場所-探す範囲))。

**状態の表示**: ノードは 1 秒ごとに (変わったときだけ) 状態の JSON をサーバーの一時ディレクトリ (`<runtime>/<id>.status.json`) に原子的に書く: 状態 (`running` / `import_error` / `reload_error` / `stopped`)、シグネチャ、定義の場所、読み込み回数、数 (`received` / `calls` / `published` / `skipped` / `waiting` / `errors` / `reloads`)、最後のエラー `{kind: import|call|convert|publish, message, location, at}`。サーバーは起動中の関数ノードの `GET /api/targets` (と `/ws/live` の targets) に `function_status` として付ける。UI は右ペインと編集画面に表示する。

**ROS への卒業**: 「ROS ノードのコードとして書き出す」(`POST /api/functions/{id}/export-code {directory}`、`function/codegen.py`) で、同じ動きをする普通の rclpy ノードのソース `<directory>/<name>_node.py` を生成する。種類ごとの変換を 1 行ずつ書いた関数 (`input_0(msg)` など)、`None` は送らない・例外はログにして止まらない処理、QoS、`main()`、ament_python のパッケージに入れる手順 (setup.py の `entry_points`、package.xml の依存、`colcon build` / `ros2 run`) をコメント付きで含む。生成したコードを読めば「自分の関数が ROS ではこう包まれていた」と学べ、ツールなしで動かすときの移行先になる。書き出し先はワークスペース内 (realpath の包含、制御文字は拒否 = launch の書き出しと同じ検査)。生成したソースは書く前に `compile()` で確かめる。既にあるファイルは roshanavi が生成したもの (先頭の印) だけ置き換え、利用者のファイルは上書きしない (409 `file_exists`)。値は検証済みのものを `repr()` で埋め込む。

**API**: `GET /api/functions/modules` (`{workspace, modules[{module, ros_package, file}]}`)、`GET /api/functions/module?name=` (`{module, ros_package, file, functions[{name, line, signature, params[{name, annotation, kind, optional}], required, returns, returns_kind, doc, varargs}]}`)、`POST /api/functions` (`?start=true`)、`PUT /api/functions/{id}`、`POST /api/functions/{id}/export-code`。削除・起動・停止・ログは `/api/targets/{id}`。

**サンプル**: `roshanavi_examples/logic.py` (ROS を import しない): `shout` (文字列 → 文字列)、`only_long` (短い文字列は `None` = 送らない)、`invert` (画像 → 画像、numpy)、`add` (数値 × 2 → 数値、複数入力)、`wave` (周期、経過秒 → 正弦波)。`examples/demo_project` に `text_shout` (`/chatter` → `/shouted`、自動起動なし)。

**詳細計測モード ([measurement.md#詳細計測モード](measurement.md#詳細計測モード-トレース計測-p47)) での見え方**: 関数ノードは rclpy なので受信数だけ (変換ノードと同じ)。

## クラスノード (状態を持つ処理を、そのままノードにする)
**目的**: 実際のロジックは「初期化 → 処理のたびに内部状態を更新 → 必要に応じてリセット」というクラスで書かれることが多い。関数ノードの拡張として、ROS を import しない普通の Python クラスを、そのままノードとして動かす。関数ノードと同じく **ROS のコードを書かない**。

```python
# roshanavi_examples/stateful.py — ROS を import しない、普通のクラス
class MovingAverage:
    def __init__(self, window: int = 5):
        self.window = window
        self.values = []

    def process(self, x: float) -> float:
        self.values = (self.values + [x])[-self.window:]
        return sum(self.values) / len(self.values)

    def reset(self) -> None:
        self.values = []
```
「＋ 関数・クラスノードを作る」→「クラス」→ モジュール `roshanavi_examples.stateful`、クラス `MovingAverage`、`process` の入力 `/number`・出力 `/average`、`reset` を「操作メソッド」に、で動く。

| クラスの部分 | roshanavi の仕組み |
|---|---|
| `__init__` の引数 (型ヒントと既定値) | ROS のパラメータ。UI のパラメータ画面や `ros2 param set` で変えると `on_param_change(name, value)` が呼ばれ (無ければインスタンスを作り直し)、不正な値は理由付きで断る |
| 処理メソッド | 関数ノードと同じ呼び出し方 (受信ごと / 周期 / 複数入力)。1 つのクラスの複数メソッドを別々のトピックに割り当てられる |
| 戻り値が dict | キーごとに別の出力トピックへ送る |
| 操作メソッド (引数なし。`reset` など) | 地図の右クリックとノード詳細の「<メソッド名> を呼ぶ」ボタン、トピック `/<ノード名>/<メソッド名>` (`std_msgs/Empty`)、シナリオの `call` ステップ |
| `close()` (なければ `shutdown()`) | ノード停止時に呼ぶ (後片付け)。作り直しで捨てる古いインスタンスにも呼ぶ |
| `get_state()` / `set_state(state)` | あれば、ホットリロードで状態を引き継ぐ |

**実行のしくみ (決定: 関数ノードの実行ファイルを拡張する)**
- 同じ `ros2 run roshanavi function --config <yaml>` で動く。設定は `{class: <ClassSpec>, workspace: <root>, status_file?: <path>}` (関数ノードは `function:` キー)。新しい実行ファイルにしなかった理由: プロセスの起動・停止・自動再起動・ログ・launch への書き出し (`executable='function'`)・状態ファイル・利用者コードの import の閉じ込め・ホットリロードの見張りを、そのまま使えるため。違うのは「関数を 1 つ呼ぶ」代わりに「クラスのインスタンスを 1 つ持つ」ことだけで、そこは `function/class_core.py` に分けた。
- 仕様は `ClassSpec` (`launcher/schema.py`): `id`、`name`、`namespace`、`module`、`class_name`、`params` (`__init__` の引数の開始値)、`methods[]` (処理メソッド: `method`、`call`、`inputs[]`、`outputs[]` (dict を返すなら各出力に `key`)、`rate_hz`、`trigger`)、`actions[]` (操作メソッド)、`autostart`、`auto_restart`。プロジェクトの `classes:` に保存し、ID は他の種類と合わせて一意。検査: 1 つ以上のメソッドをつなぐか操作メソッドを決める、`close` / `shutdown` / `get_state` / `set_state` / `on_param_change` は roshanavi が呼ぶのでつなげない、1 つのメソッドを「つなぐ」と「操作」の両方にしない、出力トピックの重複と「入力と同じ」を拒否、出力が複数のメソッドは全部にキー。
- **空のリスト (API とファイル)**: 入力の無いメソッド (周期で動く出す側、例 `render() -> 画像`) や出力の無いメソッド (受けるだけ、例 `on_pose(pose) -> None`)、メソッドの無い (操作メソッドだけの) クラスは普通にある。プロジェクトファイルは空のリストを書かない (`clean_dict`) が、API が返す仕様 (`GET /api/targets`、`GET /api/project`) は `inputs` / `outputs` / `methods` / `actions` を空でも `[]` で返す (`schema.api_dict`)。画面はこれらを必ず `?? []` で受ける (地図の口のモデルが `undefined.map` で落ちて「Cannot read properties of undefined (reading 'map')」と出た不具合の再発防止)。
- 起動ターゲットの種類は `class`、地図の役割は **`function` (関数ノードと同じ系統のピンク)**。凡例は「関数・クラスノード」、ノード一覧の役割は「関数・クラス」(絞り込みも同じ)、右クリックは「クラスノードの設定を変更」。種類を分けたのは、仕様と設定画面が関数と違うため。色と役割は同じにして、初心者が「自分のロジックのノード」を 1 つの系統として見られるようにした。
- クラスの一覧は **`ast` の静的解析だけ** (`function/class_modules.py`。サーバーでは import しない。`security.md` の閉じ込めは関数ノードと同じ): トップレベルの公開クラスごとに、`__init__` の引数 (型ヒント・既定値・パラメータにできる種類)、公開メソッド (シグネチャ・戻り値の注釈・「引数なしで呼べる = 操作メソッドにできる」か)、定義しているフック。`staticmethod` / `classmethod` / `property` は一覧に出さない。

**`__init__` の引数 = パラメータ** (`function/class_params.py`)
- 種類は [データの種類](#データの種類-ros-のメッセージ型を意識させないp55) の表と同じ注釈の対応で決める: `str` → 文字列 (STRING)、`float` → 数値 (DOUBLE)、`int` → 整数 (INTEGER)、`bool` → ON/OFF (BOOL)、数値の `list` → 数値の並び (DOUBLE_ARRAY)、`dict` / 数値以外の `list` → JSON (JSON テキストの STRING)。型ヒントが無ければ既定値の型から決める。画像・バイト列など、パラメータにできない型の引数は宣言せず、Python の既定値で動く (既定値が無い引数は「値がありません」と表示)。
- 開始値の優先順位: `ros2 run ... --ros-args -p` → `ClassSpec.params` → `__init__` の既定値。既定値が `None` や、値のない必須の引数は「未設定」で宣言し、未設定のままなら引数を渡さない (必須なら「初期化に失敗」と理由を表示し、パラメータを設定すれば作り直す)。`params` に書いた値は型で厳密に検査する (整数の引数に小数、など)。`__init__` に無い名前は警告として状態に出す。
- 変更時 (`ros2 param set` / UI): ① 型が合わなければ ROS が断る (宣言した型のため) ② `on_param_change(name, value)` があればそれを呼び、インスタンスは作り直さない (例外ならその理由を返して変更を断る) ③ 無ければ **新しい値でインスタンスを作り直し、状態はリセット** (UI に「状態をリセットしました」)。作り直しに失敗 (`__init__` が例外) したら古いインスタンスのまま、理由を `ros2 param set` の応答と画面に出す。パラメータの変更は決まった順 (単一スレッド) で処理し、10 秒待っても終わらなければ断る。
- 動いている間のパラメータの値はノードの ROS パラメータが持つ。プロジェクトの `params` (開始値) は編集画面で変え、「保存して再起動」で反映する。

**処理メソッドと出力**
- 受信のたびに呼ぶ / 周期 / 複数入力は関数ノードと同じ ([nodes.md#関数ノード](#関数ノード-ふつうの関数をそのままノードにするp55))。入力の種類 (`kind`) だけで型を省くと、地図にある既存トピックの型を採用する規則も同じ。メソッドごとに入力・出力・呼び出し方を持つので、1 つのクラスが複数のトピックに別々の働きをする。
- 戻り値: `None` は送らない。出力が 1 つでキーなしなら戻り値全体をその種類に変換して送る (JSON の種類なら dict もそのまま)。出力にキーを付けると **戻り値は dict** で、キーごとに別のトピックへ送る (キーが無い・`None` の出力は送らない。dict に出力の無いキーがあっても無視し、状態に `ignored_keys` として出す。dict 以外を返したら変換エラー)。出力が 0 個のメソッドは戻り値を使わない (副作用だけ)。
- 例外・変換の失敗は関数ノードと同じ扱い (ログと画面に ファイル:行番号 (関数名) 付きで出し、ノードは止めない)。

**操作メソッド (引数なし、`reset` など)**
- ノードは各操作メソッドについて、トピック `~/<メソッド名>` (= `/<名前空間>/<ノード名>/<メソッド名>`、`std_msgs/Empty`、reliable) を購読し、届くとそのメソッドを呼ぶ。ボタン・シナリオ・`ros2 topic pub --once /<ノード名>/reset std_msgs/msg/Empty` のどれも同じ道を通る。サービス (`std_srvs/Trigger`) は #35 の後で足す。
- 呼び出しはノードの状態に **記録** する: 呼んだ回数 (`count`)、最後の時刻、成功か失敗か、戻り値 (200 文字まで) またはエラー (場所付き)。記録は呼び出しのたびにすぐ状態ファイルへ書く。サーバーの `POST /api/classes/{id}/call` と、シナリオの `call` は、`std_msgs/Empty` を送ったあと **記録の `count` が増えるのを待ち**、結果 (戻り値・エラー) を返す。待つ上限は 5 秒。
- そのトピックは「購読だけで送り手がいない」状態が普通なので、診断 (受信なし・送信なし・いなくなった警告・開発中ノードの入力なし) から除く (`diagnostics.diagnose(quiet_topics=)`)。

**呼び出しは 1 本のスレッド (保証)** (`function/serial.py`)
- `__init__`、処理メソッド、操作メソッド、`on_param_change`、ホットリロード (新しい import・新しいインスタンス・状態の引き継ぎ)、`close()` は **すべて 1 本の作業スレッドで、受け付けた順に 1 つずつ** 呼ばれる。同時に 2 つが動くことも、別のスレッドから呼ばれることもない。利用者はロックを書かなくてよい (DB 接続や GUI 部品などスレッドを選ぶものも安全)。ROS のコールバックは受け取った値を変換して作業スレッドに依頼するだけ。
- 作業のキューは 1000 件まで。クラスの処理が追いつかず溢れたら、新しいメッセージを捨てて数える (状態の `dropped`)。メモリを使い切らない。周期の呼び出しはメソッドごとに 1 件しか待たせない (遅いメソッドで周期が積み上がらない)。
- 例外は、モジュール直下のコード (import 時に動く部分。ノード起動時に 1 回だけ起動側のスレッドで動き、ホットリロードのときは作業スレッドで動く)。クラスのメソッドは必ず作業スレッド。

**`close()` と停止** — ノード停止 (SIGINT / SIGTERM) では、入力を止めたあと、作業スレッドでインスタンスの `close()` (無ければ `shutdown()`) を呼ぶ。**待つのは最大 3 秒**: それを超えたら記録して終了する (ノードの停止が止まらない)。`close()` の例外も記録するだけで、停止は続く。

**ホットリロードと状態** (`function/class_core.py`、ファイルの見張りと新しい import は関数ノードと同じ [loader](#関数ノード-ふつうの関数をそのままノードにするp55))
- ファイルを保存すると、作業スレッドで ① 新しく import し直す (失敗したら古いモジュールに戻る) ② `__init__` の引数が変わっていればパラメータを宣言し直す ③ **新しいインスタンスを作る**。作ってから古い方の `close()` を呼ぶ (作成に失敗したとき古い方を動かし続けるため。同じ資源を `__init__` で取り合うクラスは `get_state` / `set_state` を使う)。
- 既定は **状態をリセット** (新しい `__init__` からやり直し)。画面に「状態をリセットしました (時刻、ファイルを保存したため)」と出す。古いインスタンスに `get_state()` が、新しいクラスに `set_state(state)` があれば、**状態を引き継ぐ** (「状態を引き継ぎました」)。
- 失敗 (構文エラー・import の例外・クラスの名前が変わった・新しい `__init__` の例外・`get_state` / `set_state` の例外) は、**古いインスタンスが動き続け**、状態 `reload_error` と理由・場所を表示する。直して保存すると読み込む (関数ノードと同じ)。
- 最初の `__init__` の例外は「初期化に失敗」(状態 `init_error`) として表示し、ファイルの修正かパラメータの変更を待つ。起動直後の初期化中は `starting`。

**状態の表示**: 関数ノードの状態ファイルに加え、`kind: class`、状態 (`starting` / `running` / `import_error` / `init_error` / `reload_error` / `stopped`)、パラメータ (名前・種類・現在の値・必須か)、警告、メソッドごとの呼び出し数、操作メソッドの記録 (上記)、最後の通知 (`notice`: `{kind: reset | kept, reason: reload | param, at}`)、定義しているフック。数は `received` / `calls` / `published` / `skipped` / `waiting` / `errors` / `reloads` に `dropped` (溢れて捨てた) と `resets` (作り直した回数) を足す。

**API** (`server_functions.py`): `GET /api/functions/module?name=` は `classes[{name, line, signature, init_params[{name, annotation, has_default, default, default_text, kind}], methods[{name, line, signature, params, required, returns, returns_kind, action_candidate, doc}], hooks, doc}]` も返す。`POST /api/classes` (`?start=true`)、`PUT /api/classes/{id}`、`POST /api/classes/{id}/call {method}` (`{method, topic, record}`。動いていない 409 `not_running`、操作メソッドでない 404 `unknown_action`、5 秒待っても呼ばれない 504 `call_failed`)、`POST /api/classes/{id}/export-code {directory, lifecycle?}`。削除・起動・停止・ログは `/api/targets/{id}`、状態は `function_status`。詳細は [api.md](api.md)。

**シナリオ** ([scenarios.md](scenarios.md)): ステップ `call: {node, method, timeout?}` (操作メソッドを呼び、実行されるまで待つ。例: reset のあとに出力が初期値に戻ることを確かめる)、setup の `class: {...}` (`ClassSpec`。関数ノードの `function:` と同じ)。例: `examples/scenarios/class_moving_average.yaml`。

**ROS への卒業 (コード書き出し)** (`function/class_codegen.py`、`POST /api/classes/{id}/export-code`、書き出し先・検査・上書きの扱いは関数ノードと同じ)
- クラスを包む、コメント付きの普通の rclpy ノード `<directory>/<name>_node.py` を生成する。入力・出力ごとの変換関数 (`input_0_0(msg)`、`to_message_0_0(result, stamp)`)、`__init__` の引数を宣言するパラメータ (`INIT_PARAMETERS`)、パラメータ変更の処理 (`on_param_change` があればそれを呼び、無ければ作り直す)、`run_method` (`None` は送らない・dict はキーごとに送る・例外はログにして止まらない)、操作メソッドの `~/<メソッド名>` の購読、`close()` を呼ぶ後片付け、`main()`、ament_python のパッケージに入れる手順をコメント付きで含む。`rclpy.spin` は 1 本のスレッドなので、書き出したコードでもメソッドは同時に呼ばれない。
- **`lifecycle: true`** で rclpy の `LifecycleNode` として書き出す。対応: `__init__` → `on_configure` (インスタンスを作り、パブリッシャーを作る)、メソッドの購読・周期のタイマー・操作メソッドの購読 → `on_activate` (`on_deactivate` で外す。インスタンスと状態は残る)、`close` → `on_cleanup` (インスタンスを捨てる)。パブリッシャーは `create_lifecycle_publisher` で、activate の間だけ送る。`ros2 lifecycle set /<ノード名> configure` → `activate` の順で進める (生成ファイルの先頭に書く)。ROS の lifecycle を学ぶ教材にもなる。rclpy の `LifecycleNode` の API (`create_lifecycle_publisher`、`on_configure` ほか) は Jazzy と Lyrical で同じ (両方で実行して確かめた)。
- 生成したソースは書く前に `compile()` で確かめる。値は検証済みのものだけを `repr()` で埋め込み、書き出し先は関数ノードと同じ検査 (ワークスペース内の realpath、制御文字は拒否、roshanavi が生成したファイルだけ置き換え)。クラスが無い・`__init__` が静的に読めない場合は 404 `unknown_class` 等で断る。

**対象外**: C++ のクラス (C++ のロジックは普通の ROS ノードとして書き、ランチャーから起動する)。メソッドの引数を持つ呼び出し (操作メソッドは引数なし)。`async def` のメソッド。

**サンプル** (`roshanavi_examples/stateful.py`、ROS を import しない): `MovingAverage(window)` (`process`、`reset`、`on_param_change`、`get_state` / `set_state`)、`Counter(start)` (`process`、`reset`、`close`)、`RunningStats()` (平均・件数・最大を 1 つの dict で返して 3 つのトピックへ)。`examples/demo_project` に `moving_average` (`/number` → `/average`) と `message_counter` (`/chatter` → `/message_count`)、どちらも `reset` つきで自動起動なし。シナリオ `examples/scenarios/class_moving_average.yaml` が `call` と reset を使う。

**詳細計測モード ([measurement.md#詳細計測モード](measurement.md#詳細計測モード-トレース計測-p47)) での見え方**: 関数ノードと同じ (rclpy なので受信数だけ)。
