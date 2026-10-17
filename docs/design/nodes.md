# roshanavi — ノード (入力・変換・関数・サンプル)

入力ノード (恒久ダミー)、変換ノード、関数ノード、同梱サンプルノード、データの種類 (ROS のメッセージ型を意識させない仕組み)。起動・停止・プロジェクトへの保存は [launcher.md](launcher.md)、画面は [ui.md](ui.md)。

## 恒久ダミーノード (P3)
- `ros2 run roshanavi dummy --config <yaml> --ros-args -r __node:=<name>`: 1 つの注入 (once / periodic / stream、`${}` 式、JSONL / CSV) を **独立した ROS ノード** として実行する。injector をそのまま使い、SIGINT / SIGTERM まで動き続ける (once や count 付きでも、送り終えた後もノードは残る)。設定エラーは終了コード 2、注入エラーは 1。
- Launcher が `kind: dummy` のターゲットとして管理する (役割 `dummy`、ノード名を `__node:=` で渡すので対応づけは exact)。設定 YAML (`{dummy: <DummySpec>, data_dir}`) はサーバーの一時ディレクトリに書く。
- 注入タブの実行中ジョブから「常駐ノードにする」で、同じペイロード・モード・レート・QoS の恒久ダミーを作って起動し、元のジョブは止める (`POST /api/inject/{id}/persist`)。
- **書き出し**: ワークスペース内の指定ディレクトリ (realpath で包含を検査、なければ作る) に `<id>.yaml` と `roshanavi_dummies.launch.py` を書く。`ros2 launch <dir>/roshanavi_dummies.launch.py` で、roshanavi のサーバー / UI なしで動く。ただし roshanavi パッケージのインストールは必要 (各ノードが `roshanavi dummy` を実行するため。生成ファイルの先頭に明記)。ノード名・ID は検証済みの値だけを `repr()` で埋め込む。

