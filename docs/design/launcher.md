# roshanavi — Launcher とプロジェクト

ノードの起動・停止・再起動・ログ・ビルド、ノード ⇄ プロセスの対応づけと役割、プロジェクトファイルとその切り替え、パラメータ、lifecycle、launch ファイルの分解取り込み、ノード一覧。

## Launcher (P3)

自分のノードと依存ノードを GUI で起動・停止・再起動し、ログを見て、ビルドし直す ([vision.md#主要ユーザー体験](../overview/vision.md#主要ユーザー体験-ノード単体開発者の-1-日) の 3)。`roshanavi/launcher/`。

**ワークスペースの走査 (`discovery.py`)**
- ワークスペースは `--workspace` (既定: `$ROSHANAVI_WORKSPACE` → カレントディレクトリ)。`install/` (分離・merged 両方) を先に、続いて `AMENT_PREFIX_PATH` を overlay 順に見る。
- パッケージ = ament index (`share/ament_index/resource_index/packages`)。実行ファイル = `lib/<pkg>/` の実行可能ファイル、launch ファイル = `share/<pkg>/launch/` (2 階層まで) の `*.launch.{py,xml,yaml}` と `*_launch.{py,xml,yaml}`。
- `origin`: `<ws>/install` 由来なら `workspace`、それ以外は `system`。`sourced`: サーバー起動時の `AMENT_PREFIX_PATH` に入っていたか。`src/` の `package.xml` を走査して `source_dir` を付ける (`COLCON_IGNORE` 等は除外)。未ビルドのパッケージも `built:false` で一覧に出す (ビルドボタン用)。
- 結果はキャッシュし、`POST /api/workspace/refresh` とビルド成功時に再走査する。

**プロセス管理 (`process.py` / `target.py` / `manager.py`)**
- `subprocess.Popen(argv list)` のみ (シェルは使わない)。`start_new_session=True` で新しいセッション = プロセスグループにし、`ros2 launch` が起こす子孫も同じグループに入れる。
- 停止: グループに SIGINT → 5 秒待つ → SIGTERM → 3 秒 → SIGKILL。開始時点の子孫のうちグループ外に出たものも最後に kill する。
- 状態: `stopped` / `starting` (起動後 2 秒。ただしノードが地図に対応づいた時点で、2 秒未満でも `running` にする。一覧 API `launcher.targets()` で合わせる) / `running` / `exited` (自分で 0 終了) / `crashed` (自分で非 0 終了) / `invalid` (設定が検証を通らない。例: パッケージが消えた)。稼働時間、再起動回数、`pending_restart` (実行中に設定を変えた) を返す。世代番号で、古いプロセスの終了通知が新しいプロセスの状態を上書きしないようにする。
- 自動再起動 (`auto_restart`、既定 off): `crashed` のとき 1, 2, 4 … 最大 30 秒のバックオフで再起動する。30 秒以上動いたら間隔を戻す。ユーザーが止めたら再起動しない。
- ログ: stdout / stderr を行単位で読み、`stream` タグ付きでターゲットごとのリングバッファ (5000 行) に入れる。起動コマンドと終了コードは `system` 行として残す。子プロセスの環境に `PYTHONUNBUFFERED=1`, `RCUTILS_LOGGING_BUFFERED_STREAM=0`, `RCUTILS_COLORIZED_OUTPUT=0` を入れ、遅延と色コードをなくす。
- サーバー終了時に全ターゲットを並列に停止する。uvicorn の SIGINT/SIGTERM 処理の後の `finally`、SIGHUP → SIGTERM への読み替え、`atexit` の 3 経路で呼ぶ (冪等)。サーバー自身が SIGKILL された場合は次の「子プロセスの後始末」。
- `env` (`kind: run`): サーバーの環境に足す環境変数 (launch ファイルの引き取りで引き継いだもの。読み込むコードを左右する名前は拒否、[security.md](security.md))。roshanavi のログ設定 (`PYTHONUNBUFFERED` など) は上書きできない。

**子プロセスの後始末 (#12)** — サーバーが強制終了 (`kill -9`、メモリ不足) されたときに、起動したノードが残らないようにする仕組みと、残ったときの片付け方。
- **直接の子**: Linux では起動時に `PR_SET_PDEATHSIG` (SIGTERM) を付ける (`process.spawn`、`preexec_fn`。`prctl` は fork の前に一度だけ探す。fork と prctl の間に親が死んでいたら自分に SIGTERM)。このシグナルはカーネルが「起動した **スレッド** の終了」で送るため、要求を処理するスレッド (anyio のスレッドは暇になると終わる)・自動起動のスレッド・自動再起動のタイマーから fork すると、元気な子が後で殺される。そこで子プロセスはすべて、サーバーが生きている間ずっと残る専用のスレッド (`roshanavi-spawn`) から起動する。
- **孫は対象外**: `ros2 run` / `ros2 launch` はノードを自分の子として起動するので、SIGKILL のあと `ros2 run` は止まってもノード本体 (孫) は残る (PR_SET_PDEATHSIG は子に受け継がれない)。そこで **記録** する: 起動したプロセスと子孫のすべてを、起動時刻・コマンドラインのハッシュ付きで `<data_dir>/run/procs-<サーバーの pid>.json` に書く (`proc_record.py`。1 秒ごとの見回りで、変わったときだけ原子的に書き換える。何も動いていなければファイルを消し、通常の終了でも消す。コンテナで前回と同じ pid になったときは前回のファイルを `procs-<pid>.prev-<時刻>.json` に退避)。
- **片付け**: 次に起動したとき、記録したサーバーがもう動いていないファイルのうち、**起動時刻とコマンドラインが今も一致するプロセス** (と、その後に生まれた子孫) を「残ったプロセス」とし、画面のバナー「前回の roshanavi が起動したノードが残っています (N 個)。止めますか?」(`GET /api/leftovers`、`POST /api/leftovers/stop`) で止める。同じ処理をコマンドでも行える: `ros2 run roshanavi cleanup [--data-dir DIR] [--dry-run]`。止め方はプロセスグループごとに SIGINT → 4 秒 → SIGTERM → 2 秒 → SIGKILL。記録に無いプロセス・一致しないプロセスには何もしない。
- **Docker**: コンテナの中で roshanavi が強制終了されたら、`docker restart <コンテナ>` がいちばん確実 (コンテナの中のすべてが止まる)。compose の `init: true` (tini) の下では、サーバーが死ぬとコンテナごと終わる。
- **残る制約**: (1) 記録は 1 秒ごとなので、起動した直後 (1 秒未満) に強制終了されると孫が記録に間に合わないことがある (直接の子は PR_SET_PDEATHSIG で止まる)。(2) 自分で `setsid` / 二重 fork して親から離れたプロセスは、記録の後に生まれたものは見つけられない (記録済みのプロセスの子孫としてたどれる範囲だけ)。(3) Linux 以外では PR_SET_PDEATHSIG が無い (記録と片付けは動く)。(4) ビルド (`colcon`) やシナリオのセットアップのプロセスは記録しない (直接の子は PR_SET_PDEATHSIG で止まる)。(5) 片付けは自動では行わない (利用者が確かめてから止める)。

**入力の検証 (`validate.py` / `command.py`)** — 値はすべて argv の 1 要素として渡すが、`ros2 run` / `ros2 launch` / rcl 自身が解釈する argv (`--prefix`, `--ros-args`, `--params-file`, `__node:=` …) を利用者の値に紛れ込ませないため、厳しく検査する。
- package / executable / launch file は正規表現 (先頭 `-` 不可、`..` 不可) に加え、**走査結果に存在すること**。
- パラメータ: 名前は `^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$`、値は制御文字不可・4096 文字まで。`-p name:=value` の 1 要素で渡す (bool は `true`/`false`)。
- リマップ: 両側とも rclpy の `validate_topic_name` を通り、`__` で始まらないこと (`__node` 等の特殊リマップは専用欄のみ)。ノード名・名前空間は `validate_node_name` / `validate_namespace`。
- `run` の追加引数: `--ros-args`, `--`, `-r`, `-p`, `--params-file`, `-e`, `--prefix`, `--ros-*`, `--log-*` などと、`__xxx:=` 形式を拒否する。`launch` の引数は `name:=value` のみ (名前は識別子)。launch には name / namespace / params / remaps を渡さない (スキーマで拒否)。
- パラメータファイル: `realpath` がワークスペースか data_dir の内側にある既存の `.yaml` であること (`..`、絶対パス、外向き symlink を拒否)。
- 生成される argv: `ros2 run <pkg> <exe> [args…] --ros-args -r __node:=<name> -r __ns:=<ns> -p k:=v … -r a:=b … --params-file <path>` / `ros2 launch <pkg> <file> k:=v …`。

**まだ source されていないパッケージ (`env.py`)** — サーバー起動後に初めてビルドしたパッケージは `AMENT_PREFIX_PATH` 等に入っていない。colcon が各パッケージに書く `share/<pkg>/package.dsv` (`prepend-non-duplicate;PYTHONPATH;…` などの宣言的な形式) を読んで子プロセスの環境に適用し、`AMENT_PREFIX_PATH` にもプレフィックスを足す。シェルスクリプトは実行しない。これで roshanavi から起動するノードはすぐ使えるが、利用者のターミナルでは `source install/setup.bash` のやり直しが必要 (UI に「未 source」バッジと説明を出す)。

**ビルドボタン (`build.py`)**
- `colcon build --packages-select <pkg> --symlink-install --event-handlers console_direct+` をワークスペース直下で実行する。同時に 1 つだけ (409 `build_running`)。対象は `src/` にある workspace パッケージのみ (`not_buildable`)。ログは id `_build`。
- 判定: 終了コード 0 でも「`ignoring unknown package`」「`Summary: 0 packages finished`」なら失敗とする (setup.py が壊れていると colcon はパッケージを認識できず 0 で終わるため)。失敗時は最初のエラー行 (`error:`, `CMake Error`, `…Error: `, `Traceback`, `Failed <<<` から最大 12 行) を `error_lines` に入れて UI に出す。
- 成功時は走査をやり直し、`restart_running` (既定 on) なら、そのパッケージの実行中ターゲットを再起動する (`restarted`)。未 source だったパッケージは `needs_resource:true` として UI で案内する。

**ノード ⇄ プロセスの対応づけ (`process_map.py`)** — リソース監視 ([resources.md#前提](resources.md#前提-ノードとプロセスの対応づけ)) でもそのまま使う (リソース監視では、Launcher の時刻による推定より argv の `__node:=` を優先する)。
- 純関数 `map_nodes(nodes, targets, first_seen, baseline, sticky)` と、状態を持つ `NodeProcessMapper` (初出時刻・ベースライン・確定済みの推定) に分ける。プロセスツリーは psutil (`process_tree(pid)`: ルート + 子孫を深さ順)。
- **exact**: ターゲットのプロセスツリーの argv に `__node:=<name>` (と `__ns:=`、`node:__node:=` 形式も) があれば一致。`ros2 run` のラッパーと実行ファイルの両方に付くため、最も深いプロセスを pid とする。launch_ros は `Node(name=…)` のときに付け、Launcher はノード名を入力したときに付ける。
- **launch サービス自身のノード**: `ros2 launch` は `launch_ros_<pid>` という名前のノードを 1 つ持つ。この `<pid>` がターゲットのプロセスツリーにいれば、そのプロセス (`ros2 launch` 本体) に対応づける (推定のまま)。launch がコンテナを起動していても、コンテナには対応づけない (#22 の実機確認で見つかった誤り。以前はツリーの末端 = コンテナの pid になっていた)。
- **heuristic**: ターゲットの (再) 起動から 20 秒以内に初めて現れ、他のターゲットが exact で持っていないノード。候補が複数あれば、実行ファイル名とノード名が一致するターゲット、なければ最後に起動したターゲット。一度決まった推定は、そのターゲットが生きている間は保持する。
- ベースライン: 自分のプロセスが 1 つも動いていない間に見えたノードは推定の対象外 (消えたらベースラインからも外す)。autostart はサーバー起動の 2 秒後に行い、既存ノードの発見を先に済ませる。roshanavi 自身のノードは対象外。
- 限界 (UI に「推定」と出す): composable node はコンテナプロセス単位 (コンテナ内のどのノードかは分からない。実機での確認は [composable container の扱い](#composable-container-の扱い-22))。別コンテナ (PID 名前空間が別) や別 PC のノードは対応づけない。起動直後に無関係のノードが同時に現れると推定を誤ることがある (ノード名を付ければ exact になる)。

**役割**: グラフの各ノードに `role` を付ける。`mine` (ターゲットの「開発中」フラグ)、`dependency` (それ以外のターゲット)、`dummy` (注入ジョブの仮想ノードと恒久ダミーノード)、`other`。対応づいたノードには `target_id` と `confidence` (`exact`/`heuristic`) も付ける。

## プロジェクトファイル (P3)

**`roshanavi.yaml`** (既定: ワークスペース直下、`--project PATH` で変更。Docker の lab は `/data/roshanavi.yaml`)
```yaml
version: 1
targets:
- id: talker               # [a-z0-9][a-z0-9_-]{0,63}、targets と dummies で一意
  kind: run                # run | launch
  package: demo_nodes_cpp
  executable: talker       # kind: launch なら launch_file
  name: my_talker          # 以下は任意 (run のみ: name / namespace / params / params_file / remaps)
  params: {rate: 2, use_sim_time: false}
  remaps: {chatter: /chat}
  args: []                 # run: 実行ファイルへの追加引数 / launch: ["name:=value", ...]
  role: mine               # mine | dependency
  autostart: true
  auto_restart: false
dummies:
- id: cam
  name: dummy_camera       # ROS ノード名
  topic: /camera/info
  type: std_msgs/msg/String
  kind: string             # 任意: UI で選んだデータの種類 (docs/design/nodes.md)。type に合わないと拒否
  mode: periodic           # once | periodic | stream | media (bag は不可。media は `media:` にオプション)
  payload: {data: "frame ${i}"}
  rate_hz: 5
  qos: {reliability: reliable, durability: volatile, depth: 10}
  autostart: true
transforms:               # 変換ノード (P5, docs/design/nodes.md)。id は targets / dummies と合わせて一意
- id: chatter_upper
  name: chatter_upper
  inputs: [{topic: /chatter, type: std_msgs/msg/String, alias: msg}]
  output: {topic: /chatter_upper, type: std_msgs/msg/String}
  mapping: {data: '${upper(msg.data)}'}
  autostart: true
functions:                # 関数ノード (docs/design/nodes.md)。id は targets / dummies / transforms と合わせて一意
- id: text_shout
  name: text_shout
  module: roshanavi_examples.logic   # ワークスペースの Python パッケージのモジュール
  function: shout
  call: on_message                   # on_message | periodic (rate_hz) | multi_input (trigger)
  inputs: [{topic: /chatter, kind: string}]          # kind = データの種類 (docs/design/nodes.md)、type は任意
  output: {topic: /shouted, kind: string}
classes:                  # クラスノード (docs/design/nodes.md)。id は他の種類と合わせて一意
- id: moving_average
  name: moving_average
  module: roshanavi_examples.stateful
  class_name: MovingAverage
  params: {window: 5}                # __init__ の引数の開始値 (ROS パラメータ)
  methods:                           # トピックにつなぐメソッド (関数ノードと同じ call / inputs / output(s))
  - method: process
    inputs: [{topic: /number, kind: float}]
    outputs: [{topic: /average, kind: float}]   # dict を返すなら各出力に key:
  actions: [reset]                   # 操作メソッド: /<node>/reset (std_msgs/Empty) とボタンで呼ぶ
watch_topics: [/chat]
```
- pydantic のスキーマで検証する。未知のキーは拒否し、エラーはパス付き (`targets.0.colour: extra fields not permitted`、YAML の構文エラーは行・列付き)。
- 保存は同じディレクトリの一時ファイル → fsync → `os.replace` (原子的)。キーはスキーマ順、空の値は省いて書く (差分が安定し、git で読みやすい)。
- サーバーは起動時に読み込み、作業中の内容 (起動リストとダミーの登録・変更) との差を `dirty` として返す。
- **自動保存 (P4.5a)**: Launcher facade 経由の追加・更新・削除・常駐化はすぐにファイルへ保存する (`Launcher.add/update/remove`、UI の保存ボタンと「未保存」表示は廃止。読み直しは設定メニュー)。保存の失敗は例外にせず `save_error` で返す。**読み込みに失敗したファイルは自動では上書きしない** (`autosave: false`。読み直しか明示的な保存 `POST /api/project/save` で解除)。
- **テンプレート (P4.5a)**: `--project-template PATH` (または `$ROSHANAVI_PROJECT_TEMPLATE`) を付けると、プロジェクトファイルが **無いときだけ** それをコピーしてから読み込む (`bootstrap_project`。`O_EXCL` で作成し既存は上書きしない。壊れたテンプレートはコピーせずログに出す)。パッケージが見つからないなど検証を通らないターゲットも、`invalid` 状態で一覧に残す (古いプロジェクトでも開ける)。
- `autostart: true` のターゲットとダミーはサーバー起動時に起動する (`--no-autostart` で無効)。
- **launch の引き取り** (`takeover:` と、ターゲットの `takeover: true`): [integration.md](integration.md)。`takeover: {package, launch_file, args: ["name:=value"], mode: node|whole}` は「どの launch ファイルを引き取ったか」だけを残す。

- **プロジェクトの切り替え (P5)**: ⚙ 設定メニューの「プロジェクトを切り替える」(`GET /api/projects`、`POST /api/projects/open {id}`、`launcher/catalog.py`)。候補は (1) サンプル: `--examples-dir` (既定は `--project-template` の 2 つ上、Docker では `/examples`) の `<name>/roshanavi.yaml`、(2) 保存済み: `<data_dir>/roshanavi.yaml` と `<data_dir>/projects/*.yaml`。サンプルを開くと初回だけ `<data_dir>/projects/<name>.yaml` にコピーし (`O_EXCL`、上書きしない)、以後はそのコピーを編集する (サンプル自体と元のプロジェクトファイルには書かない)。クライアントは一覧の `id` だけを送る (任意のパスは開けない)。切り替えは動いている起動リスト・入力ノード・変換ノードをすべて止め、新しいプロジェクトを読み込み、autostart のものを (待ち時間なしで) 起動する。切り替えに成功すると (読み込みエラーが無いとき) 開いた一覧の `id` を `<data_dir>/last_project.json` (`{"id": ...}`) に書き、**サーバーを再起動するとそのプロジェクトで始まる** (#9)。起動時は保存された `id` を現在の一覧と照らして検証し (一覧に無い・ファイルが消えた・JSON が壊れている・型が違うときは無視して警告だけ出す)、通らなければ `--project` のファイルで始める。保存に失敗しても切り替え自体は成功する (ログに警告)。

## ノードのパラメータと型の定義 (P4.5a)
**パラメータ (`params.py`)** — rclpy / rclcpp のノードが必ず持つ `<node>/list_parameters`・`describe_parameters`・`get_parameters`・`set_parameters` (rcl_interfaces) を、サーバー自身のノードから呼ぶ。
- クライアントは Reentrant なコールバックグループで作り、サービス名ごとに最大 24 個を LRU でキャッシュする。各呼び出しは `wait_for_service` と応答待ちのそれぞれに 2 秒のタイムアウト (応答しないノードでサーバーが止まらない)。失敗は 504 `param_service_unavailable` / `param_timeout`、502 `param_call_failed`。
- 一覧は名前順に最大 500 個。各項目に型・値・説明・`read_only`・`dynamic_typing`・範囲。
- 変更は値を型どおりに厳密に検査してから (`value_to_msg`: bool は true/false のみ、整数は int64 範囲、小数は有限、文字列は 4096 文字まで、配列は 1000 要素まで、バイトは 0..255)、describe で読み取り専用と型の一致 (dynamic_typing でない限り) を確かめて送る。ノードが拒否したら理由付きで `param_rejected`。
- **方針** (`server_nodes.py`): グラフに今いるノードだけを対象にする (404 `node_not_found`、任意のサービス名を作らせない)。ノード名・パラメータ名は正規表現で検査。roshanavi が起動していないノード (role `other`) は閲覧のみが既定で、変更には `allow_external: true` が必要 (UI は確認ダイアログの後に付ける。無ければ 403 `external_node_readonly`)。roshanavi 自身のノードは変更不可 (403 `self_node`)。mutating な PUT は既存のミドルウェア (Host / Content-Type) を通る。
**型の定義 (`interfaces.py`)** — `rosidl_runtime_py.get_interface_path` でインストール済みの `.msg/.srv/.action` を読み、入れ子の型をタブで字下げして展開する (`ros2 interface show` 相当。入れ子のコメントは省く。深さ 6・2000 行まで、循環はたどらない)。名前は `pkg/(msg|srv|action)/Name` のみ。

## デモ構成 (P4.5a)
- `examples/demo_project/roshanavi.yaml`: `talker` (demo_nodes_cpp, role mine, autostart, ノード名 talker) と `listener` (demo_nodes_cpp, role dependency, autostart)。compose の `lab` は `--project-template` でこれを指定し、`/data/roshanavi.yaml` が無いときだけコピーする。デモ開始時点で talker / listener を地図から停止・再起動でき、ログも見られる。(P5) サンプルノード 4 つの起動設定を autostart なしで足した (既存の `./data/roshanavi.yaml` は上書きしないので、すでにあるラボには入らない。プロジェクトの切り替えでサンプルを開くと入る)。
- (P5) `examples/perception_demo/roshanavi.yaml`: 入力ノード `dummy_camera` (`samples/blobs.mp4` → `/camera/image`、media / loop) → `image_filter` (`/camera/gray`, `/camera/edges`) → `blob_detector` (`/camera/detections`) → 変換ノード `blob_count` (`/camera/blob_count`, `std_msgs/Int32` = `len(msg.detections)`)、入力ノード `dummy_microphone` (`samples/tone.wav` → `/audio`, AudioDataStamped) → `audio_level` (`/audio/level_db`, `/audio/silence`)。すべて autostart。サンプルのファイルはリポジトリに入れず、サーバーの起動時に ffmpeg で `<data_dir>/samples/` に作る (`sample_media.py`、無いものだけ。`--no-sample-media` で無効): `blobs.mp4` (10 秒・320x240・15 fps。ffmpeg の `testsrc` を 25% に暗くし、その上を明るい円が 2 つ動く。`geq` で描く) と `tone.wav` (12 秒・16 kHz mono。440 Hz 2 秒 / 無音 2 秒の繰り返し)。一時ファイルに書いてから rename。
- (#40) `examples/busy_demo/roshanavi.yaml`: `busy_demo_driver` (`/busy_demo/in` に 100 Hz) と `executor_busy_demo` の 3 構成 (`multi_default` / `multi_off` / `single_default`、stats は `/busy_demo/<構成>/stats`)。すべて autostart なし (1 つずつ起動して比べる)。説明と実測は [nodes.md](nodes.md#executor_busy_demo--multithreadedexecutor-の空回りを体験する-40)。
- `demo` コンテナは「roshanavi が起動していないノード」の例: `external_talker` が `/external/chatter` に送り、`external_listener` が受ける。`/chatter` とは混ざらず、地図に「操作できるノード」と「見るだけのノード (停止は無効)」が並ぶ。
- (P4.5b) `demo` コンテナは外部の lifecycle ノード `lc_talker` (unconfigured で起動) も動かす ([launcher.md#lifecycle ノード](launcher.md#lifecycle-ノード-p45b))。launch の取り込みのデモ用に `roshanavi/demo_system.launch.py` を同梱する ([launcher.md#launch の分解取り込み](launcher.md#launch-の分解取り込み-p45b))。

## lifecycle ノード (P4.5b)
`lifecycle.py`。ROS の正規の仕組み (lifecycle_msgs の `<node>/get_state`・`get_available_transitions`・`change_state`) だけを使うので、**roshanavi が起動していないノードにも使える** (プロセスにシグナルは送らない)。
- 検出: 毎秒のグラフ収集で `get_service_names_and_types()` を 1 回呼び、`<node>/get_state` が `lifecycle_msgs/srv/GetState` 型のノードに `lifecycle: true` を付ける (`graph.lifecycle_nodes`)。
- 呼び出しはパラメータと共通の `service_call.ServiceCaller` (Reentrant グループ、LRU 24、`wait_for_service` と応答待ちそれぞれにタイムアウト。問い合わせ 2 秒、`change_state` は on_configure の処理を見込んで 10 秒)。新しいクライアントにも QoS イベントハンドラは登録しない ([map-and-traffic.md#ros_runtime](map-and-traffic.md#ros_runtime))。失敗は 504 `lifecycle_unavailable` / `lifecycle_timeout`、502 `lifecycle_call_failed`。
- 操作は configure / activate / deactivate / cleanup のみ (shutdown は元に戻せないので出さない)。いまの状態で使えない遷移は 409 `lifecycle_transition_unavailable`、ノードが拒否したら 409 `lifecycle_transition_failed`。目標 `goal` (`active` / `inactive`) は必要な遷移を順に行う (unconfigured → configure → activate)。一括操作 (ノード一覧) はこれを使う。
- 方針は [launcher.md#ノードのパラメータと型の定義](launcher.md#ノードのパラメータと型の定義-p45a) と同じ: グラフにいるノードだけ (404)、lifecycle でなければ 400 `not_lifecycle`、外部ノード (role other) は `allow_external: true` が必要 (UI は確認ダイアログの後に付ける。無ければ 403)、roshanavi 自身は 403。
- ノード一覧の状態表示は lifecycle ノードだけを並列 (最大 8) に 1 秒のタイムアウトで問い合わせ、1.5 秒キャッシュする。応答しないノードは「状態を取得できません」。
- デモ: `demo` コンテナで `ros2 run lifecycle lifecycle_talker` (ノード名 `lc_talker`、起動時は unconfigured。`ros-jazzy-lifecycle`)。

## launch の分解取り込み (P4.5b)
既存の launch ファイルの `Node` を 1 つずつの起動設定 (`kind: run`) として起動リストに取り込み、既存システムのノードを 1 つずつ ON/OFF できるようにする。`roshanavi/launch_import/`。

**信頼モデルとサンドボックス**
- Python の launch ファイルを評価すると、その Python コードが実行される。したがって **`ros2 launch` でその利用者が実行するのと同じ範囲のファイルだけ** を受け付ける: (a) 走査で見つかったパッケージの launch ファイル (ワークスペース / source 済みの ROS)、(b) realpath がワークスペースの内側にある `.py/.xml/.yaml` (`validate.contained_file`。`..`・絶対パス・外向き symlink は拒否)。**data_dir (アップロード・録画) の下のファイルは、どちらの経路でも評価しない** (403 `forbidden_path`)。
- 評価は **サーバーのプロセスでは行わない**。`python3 -m roshanavi.launch_import.child` を新しいセッション (プロセスグループ) で起動し、ランチャーと同じ環境 (未 source のワークスペースも overlay) で動かす。入力は stdin の JSON `{path, args}`、結果は元の stdout に 1 つの JSON (launch ファイル自身の print は stderr に回す)。20 秒で打ち切り (504 `launch_eval_timeout`)、終了後も含めてプロセスグループごと SIGKILL する (launch ファイルが裏で何かを起動していても残さない)。結果は 8 MB まで、pydantic で形を検査する。
- 評価中もプロセスは起動しない: 子プロセスは **LaunchContext を変えるだけの action** (下表の「評価する」) だけを visit し、`Node` は execute せずに設定を読み取る。それ以外は実行せず、理由付きで報告する。

**評価のしかた** (`walker.py`, `extract.py`): `AnyLaunchDescriptionSource(path).get_launch_description(context)` で読み (python / XML / YAML)、利用者が入れた引数を launch configuration に入れ、`current_launch_file_path/directory` を locals に置いてから再帰的にたどる。各要素の `condition` を先に評価し (偽ならその部分は「条件により起動されない」)、子要素は LaunchService と同じく locals を push / pop して visit する。必須の引数 (default なし) が足りなければ評価せず `missing_args` を返す (UI が入力欄を出す)。深さ 40・5000 要素で打ち切る。

| 要素 | 扱い |
|---|---|
| `Node`, `LifecycleNode` | **分解**: package / executable / name / namespace (PushRosNamespace と合成) / remappings (SetRemap と合成) / arguments / parameters を評価して 1 つの起動設定にする |
| `DeclareLaunchArgument`, `SetLaunchConfiguration`, `UnsetLaunchConfiguration`, `Push/Pop/ResetLaunchConfigurations`, `GroupAction` (scoped を含む), `PushRosNamespace`, `SetRemap`, `SetParameter`, `SetParametersFromFile`, `SetUseSimTime`, `SetROSLogDir` | 評価する (文脈を変えるだけ) |
| `IncludeLaunchDescription` | 評価して中をたどる。読めない (ファイルが無い・置換が解けない) ときは「分解できない部分」(`include_failed`) |
| `OpaqueFunction` | 評価して返り値をたどる (よく使われる `launch_setup` パターン)。**中の Python は実行される** ので警告を出す (`opaque_function_ran`)。子プロセス + タイムアウト + プロセスグループの kill の内側 |
| 環境変数の action (`SetEnvironmentVariable` など) | 評価する (後の置換に効く)。起動設定には取り込まない (警告) |
| `LogInfo` | 無視 |
| `ComposableNodeContainer`, `LoadComposableNodes` | **代替**: 分解しない (1 プロセスで動くので 1 つずつ止められない)。中の composable node を一覧に出す |
| `ExecuteProcess` / `ExecuteLocal` (Node 以外) | **代替**: 分解しない (ROS ノードではない) |
| `RegisterEventHandler`, `UnregisterEventHandler`, `TimerAction`, `RosTimer`, `EmitEvent` / `Shutdown`, `LifecycleTransition`, `OpaqueCoroutine` | **代替**: 分解しない (イベント・時間に依存する、または起動以外の動作) |
| 条件 (`if` / `unless`) | 評価する。偽 → 「条件により起動されない」、計算できない → 「分解できない部分」(`condition_failed`) |
| 知らない種類の action (利用者独自のものなど) | **代替**: 実行せずに残す (`unknown_action`) |

「代替」の部分があるときは、**「launch 全体として 1 つ取り込む」** (`kind: launch`、評価に使った引数を `name:=value` で付ける) を選べる。これはパッケージの launch ファイルのときだけ (ワークスペース内の任意のファイルは `ros2 launch <pkg> <file>` で指定できないため)。

**パラメータ** (`params_merge.py`, 純関数): launch_ros と同じ順 (SetParameter などのグローバル → ノード自身の dict / `Parameter` / パラメータファイルの順、後勝ち) に 1 つにまとめる。パラメータファイルは rcl の YAML の規則 (入れ子・絶対・相対のノードパス、`*` と `**` のワイルドカード。ワイルドカードの項目を先に、ノード名の項目を後に適用) で、そのノードに当たる値だけを取り出す。ファイルの中身は子プロセスが読んで (1 MB まで) JSON で返す (サーバーは launch ファイルが指すパスを開かない)。ノード名が無い Node は `/**` の項目だけ (警告)。まとめた値のうち、名前が識別子で値が bool / 整数 / 小数 / 4096 文字までの文字列のものは `params` (UI で編集できる)、それ以外 (配列・入れ子) は取り込み時に `<data_dir>/imported_params/<id>.yaml` (`/**: ros__parameters:`) に書き、`params_file` で渡す。キーは重ならないので `-p` とファイルの順序に依存しない。

**プレビューと取り込み**: プレビューの段階で各案をランチャーと同じ検査 (`manager.validate`: パッケージ・実行ファイルの存在、名前、引数の規則) にかけ、通らないものは理由付きで「取り込めない」。同じ package / executable / name / namespace の起動設定がすでにあれば「重複」として既定で選ばない。案はサーバーに 30 分 (最大 16 個) 保存し、`preview_id` で取り込む (クライアントからパラメータファイルの中身を受け取らない)。ID はノード名 (なければ実行ファイル名) から重複を避けて作る。取り込んだものは停止状態・autostart なしで起動リストに入り、自動保存される。`TargetSpec.imported_from` (情報用) に取り込み元 (`pkg/file` かワークスペースからの相対パス) を残す。
- **launch ファイルごと引き取る** (`--launch`): この分解を使って起動まで自動で行い、launch ファイルの変更を検出して取り込み直す。[integration.md](integration.md)。分解の結果には、`respawn` / `respawn_delay` / `on_exit=Shutdown` (required) / ノードに届く環境変数 (`env`) / 読み込んだ launch ファイルの一覧 (`files`) / 条件を評価したか (`conditions_evaluated`) も入る。ノードごとの取り込みでは `respawn` を `auto_restart` に、環境変数を `env` に引き継ぐ (`carried` / `lost`)。
- デモ: `roshanavi/demo_system.launch.py` (talker / listener を名前空間・リマップ・パラメータ付きで起動し、最後に「分解できない部分」の例として ExecuteProcess)。

## ノード一覧の集約 (P4.5b)
- **ノード一覧** (`node_list.py`, 純関数): グラフのノード (注入ジョブの仮想ノードは除く) と、グラフにノードが無い起動リスト・常駐ダミーの和集合。行に役割・状態 (起動リストの状態、外部は「実行中 (外部)」)・起動元 (package / executable / launch file / 取り込み元)・PID・対応づけ・lifecycle の状態、`control` (`target` / `lifecycle` / `none`) と `reason` (`external` / `invalid`) を付ける。kind launch の起動設定と、1 プロセスに 2 つ以上のノードが対応づいた起動設定 (composable container など) は `groups` になり、行はグループごとに並ぶ (止めると一緒に止まる単位)。
- **削除と「元に戻す」** (`launcher/trash.py`, `POST /api/registry/delete` / `undo`): ノード一覧で選んだ roshanavi の登録 (起動リスト・取り込んだもの・入力・変換・関数・クラスノード) をまとめて外す。知らない ID が 1 つでもあれば何も変えない (404)。外すときに動いているものは止め、仕様 (spec) と「動いていたか」を 15 秒 (UI は 10 秒) まで最大 8 回分覚えておき、`undo` で登録し直して (検証を通らなくなっていても `invalid` で残す) 動いていたものを起動する。ソースコード・パッケージ・取り込んだパラメータファイル・録画には触らない。

## composable container の扱い (#22)
1 つのプロセス (`component_container`) の中に複数のノードが入る構成を、**実物のコンテナ**で確かめた。使ったのは中継パイプライン ([nodes.md#中継パイプライン](nodes.md#中継パイプライン-source--relay--sink51)) の `mode:=container` (`ComposableNodeContainer` に 12〜20 ノード) を `ros2 launch` で起動する `kind: launch` の起動設定。テストは `test_container_ros.py`、E2E は `web/e2e/pipeline.spec.ts`。

| 見る点 | 実機での結果 |
|---|---|
| ノード ⇄ プロセス | コンテナの中のノードはすべて同じ起動設定 (`target_id`) に、**推定 (`heuristic`) で同じ pid (コンテナのプロセス)** に対応づく。コンテナ自身のノード (`/pipeline_container`) は `__node:=` を持つので `exact`。1 ノードずつの pid にはならない。同じパイプラインを `mode:=process` (1 ノード 1 プロセス) で動かした場合は、全ノードが `exact` で別々の pid (`test_pipeline_modes_ros.py`) |
| ノード一覧 | `kind: launch` の起動設定なので 1 つのグループ (`kind: launch`、ラベルは launch ファイル名) にまとまり、全ノードの `control` は `target` (地図・一覧から停止・再起動できる) |
| 停止 | どのノードを選んでも操作の対象は同じ起動設定。確認ダイアログに出すノードの一覧 (`GET /api/targets` の `nodes`) には、コンテナの全ノード (パイプライン 12 + コンテナ + launch サービスのノード) が入る。停止すると全ノードが同時に地図から消え、`ros2 launch` もコンテナも終了する。起動し直すと全部が戻る |
| リソース | プロセス単位だけ。`component_container` の行が 1 つ (`label` = 起動設定、`nodes` = 全ノード)、各ノードの値は**同じ値** (`scope: process`、`shared` に同居するノード) |
| launch の取り込み | `ComposableNodeContainer` は分解できず「分解できない部分」(`composable_container`) として、**中のノード名とプラグインを一覧に出す**。パッケージの launch ファイルなので「launch 全体として取り込む」が選べて、`kind: launch` (引数 `mode:=container` 付き) になる。同じ launch を `mode:=process` で読むと全ノードが 1 つずつ取り込める |
| 詳細計測モード | **ノードごとに測れる**。同じコンテナの中のノードごとに受信 Hz・処理 Hz・コールバック時間が別々に出る (送信元の速さが違う 3 本の列で 20 / 10 / 5 Hz が別々に出ることを確認)。rclpy の `launch_ros_<pid>` だけが「受信数のみ」 |
| intra-process 通信 (`use_intra_process_comms`) | 地図・トラフィックには出る (roshanavi の計測ノードは別プロセスなので DDS 経由でも受ける)。**詳細計測モードは正しく測れない (未修正の不具合)**: コンテナ内のノードのコールバックが購読に対応づかず、処理数が 0 になって「処理が追いつかない」と誤って出る (`intra` の印も付かない)。`test_container_ros.py` に `xfail(strict)` で記録してあり、直したら外す |
| 速さの限界 | 1 本のスレッドで回る `component_container` では、中のノードの処理時間の合計がそのコンテナの上限を決める ([measurement.md#規模と負荷の限界](measurement.md#規模と負荷の限界-51)) |

直した不具合: `ros2 launch` 自身のノード `launch_ros_<pid>` が「コンテナのノード」として数えられ、コンテナのプロセスに対応づけられていた (確認ダイアログとリソースの「n ノードで共有」に混ざる)。上記「launch サービス自身のノード」の規則で `ros2 launch` のプロセスに対応づけるようにした。

まだ確かめていないこと: コンテナを roshanavi の外で起動して `ros2 component load` で後からノードを足す構成 (ノードは roshanavi の起動したものではなく、外部扱いになるはず)、複数のコンテナを別々の起動設定にした場合の組み合わせ、`LoadComposableNodes` で既存のコンテナに足す launch。
