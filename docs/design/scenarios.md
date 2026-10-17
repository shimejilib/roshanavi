# roshanavi — シナリオ (P6)

「この入力を送ったら、○秒以内にこう出る」を YAML のシナリオにして、UI (Scenarios タブ) と CLI で何度でも同じように確かめる。シナリオは **記録モード** で UI の操作から作るのが主軸で、YAML は保存・CI 用の形式 (手で書いてもよい)。実装は `roshanavi/scenario/`、画面は `web/src/scenarios/` ([ui.md#実装メモ (P6: シナリオ)](ui.md#実装メモ-p6-シナリオ))。

対象ユースケース: **センサー処理パイプライン** (画像・点群の前処理・認識) と **自作ノード群** (独自 msg, 状態遷移)。トピックのみ (サービス・アクションは今後対応)。

## ステップの種類

| ステップ | 意味 | 主な項目 |
|---|---|---|
| `send` | 1 件送る | `topic`、`data` (メッセージのフィールド、`${}` 式可) または `kind` + `value` (データの種類の値)、`type` / `qos` (任意) |
| `start` / `stop` | 周期送信・ファイル・メディアを裏で開始 / 停止する | `start: {id, topic, rate_hz, data\|value, count?}`、`stream: <data_dir のファイル>`、`media: {source, ...MediaOptions}`。`id` の既定はトピック名。`stop: <id>` |
| `start: {target}` / `stop: {target}` | プロジェクトの起動設定 (入力ノード・関数ノードなど) を起動 / 停止する | `target: <起動設定の ID>` |
| `call` | クラスノードの操作メソッド (引数なし) を呼ぶ ([nodes.md#クラスノード](nodes.md#クラスノード-状態を持つ処理をそのままノードにする)) | `call: {node, method, timeout?}`。`node` は `/ns/name` か `name`、`timeout` の既定は 5 秒 |
| `play` | bag を再生する | `bag` (data_dir の中)、`topics`、`rate`、`loop`、`wait: true` で終わるまで待つ (`timeout`) |
| `wait` | 指定秒待つ | `wait: 1.0` |
| `expect` | `within` 秒以内に、`where` を満たすメッセージが `count` 件届く | `topic`、`within`、`count` (1)、`where` |
| `always` | `for` 秒間、届くメッセージがすべて `where` を満たす (最低 `min_count` 件、既定 1) | `topic`、`for`、`where`、`min_count` |
| `never` | `for` 秒間、`where` を満たすメッセージが 1 件も来ない (`where` 省略時は「何も来ない」) | `topic`、`for`、`where` |
| `rate` | `for` 秒間の周期が `min_hz..max_hz` に入る | `topic`、`for`、`min_hz` / `max_hz` (片方でも可) |
| `throughput` | 入力の件数に対する出力の件数の比が `min_ratio` 以上 (`max_ratio` 以下) | `input`、`output`、`for` (5)、`min_ratio` |
| `latency` | 入力と出力を対応づけ、処理時間の `p50_ms` / `p95_ms` / `max_ms` を上限で判定 | `input`、`output`、`match`、`for` (5)、`min_samples` (3) |
| `resources` | `for` 秒間のノードの **CPU の平均** (1 コア = 100%) が `cpu_max` 以下、**RSS の最大** が `mem_max_mb` 以下 (片方でも可) | `node`、`for` (5)、`cpu_max`、`mem_max_mb` |
| `mem_growth` | `for` 秒間 (10 秒以上) のノードの RSS の増え方 (最小二乗の傾き) が `max_mb_per_min` MB/分以下 (メモリリークの確認) | `node`、`for`、`max_mb_per_min` |

`resources` / `mem_growth` はトピックではなくノードのプロセスを測る ([resources.md#シナリオ連携](resources.md#シナリオ連携))。ノードはこの PC の同じユーザーのプロセスとして見つかる必要があり (argv の `__node:=`、サーバーではリソース監視の対応づけ)、シナリオ自身が起動したプロセスなら「確実」、それ以外は結果に「推定」と書く。0.5 秒ごとに `/proc` を読む。`mem_growth` にはウォームアップが無いので、起動直後の確保を除くなら前に `wait` を置く。

判定のステップ (`expect`〜`latency`) と guards には任意で `type` / `kind` を書ける (そのトピックをシナリオの最初から型付きで購読する。記録モードは自動で書く)。全ステップに任意の `label`。

**`guards`** はシナリオ全体に掛かる `never` / `always` (`for` なし)。最初のステップからシナリオの終わりまで見張り、どのステップの最中に破れても、そのステップを中断して失敗にする (例: 「ずっと `/state` が ERROR にならない」)。

**`setup`** はステップの前に起動するプロセス。1 項目に次のどれか 1 つ + `wait_for_node` (文字列か配列) / `wait_timeout` (既定 15 秒):

| 種類 | 内容 |
|---|---|
| `run: {package, executable, name?, namespace?, params?, remaps?, args?}` | `ros2 run` |
| `launch: {package, file, args: {name: value}}` | `ros2 launch` |
| `cmd: [ros2, run\|launch, ...]` | 上の 2 つの別の書き方 (`--ros-args` の `-p` / `-r` と `__node:=` / `__ns:=` だけ解釈)。ほかのコマンドは起動しない |
| `target: <id>` | プロジェクトの起動設定 |
| `function` / `class` / `transform` / `dummy: {...}` | 関数ノード・クラスノード (`ClassSpec`)・変換ノード・入力ノードの仕様 ([nodes.md](nodes.md))。`id` は自動、`name` の既定は `scenario_<種類>_<番号>` |

ノード名が分かるもの (`run` の `name`、関数・クラス・変換・入力ノード、名前付きの起動設定) は、`wait_for_node` が無くてもそのノードがグラフに現れるまで待つ。プロセスが途中で終わったり、時間内にノードが現れなければセットアップの失敗 (ログの最後 20 行を付ける)。

## 例

```yaml
# 自作ノード: 状態遷移 (examples/scenarios/state_machine.yaml)
version: 1
name: state_machine
setup:
  - run: {package: roshanavi_examples, executable: state_machine, name: scenario_state_machine,
          params: {publish_period_sec: 0.0}, remaps: {cmd: /scenario/sm/cmd, state: /scenario/sm/state}}
guards:
  - never: {topic: /scenario/sm/state, where: [{field: data, op: eq, value: ERROR}]}
steps:
  - send: {topic: /scenario/sm/cmd, data: {data: start}}
  - expect: {topic: /scenario/sm/state, within: 1.0, where: [{field: data, op: eq, value: RUNNING}]}
  - send: {topic: /scenario/sm/cmd, kind: string, value: stop}
  - expect: {topic: /scenario/sm/state, within: 1.0, where: [{field: data, op: eq, value: IDLE}]}
```

```yaml
# センサー処理 (examples/scenarios/perception.yaml の要約)
steps:
  - start: {id: camera, topic: /scenario/camera/image, type: sensor_msgs/msg/Image,
            media: {source: samples/blobs.mp4, kind: video}, loop: true}
  - expect: {topic: /scenario/camera/detections, within: 5.0,
             where: [{field: detections, op: len_range, min: 1}]}
  - throughput: {input: /scenario/camera/image, output: /scenario/camera/detections, for: 5.0, min_ratio: 0.9}
  - latency: {input: /scenario/camera/image, output: /scenario/camera/detections, match: header.stamp, p95_ms: 200}
  - stop: camera
  - wait: 0.5
  - never: {topic: /scenario/camera/detections, for: 1.0}    # 入力が止まれば出力も止まる
```

```yaml
# 負荷とメモリ (examples/scenarios/busy_cpu.yaml の要約): busy_demo の回避構成 (multi + off)
setup:
  - run: {package: roshanavi_examples, executable: busy_demo_driver, name: busy_cpu_driver, params: {rate_hz: 100.0}}
  - run: {package: roshanavi_examples, executable: executor_busy_demo, name: busy_cpu_target,
          params: {executor: multi, qos_events: 'off', work_ms: 5.0, num_threads: 4, stats_topic: /busy_cpu/stats}}
steps:
  - wait: {seconds: 3.0, label: 起動直後の負荷が落ち着くまで待つ}
  - resources: {node: /busy_cpu_target, cpu_max: 40, mem_max_mb: 300, for: 5.0}   # 実測 平均 7% 前後
  - mem_growth: {node: /busy_cpu_target, max_mb_per_min: 5, for: 10.0}
```
`qos_events` を `'default'` (問題の構成 multi + default) にすると CPU が 1 コア近く (実測 平均 85〜87%) になり、`resources` が「CPU が上限を超えました」で失敗する ([measurement.md#CPU が高い](measurement.md#cpu-が高い-multithreadedexecutor-の空回り))。

サンプル (`examples/scenarios/`): `chatter_smoke` (talker の出力と周期、`cmd`)、`state_machine` (guards)、`perception` (throughput + latency を header.stamp で)、`perception_order` (`keep_stamp:=false` の image_filter を `match: order` で)、`function_shout` (関数ノード `shout`: `/chatter` → `/shouted` が大文字)、`busy_cpu` (`resources` / `mem_growth`)。launch_pytest からの使い方は `examples/launch_pytest/`。

## ファイルの形式と検査 (`schema.py`)
- `version: 1` (省略時 1。ほかの値は拒否)、`name`、`description?`、`setup`、`guards`、`steps` (1〜500 個)。pydantic (v1) で検査し、**未知のキーは拒否**。ステップ・ガード・セットアップの各項目は「種類: 内容」の 1 キー。
- エラーは **パスと行番号** 付き (`steps.1.expect.withn (7 行目): 使えないキーです`)。YAML を `yaml.compose` でノードの木にして、エラーのパスから行をたどる。pydantic の英語のメッセージは種類ごとに平易な日本語にする。YAML の構文エラーも行・列付き。
- 意味の検査: `stop: <id>` はそれより前の `start` / `play` の id であること、止める前に同じ id で始め直さない、`where` の op ごとの値 (`range` は min/max、`regex` はコンパイルできる 500 文字まで、`len_eq` は 0 以上の整数 …)、トピックは絶対名 (rclpy の検査)。
- UI から保存するときは正規化して書く (`dump`: キーは定義順、既定値は省く、`wait` / `stop` は短い形)。YAML を直接編集したときは、検査だけしてテキストのまま保存する (コメントを残す)。

## 判定ルール (`runner.py` / `checks.py`)
- **取りこぼし防止 (事前購読)**: セットアップの後、最初のステップの前に、判定・ガードで参照する全トピックを購読し、メッセージを受信時刻 (monotonic) 付きでためる (`buffers.py`)。型は `type` / `kind` → グラフの順で決め、まだ誰も使っていないトピックは最大 3 秒現れるのを待ち、その後も現れたら途中から購読する (失敗時に「購読を始めたのが ○ 秒後」と出す)。購読後、グラフにいる送信者とつながるまで (最大 1 秒) 待ってから始める。QoS は、いまの送信者がすべて reliable なら reliable、そうでなければ best effort (どちらの送信者からも受けられる)、volatile、depth 100。受信したメッセージは一度だけ素のデータにし、256 要素を超える配列は長さと先頭だけ残す (`len_*` は長さを使える)。1 トピック 20,000 件まで。
- **評価の窓**: 判定ステップは「そのステップの開始以降」に受信したメッセージを評価する。ただし `expect` の直前のステップが入力 (`send` / `start` / `stop` / `play`) なら、その入力を始める直前から数える (送信ステップが終わる前に返ってきた応答を取りこぼさない)。
- 最初に失敗したステップでシナリオを止め、残りは「未実行」。ガードは最後に `finish` で確定する。
- **送信**: `send` / `start` / `play` は注入 ([input-and-media.md#injector](input-and-media.md#injector)) をそのまま使う (シナリオ専用の Injector。受信側がつながるまで最大 1 秒待ってから送る)。型は `type` → `kind` (そのトピックの型が種類に合えばそれ) → グラフの型の順 (最大 2 秒待つ)。`value` に `${...}` を含む文字列は式として毎回評価する (安全な式評価器, [input-and-media.md#expr](input-and-media.md#expr-安全な式評価))。ファイルはすべて data_dir の中。
- `where` の op: `eq ne lt le gt ge range approx regex contains exists len_eq len_range`。field はドット区切り + 配列の番号 (`detections.0.bbox.center.position.x`)。フィールドは `MsgView` の辞書引き・範囲付きの添字で読む (`eval` も `getattr` も使わない)。`eq` は bool と数を区別し、整数と小数は値で比べる。`approx` の `tol` の既定は `|value| × 0.001`。`len_*` は配列 (と文字列) の長さ。
- **周期** (`rate`): 地図・トラフィックと同じ `stats.window_rate` (間隔から計算、止まったら 0、2 件未満は「測れない」)。窓は `for` の全体 (`retain_sec`)。
- **件数の比** (`throughput`): `for` の間の入力と出力の件数の比。
- **処理時間** (`latency`): 入力と出力をどちらも roshanavi の購読で受けた時刻の差 (受信 → 受信)。下の対応づけモード。p50 / p95 は最近傍順位、`min_samples` 組に足りなければ失敗。
- **失敗の説明**: 「何が来て何が足りなかったか」を平易に出す (受信件数、条件に合った件数、最後に届いた値 (新しい順に最大 3 件)、最後の値で合わなかった条件と実際の値、never/always は破った値と時刻)。ステップには **原因の候補** (`hints.py`) を付ける: 判定するトピックに送信者がいない (似た名前のトピック)、送ったトピックを誰も受信していない、QoS が合わない組 (方針ごとに送信側 / 受信側)、1 つのトピックに複数の型、購読できなかった・遅れた。
- **後片付けは必ず行う** (成功・失敗・中止・例外のどれでも): シナリオの注入ジョブを止め、起動設定を元に戻し (シナリオが起動したものは止め、止めたものは起動し直す)、セットアップのプロセスを止め (プロセスグループごと SIGINT → SIGTERM → SIGKILL、[launcher.md#Launcher](launcher.md#launcher-p3))、購読を外す。

## latency の対応づけモード
- `match: header.stamp` (既定): 出力が入力の stamp を引き継ぐノード向け。出力の stamp と同じ stamp の入力 (いちばん最初に届いたもの) と組にする。1 組もできなければ「stamp を引き継いでいないなら match: order を」と出す。
- `match: order`: 受信順に対応づける **近似** (出力は、まだ答えていない最も古い入力に答えたとみなす)。stamp を引き継がないノード向け。取りこぼしがあるとずれるため `throughput` と併用を推奨し、結果に「近似」と表示する。

## CLI と Python API
- `ros2 run roshanavi scenario run <file|dir> [--junit out.xml] [--json out.json] [--data-dir D] [--workspace W] [--project P] [-v]`。ディレクトリなら直下の `*.yaml` / `*.yml` を名前順に全部。終了コード: すべて成功 0、どれか失敗 (ファイルの誤りを含む) 1、引数の誤り (パスが無い・シナリオが無い) 2。結果はステップごとに ✔ / ✘ と説明・原因の候補を出す。
- JUnit (`junit.py`): シナリオごとに `<testsuite>`、セットアップ・ステップ・ガードごとに `<testcase>` (失敗は `failure`、エラー・中止は `error`、未実行は `skipped`)。
- `roshanavi.scenario.run_scenario(path, *, data_dir, workspace, project, runtime, cancel, progress) -> Result`。`runtime` を渡さなければ自分の rclpy コンテキスト (ノード `roshanavi_scenario`) を持つので、launch_pytest のテストの中からも呼べる (`examples/launch_pytest/test_state_machine_launch.py`)。`Result.passed`、`Result.failures()` (失敗の説明の一覧)、`to_dict()`。
- `data_dir` (stream / bag / メディア) の既定は `$ROSHANAVI_DATA_DIR` かカレントディレクトリ、`workspace` は `$ROSHANAVI_WORKSPACE` かカレントディレクトリ、`project` は `target:` が使う `roshanavi.yaml`。

## サーバー (Scenarios タブ) (`service.py` / `store.py`)
- シナリオのファイル: プロジェクトのファイルの隣 (`roshanavi.yaml` なら `<dir>/scenarios/`、ほかの名前なら `<dir>/<stem>_scenarios/`) と、サンプル (`<examples_dir>/scenarios`, 読み取り専用)。クライアントは一覧の id (`project:<file>` / `example:<file>`) だけを送る。ファイル名は `[A-Za-z0-9_][A-Za-z0-9_.-]*\.ya?ml` だけ、realpath がそのディレクトリの直下であること (symlink で外に出られない)。保存は一時ファイル → rename、同名は 409。
- 実行は 1 つずつ (別スレッド、2 つ目は 409 `run_busy`)。ラボの ROS ランタイム・ワークスペースを使い、セットアップはシナリオ専用のプロセス管理で起動する。`target` はラボのランチャーの起動設定を使い、終わったら元に戻す。進み具合は `/ws/scenarios`、中止は `POST /api/scenario-runs/{id}/cancel`。
- 結果は `<data_dir>/scenario_results/<run_id>.json` に新しい 50 件まで。一覧は各シナリオの最後の結果を付ける。

## UI での作り方: 記録モード (主軸)
YAML は保存・CI 用の形式であり、ユーザーは原則として手で書かない。

1. **記録開始**: 確かめたい出力トピック (watch, 最大 8) を選び、記録を始める。サーバーが watch トピックを購読し (タイムラインには、遅いトピックは全件、速いトピックは 10 件の後は毎秒 10 件まで出す。区間の計測には全件の受信時刻を使う)、記録中は上部に「● シナリオを記録中」が出る。
2. **入力操作がステップになる**: 記録中に **どのタブで行った操作も**、サーバーの API (注入の開始・停止、起動設定の起動・停止・再起動) で記録され、`send` / `start` / `stop` / `play` / `start: {target}` / `stop: {target}` になる。操作の間隔は `wait` になる (最初の操作より前の時間と 0.1 秒未満の間隔は除く)。記録の前に始めた注入の停止はステップにしない。
3. **出力をクリックして期待値にする**: タイムラインのメッセージをクリックし「これが来るはず」を選ぶと `expect` ができる (`web/src/scenarios/record.ts`)。
   - フィールドは自動で選ぶ: スカラーは `eq`、小数は `approx` (許す差 = 値の 1%)、番号だけ違う文字列 (`Hello World: 12` と `…: 13`) は正規表現 `^Hello World: \d+$`。`header.stamp` や名前が `stamp / time / sec / nanosec / seq / count / counter …` のもの、メッセージごとに必ず違う整数 (カウンタ)、メッセージごとに長さが変わる配列、大きな配列、長い配列 (5 個以上) の要素は既定で外し、理由を添えてチェックボックスで調整できる。値も直せる。
   - `within` は実測の応答時間 (直前の操作からそのメッセージまで) × 3、最低 0.5 秒 (0.1 秒単位で切り上げ)。
   - 判定のステップには watch トピックの型 (`type`) を書く (再実行のとき最初から購読できる)。
4. **種類を変える**: Shift+クリックで区間を選び、`always` (選んだメッセージのフィールドを条件に)、`never`、`rate` / `throughput` / `latency` を作る。`for` は区間の長さ (選ばなければ 2 秒)。しきい値はサーバーが記録を同じ判定のコード (`window_rate`、stamp / 受信順の対応づけ) で測った値から提案する: 周期は実測 × 0.8〜1.2、件数の比は実測 (1 まで) × 0.9、処理時間 p95 は max(実測 × 2, 実測 + 20 ms)。stamp で 1 組も対応づかなければ受信順 (近似) にする。作った期待はカードで種類・数値を変えられる。
5. **保存して再実行**: 名前を付けて保存すると YAML になり、Scenarios タブと CLI から再実行できる。Scenarios タブでは一覧 (プロジェクト / サンプル)、実行 (ステップごとの結果・説明・原因の候補)、フォームでの編集 (詳細設定モードでは YAML を直接)、確認付きの削除ができる。サンプルは「コピーして編集」でプロジェクトにコピーする。

## 制約・既知の問題
- サービス・アクションは未対応 (トピックのみ)。
- 処理時間は roshanavi の購読で受けた時刻の差なので、DDS の配送時間を含む (詳細計測モードの処理時間とは別物)。
- 判定する重い型 (画像など) は Python で受けるので、高いレートでは roshanavi 側の受信が落ちて throughput を下げることがある。
- 記録モードのタイムラインの値は、エコーと同じく長い配列を先頭 32 個に切り詰めた形。
- 記録中にほかの人が同じサーバーで行った操作も記録される (記録は 1 つだけ)。