## 恒久ダミーの一時停止
- dummy ノードは bool パラメータ `paused` を宣言する。true にすると注入ジョブを一時停止する (ノードは動き続ける)。地図の「一時停止・再開」はこのパラメータを [launcher.md#ノードのパラメータと型の定義](launcher.md#ノードのパラメータと型の定義-p45a) の API で変える (`ros2 param set` でも同じ)。

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

**試算 (プレビュー)** (`transform/preview.py`、`POST /api/transforms/preview {spec, samples}`): ノードと同じ `Computer` と `msgutil.build` で、送らずに計算だけする。`samples` は入力の別名ごとの素の dict (UI が `/ws/echo` で受けた最新のメッセージ。届いていなければ省略し、サーバーが入力の型の既定値で代わりに計算して `templated` に別名を返す)。常に 200 で `{ok, passed, output, errors[{path, code, message, params}], templated, relay}` を返す (仕様の検査エラーも `spec_invalid` として同じ形)。`passed: false` かつエラーなしは「条件に合わないので送らない」。出力の型に合わない値は `build_invalid_value` などを、メッセージの先頭のフィールドの場所に付ける。サンプルは最大 8 個、深さ 32 まで。エコーは長い配列を先頭 32 個に切り詰めた形 (`{_truncated, length, head}`) で送るため、32 個を超える配列のフィールドを使う式はプレビューと実際の結果が違うことがある (既知の制限)。

**詳細計測モード ([measurement.md#詳細計測モード](measurement.md#詳細計測モード-トレース計測-p47)) での見え方**: 変換ノードは rclpy なので、トレースで測れるのは **受信数だけ** (処理数・処理時間は「未対応」、理由 `rclpy`)。送信は C++ 計測ノード ([measurement.md#C++ 計測ノード](measurement.md#c-計測ノード-roshanavi_probe-p46)) で送信ノードごとに実測される。編集画面にもこの注意を書く。
- 制約: 式は 1 メッセージあたり Python で評価するので、数百 Hz を超える入力や大きい配列のフィールド計算には向かない (大きい型は relay のみ)。

## 同梱サンプルノード (`roshanavi_examples`, P5)
チュートリアル、デモ、自動テストの対象を兼ねる。初めて ROS を触る人が読む前提で、各ファイルの先頭に「何を受けて何を出すか・パラメータ・実行例・なぜその言語か」を書き、処理の中身にもコメントを付ける。各ノードに `launch/<name>.launch.py` (引数でトピックとパラメータを変える) がある。

**言語の分け方**: 画像の 2 つは C++ (rclcpp)、ほかの 2 つは Python (rclpy)。詳細計測モード ([measurement.md#詳細計測モード](measurement.md#詳細計測モード-トレース計測-p47)) で、C++ のノードは受信・処理・処理時間まで、Python のノードは受信数だけが測れる。その違いを同じデモの中で見比べられるようにわざと混ぜた。画像処理は C++ の方が自然 (1 画素ずつのループ) で、状態遷移や音量の計算は Python の方が短く読みやすい。

| ノード | 言語 | 受信 → 送信 | パラメータ | 詳細計測モードで測れるもの |
|---|---|---|---|---|
| `image_filter` | C++ | `image` (Image: rgb8 / bgr8 / rgba8 / bgra8 / mono8) → `image_gray`、`image_edges` (どちらも mono8、同じ大きさ) | `keep_stamp` (bool, true: 入力の `header.stamp` を引き継ぐ / false: いまの時刻)、`process_delay_ms` (int, 遅い処理の再現) | 受信・処理・処理時間。`process_delay_ms` を大きくすると「処理が追いついていません」 |
| `blob_detector` | C++ | `image` → `detections` (`vision_msgs/Detection2DArray`。bbox の中心・大きさ、`class_id: blob`、`score` = 平均の明るさ / 255、header は入力のまま。見つからなくても空の配列を毎回送る) | `threshold` (0〜255, 200)、`min_area` (30)、`max_detections` (20) | 受信・処理・処理時間 |
| `audio_level` | Python | `audio` (`input_type: stamped` → `audio_common_msgs/AudioDataStamped` の S16LE、`int16` → `std_msgs/Int16MultiArray`) → `level_db` (Float32、RMS の dBFS、無音は -120)、`silence` (Bool) | `input_type`、`silence_below_db` (-45)、`sound_above_db` (-35): 2 つのしきい値の間では状態を変えない (ヒステリシス) | 受信数だけ |
| `state_machine` | Python | `cmd` (String: start / stop / fault / reset、大文字小文字は無視) → `state` (String: IDLE / RUNNING / ERROR) | `initial_state` (IDLE)、`publish_period_sec` (1.0, 0 で変化時だけ) | 受信数だけ |

- 画像処理は OpenCV を使わず `include/roshanavi_examples/image_ops.hpp` の純粋な関数 (グレースケール: 整数の BT.601 の重み、エッジ: 3x3 Sobel の |gx|+|gy| を 255 で頭打ち・端は 0、塊: 4 近傍の塗りつぶし (再帰しない)、面積の大きい順) にまとめ、gtest (`test_image_ops`) で ROS なしにテストする。ノードは ROS のメッセージとの変換だけ。パラメータは毎回読むので、実行中の変更 (地図のパラメータ・`ros2 param set`) がすぐ効く。壊れた画像 (大きさが足りない・未対応の encoding) は 5 秒に 1 回の警告で捨てる。
- QoS: 購読は best effort (SensorDataQoS。どの送信者からも受けられる)、送信は reliable (どの購読者でも受けられる)。`state_machine` の `state` は transient local (後から購読したノードにもいまの状態が届く)。
- Python のノードは計算の部分 (`level_db`・`SilenceDetector`・`StateMachine`) を ROS なしのクラス・関数にし、pytest で直接テストする。ROS の import は `main()` の中。
- `audio_common_msgs` は `input_type: stamped` のときだけ必要 (package.xml は exec_depend)。`vision_msgs` は新しい依存 (`ros-jazzy-vision-msgs`)。
- 起動設定の例: `examples/demo_project` (autostart なし)、`examples/perception_demo` ([launcher.md#デモ構成](launcher.md#デモ構成-p45a))。

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
| 音声 | `audio` | `audio_common_msgs/AudioDataStamped` (無ければ `std_msgs/Int16MultiArray`) | numpy int16 (サンプル、または サンプル×チャンネル) |
| バイト列 (生データ) | `bytes` | `std_msgs/UInt8MultiArray` | `bytes` |
| 専用の型 (詳細設定モード) | `message` | 指定した任意の型 | メッセージ全体の dict 表現 |

- **対応表は 1 か所** (`roshanavi/data_kinds.py`): 種類 ↔ 型、インストールされている型の選択 (音声の代替)、既存の型 → 種類 (互換の型: `Float32` → 数値 (小数)、`Int8`〜`UInt64` → 整数、各種 `*MultiArray` → 数値の並び、`AudioData` → 音声。型はそのまま使う)、Python の値との変換 (`to_python` / `from_python`、画像・音声はメディアのアダプタ [input-and-media.md#メディア](input-and-media.md#メディア-アダプタファイルソースブラウザ入力ビューア-p4) 経由で変換は型ごとに 1 つ)、詳細設定モードの並び (`type_groups`)。入力ノード・変換ノード・関数ノード・メディアのアダプタ (`/api/media/types` の `data_kind`) が共有する。`GET /api/data-kinds` は `{kinds[{id, type, available, python}], type_kinds, common_types}`。表示名は UI の i18n (`i18n/messagesKinds.ts`)。
- 変換は厳密: 数値に `bool` や文字列は渡さない、整数は整数値の float まで、画像は uint8 で 2 次元か 3 チャンネル、音声は int16。合わないときは「出力の種類 int には int が必要ですが、関数は str を返しました」のように型名付きのエラー (`KindError`)。
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
roshanavi で「＋ 関数ノードを作る」→ モジュール `my_pkg.logic`、関数 `shout`、入力 `/chatter`、出力 `/shouted` を選ぶだけで、ノードとして動く。

| 呼び出し方 (`call`) | 内容 |
|---|---|
| 受信のたびに呼ぶ (`on_message`) | 入力 1 つ。届いた値を引数にして関数を呼び、戻り値を出力トピックに送る |
| 一定周期で呼ぶ (`periodic`、`rate_hz`) | 入力なし。引数なしで (必須の引数が 1 つなら起動からの経過秒を渡して) 周期的に呼ぶ (センサーの代役など) |
| 複数入力 (`multi_input`、`trigger`) | 入力 2〜8 つ。各入力の最新値を入力の順に引数へ渡す (変換ノードと同じ結合ルール `transform/pipeline.Joiner`: 全部の入力が 1 回届くまで呼ばない、`trigger` は `any` か入力のトピック) |

- 戻り値が `None` のときは送らない (条件付きで出したいとき用、`skipped` に数える)。
- 例外が起きたら、そのメッセージは送らず、ログと画面に「関数でエラーが起きました」と **ファイル:行番号 (関数名)** 付きで出す (利用者のパッケージ内でいちばん深いフレーム。ログは 5 秒に 1 行まで、抑えた件数を添える)。ノードは止めない。値の変換の失敗 (戻り値の型が合わない、届いた JSON が読めない) も同じ扱い。
- 値の受け渡しは [nodes.md#データの種類](nodes.md#データの種類-ros-のメッセージ型を意識させないp55) の表 (入力側も同じ)。関数には ROS のメッセージではなく Python の値を渡す。詳細設定モードの「専用の型」では、メッセージ全体を dict で受け取り、dict で返す。画像・音声の出力には、呼び出しのきっかけになった入力の `header.stamp` を引き継ぐ (latency を測れるように。無ければいまの時刻)。
- 地図上の役割は `function` (変換・ダミーと同じ系統の色で、ピンク。凡例「関数ノード」、ノード一覧の役割「関数」、右クリック「関数ノードの設定を変更」)。プロジェクトの `functions:` に保存し ([launcher.md#プロジェクトファイル](launcher.md#プロジェクトファイル-p3))、自動起動・自動再起動・停止・ログ・launch への書き出し (`executable='function'`) はダミー・変換ノードと同じ。

**実行と安全**
- 関数は独立したノードのプロセス (`ros2 run roshanavi function --config <yaml>`、設定は `{function: <FunctionSpec>, workspace: <root>, status_file?: <path>}`) で動く。**roshanavi のサーバーの中では実行も import もしない**。サーバーはモジュールの一覧と関数のシグネチャを **`ast` の静的解析だけ** で作る (`function/modules.py`: トップレベルの公開 `def`、引数・注釈・既定値の有無・戻り値の注釈・docstring の最初の段落・行番号。注釈から種類を推す: `str` → 文字列、`np.ndarray` → 画像 …)。
- **import できる範囲** (`modules.resolve_module`): `<workspace>/src` の ROS パッケージ (package.xml) の直下にある Python パッケージ (`__init__.py` のあるディレクトリ) のモジュールだけ。モジュール名は `[A-Za-z_][A-Za-z0-9_]*` の最大 8 段。解決したファイルの realpath が `<workspace>/src` とその Python パッケージの内側で通常ファイルであること (外向き symlink は拒否)。`roshanavi` 自身は拒否。data_dir は使わない。import は `sys.path` を触らず、パッケージの `__init__.py` から `spec_from_file_location` で読み、import 後に `__file__` が解決したファイルと一致することを確かめる。利用者自身のコードなので、信頼の水準は自分でノードを起動するのと同じ (サンドボックスはしない)。
- 追加・変更の時点 (`command.validate_function`) でモジュールが解決できなければ 404 `unknown_module`。起動後に import が失敗したときはプロセスを終わらせず、状態 `import_error` で待ち、ファイルが直ったら読み込む。

**ホットリロード (決定: プロセス内で新しく import し直す)** (`function/loader.py`)
- ファイルの保存を 0.5 秒ごとの mtime + サイズの見張りで検出し (書き込みが落ち着くまで 0.2 秒待つ)、利用者のパッケージのモジュールを `sys.modules` から外して **パッケージごと新しく import し直す**。関数はメッセージごとにローダーから読むので、次のメッセージから新しい関数になる。
- 理由: (1) `importlib.reload` は 1 つのモジュールしか読み直さず、同じパッケージの補助モジュールや他のモジュールが持つ古い参照が残る。新しい import ならパッケージ全体が揃う。(2) 新しい import が失敗したら (構文エラー・import 時の例外・関数の名前が変わった)、外したモジュールを戻して **前の関数のまま動き続け**、エラーを場所付きで出す (状態 `reload_error`)。直して保存すれば読み込む。(3) ノード・購読・送信者はそのままなので、DDS の再発見の待ち (プロセスの再起動なら毎回 1 秒程度 + 発見) が無く、複数入力の最新値も失わない。(4) inotify は bind mount や WSL では届かないことがあり、依存も増えるので、ポーリングにした。
- バイトコードは読まず書かない (`sys.dont_write_bytecode`、`pycache_prefix` は空の一時ディレクトリ): 同じ秒・同じサイズの編集でも古い `.pyc` を読まず、利用者のソースに `__pycache__` を作らない。
- 制約: モジュールの大域変数は読み直しのたびに初期化される。C 拡張と、利用者のパッケージの外のモジュールは読み直さない。

**状態の表示**: ノードは 1 秒ごとに (変わったときだけ) 状態の JSON をサーバーの一時ディレクトリ (`<runtime>/<id>.status.json`) に原子的に書く: 状態 (`running` / `import_error` / `reload_error` / `stopped`)、シグネチャ、定義の場所、読み込み回数、数 (`received` / `calls` / `published` / `skipped` / `waiting` / `errors` / `reloads`)、最後のエラー `{kind: import|call|convert|publish, message, location, at}`。サーバーは起動中の関数ノードの `GET /api/targets` (と `/ws/live` の targets) に `function_status` として付ける。UI は右ペインと編集画面に表示する。

**ROS への卒業**: 「ROS ノードのコードとして書き出す」(`POST /api/functions/{id}/export-code {directory}`、`function/codegen.py`) で、同じ動きをする普通の rclpy ノードのソース `<directory>/<name>_node.py` を生成する。種類ごとの変換を 1 行ずつ書いた関数 (`input_0(msg)` など)、`None` は送らない・例外はログにして止まらない処理、QoS、`main()`、ament_python のパッケージに入れる手順 (setup.py の `entry_points`、package.xml の依存、`colcon build` / `ros2 run`) をコメント付きで含む。生成したコードを読めば「自分の関数が ROS ではこう包まれていた」と学べ、ツールなしで動かすときの移行先になる。書き出し先はワークスペース内 (realpath の包含、制御文字は拒否 = launch の書き出しと同じ検査)。生成したソースは書く前に `compile()` で確かめる。既にあるファイルは roshanavi が生成したもの (先頭の印) だけ置き換え、利用者のファイルは上書きしない (409 `file_exists`)。値は検証済みのものを `repr()` で埋め込む。

**API**: `GET /api/functions/modules` (`{workspace, modules[{module, ros_package, file}]}`)、`GET /api/functions/module?name=` (`{module, ros_package, file, functions[{name, line, signature, params[{name, annotation, kind, optional}], required, returns, returns_kind, doc, varargs}]}`)、`POST /api/functions` (`?start=true`)、`PUT /api/functions/{id}`、`POST /api/functions/{id}/export-code`。削除・起動・停止・ログは `/api/targets/{id}`。

**サンプル**: `roshanavi_examples/logic.py` (ROS を import しない): `shout` (文字列 → 文字列)、`only_long` (短い文字列は `None` = 送らない)、`invert` (画像 → 画像、numpy)、`add` (数値 × 2 → 数値、複数入力)、`wave` (周期、経過秒 → 正弦波)。`examples/demo_project` に `text_shout` (`/chatter` → `/shouted`、自動起動なし)。

**詳細計測モード ([measurement.md#詳細計測モード](measurement.md#詳細計測モード-トレース計測-p47)) での見え方**: 関数ノードは rclpy なので受信数だけ (変換ノードと同じ)。
