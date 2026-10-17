# roshanavi — 入力とメディア

注入ジョブ、式 (`${...}`) のペイロード、メディアファイルの注入、ブラウザ入力、録画、ビューア、送信のペース制御。常駐ノードとしての入力は [nodes.md](nodes.md)、画面は [ui.md](ui.md)。

## msgutil
- `resolve_type("std_msgs/msg/String")` → クラス (`rosidl_runtime_py.utilities.get_message`)。
- `template(type)` → 既定値インスタンスを `message_to_ordereddict` した dict (UI で YAML 編集の初期値)。
- `build(type, dict)` → `set_message_fields` でメッセージ生成。失敗時はフィールドパス付きの明確なエラー。
- `to_display(msg)` → dict 化、長い配列は先頭 N 要素 + 件数に切り詰め (画像・点群対策)。

## expr (安全な式評価)
- Web 入力を `eval` しない。`ast.parse(mode="eval")` → 許可ノードのみ再帰評価: 数値/文字列リテラル, 四則・剰余・べき, 比較, 単項 ±, 三項演算子, 許可関数呼び出し。
- 変数: `i` (送信回数, 0 始まり), `t` (ジョブ開始からの秒), `now` (epoch 秒)。
- 関数: `sin cos tan abs min max round floor ceil sqrt random uniform(a,b) randint(a,b) str int float`、定数 `pi e`。
- 属性アクセス・添字・内包表記・lambda は拒否。べき指数や文字列長に上限 (DoS 防止)。
- **入力メッセージのフィールド参照 (P5, 変換ノード用)**: `Expression(source, message_names=("msg", ...))` で作った式だけが、その名前の入力メッセージのフィールドを `msg.linear.x`・`msg.data[0]` の形で読める。
  - 静的な検査: `ast.Attribute` / `ast.Subscript` は、連なりの根元が `message_names` の名前 (`ast.Name`) のときだけ許可。フィールド名は `[A-Za-z][A-Za-z0-9_]*` (`_` 始まり = `__class__` などは拒否)。添字は整数の式だけ (スライス・タプル・文字列の定数は拒否)。名前は `[a-z][a-z0-9_]{0,31}` で、変数・定数・関数名とは重ならない。`message_names` が空 (注入のペイロード) なら従来どおり属性・添字はすべて拒否。
  - 実行時: 受信したメッセージは `message_to_ordereddict` で素のデータ (dict / list / スカラー) にしてから `MsgView` (`msg_view.py`) で包む。`.name` は `view.field(name)` = 辞書の検索、`[i]` は `view.item(i)` = 整数添字 (bool は不可、|i| ≤ 1,000,000、範囲外は `index_range`)。`getattr` は一切使わないので、Python のオブジェクトの属性には届かない。土台が `MsgView` でなければ `not_struct`。ビューは変更不可・反復不可・ハッシュ不可。ビュー同士・数値との四則演算は `whole_message` で拒否。
  - 文字列化 (`str(msg)`・埋め込み) は JSON で、長さの上限 (10,000 文字) を超えると拒否。テンプレートの `${...}` 全体がビューなら素の dict / list に戻して値にする (例: `header: ${msg.header}`)。
  - 追加した関数: `upper lower strip replace` (文字列。`replace` は結果の長さを先に計算して上限を超えるなら拒否)、`len` (文字列・配列)、`clamp(x, lo, hi)`、`now_stamp()` (いまの時刻の `{sec, nanosec}`)。`int()` / `float()` はビューを拒否。
  - エラーには `code` (`syntax` / `unknown_name` / `unknown_function` / `not_allowed` / `bad_field` / `field_base` / `no_field` / `not_struct` / `not_array` / `bad_index` / `index_range` / `whole_message` / `not_string` / `not_number` / `bad_argument` / `too_long` / `too_large` / `too_deep` / `eval_failed` / `no_message`) と `params` を付け、UI が平易な日本語にする (`transform/previewText.ts`)。
- メッセージ dict 中の文字列 `"${...}"` を式として評価。全体が `${...}` 一つなら評価結果の型をそのまま、文字列中に埋め込みなら文字列置換。

## injector
- ジョブモデル: `{id, topic, type, qos, mode, payload, rate_hz?, count?, source?}`。`POST /api/inject` で開始、`DELETE /api/inject/{id}` で停止、`GET /api/inject` で一覧 (送信数・状態・エラー)。
- mode:
  - `once`: 1 回送信して完了。
  - `periodic`: `rate_hz` で送信、`count` 指定で自動終了。payload の `${}` は毎回評価 (= 式モードも兼ねる)。
  - `stream`: JSONL (1 行 1 メッセージ dict) または CSV (ヘッダ = フィールドパス, `a.b.c` 形式) を `rate_hz` で順送り、`loop` 可。
  - `bag`: `ros2 bag play <path> [--rate r] [--loop] [--topics ...]` をサブプロセス起動、停止で SIGINT。
  - `media`: 画像・動画・音声ファイルを型に合わせて変換して送る ([input-and-media.md#メディアファイル注入](input-and-media.md#メディアファイル注入)、[input-and-media.md#メディア](input-and-media.md#メディア-アダプタファイルソースブラウザ入力ビューア-p4))。
- **一時停止 (P4.5a)**: `POST /api/inject/{id}/pause|resume`。periodic / stream / media のジョブは送信だけを飛ばし、タイマー・ペーサーは動かし続ける (再開してもまとめ送りしない。media は読んだフレームを捨てる)。once・bag・capture は `not_pausable`、終了済みは 409 `not_running`。ジョブに `paused`, `pausable` を出す。
  - (`capture`: ブラウザのマイク・カメラ。`/ws/capture` で始まり、ジョブ一覧と地図には同じ形で出る。[input-and-media.md#メディア](input-and-media.md#メディア-アダプタファイルソースブラウザ入力ビューア-p4))
- ファイルパス (stream / bag) は設定された `data_dir` (既定 `/data`) 配下のみ許可 (realpath で検査、パストラバーサル防止)。
- publisher はジョブごとに作成、終了時に破棄。

## メディアファイル注入
`data_dir` 内のファイル (またはフォルダ) を、送信先トピックの型に合わせて変換して送る (`mode: "media"`)。デコードは ffmpeg (サブプロセス、パイプで逐次。ファイル全体をメモリに読まない)。詳細は [input-and-media.md#メディア](input-and-media.md#メディア-アダプタファイルソースブラウザ入力ビューア-p4)。

| 入力 | 送信形式 | 備考 |
|---|---|---|
| PNG/JPG/BMP/WebP (単体・フォルダ) | `sensor_msgs/Image` (rgb8/bgr8/mono8) / `CompressedImage` (jpeg/png) | フォルダは名前順のスライドショー。`rate_hz` (既定 1 Hz) で切り替え。単体の画像は止めるまで (または `count` 回) 繰り返す |
| MP4/MOV/MKV/WebM/AVI | フレームに分解して `Image` / `CompressedImage` | 既定は動画の fps。`rate_hz` を指定すると ffmpeg の fps フィルタでその fps に間引き / 補間 (内容は実時間のまま)。開始・終了 (秒)、リサイズ (片方だけなら縦横比を保つ)、loop |
| WAV/MP3/FLAC/OGG/M4A | PCM S16LE に変換し、チャンクごとに送る | サンプルレート (既定 16000)・チャンネル数 (既定 1)・チャンク長 (既定 1024 サンプル) を送信先に合わせて変換。実時間ペース (先読み + プレバッファ、遅れの方針 `late_policy`、[input-and-media.md#メディア](input-and-media.md#メディア-アダプタファイルソースブラウザ入力ビューア-p4))。揺らぎ・欠落の注入可 |

- **型**: 指定がなければ、送信先トピックの既存の **subscriber の型** (受け手が期待する型)、なければ publisher の型を使う。誰も使っていなければ、対応型の一覧を示して選んでもらう (`media_type_required`)。対応外の型は、bag 再生 / 録画 ([input-and-media.md#録画](input-and-media.md#録画-p4)) を案内するエラー (`media_type_unsupported`)。
- **音声の型**: `audio_common_msgs` (AudioData / AudioDataStamped + AudioInfo) が入っていればそれも選べる。無い環境ではその型が一覧から消えるだけで、`std_msgs/Int16MultiArray` など配列型は使える。
- 恒久ダミーノード ([nodes.md#恒久ダミーノード](nodes.md#恒久ダミーノード-p3)) にもできる (`mode: media` + `media:` オプション。別プロセスの dummy ノードが同じ変換をする)。

## echo
- `WS /ws/echo/{topic}` 接続中のみデシリアライズ購読し、最大 10 Hz に間引いて `to_display` を送る。接続切断で購読解除。

## メディア: アダプタ・ファイルソース・ブラウザ入力・ビューア (P4)

`roshanavi/media/`。対象ユーザーが「自分の声やカメラ、手元の動画を、ノードが期待する型でそのまま流す」ための層。

**アダプタ (`media/adapters/`)** — メディア (画像フレーム / PCM チャンク) ⇄ メッセージの変換を **型ごと** に持つ。レジストリは型名がキー。
| 型 | 変換 | 付随メッセージ |
|---|---|---|
| `sensor_msgs/msg/Image` | rgb8 / bgr8 / mono8 (mono は BT.601)。`step = width × ch` | `CameraInfo` |
| `sensor_msgs/msg/CompressedImage` | JPEG / PNG をそのまま格納 (`format: "jpeg"/"png"`) | `CameraInfo` |
| `audio_common_msgs/msg/AudioData` / `AudioDataStamped` | PCM S16LE (インターリーブ) を `data` に | `AudioInfo` |
| `std_msgs/msg/Int16MultiArray` / `UInt8MultiArray` / `Float32MultiArray` | int16 / S16LE バイト列 / ±1.0 の float。`layout.dim = [samples, channels]` | なし |
- **CameraInfo**: 画像と同じ stamp・frame_id で毎フレーム送る。既定の送り先は同じ名前空間の `camera_info` (`/cam/image_raw` → `/cam/camera_info`、image_transport の慣習)。値は既定 (水平画角約 60° のピンホール、歪みなし) か、`camera_calibration` 形式の YAML (ワークスペースか data_dir の中のみ)。フレームの大きさが違えば内部パラメータを比例で直す。
- **AudioInfo の名前 (決定)**: Jazzy の `audio_common` 0.4.x の `audio_capture` は、ノードの名前空間に `audio` (AudioData)・`audio_stamped`・`audio_info` を並べて出す (launch の既定は ns `audio` → `/audio/audio`, `/audio/audio_info`)。これに合わせ、既定は送信先と **同じ名前空間の `audio_info`** (`<topic>_info` ではない)。`audio_info_topic` で変更できる。内容は `channels, sample_rate, sample_format: S16LE, bitrate = rate × ch × 16, coding_format: wave`。QoS は RELIABLE / TRANSIENT_LOCAL / depth 1 で開始時に送り、VOLATILE の購読者のために 1 秒ごとにも送り直す。
- **プラグイン**: entry point グループ `roshanavi.adapters`。`MediaAdapter` のサブクラス / インスタンス / それを返す callable を登録できる (`setup.py` に `entry_points={'roshanavi.adapters': ['my = my_pkg.adapter:MyAdapter']}`)。読み込みに失敗したプラグインはログに出して無視する。型のパッケージが無いアダプタ (例: audio_common_msgs 未インストール) は登録されない。
- **型の判定 (`options.detect_type`)**: subscriber の型 → publisher の型の順。同じ側に複数の型があれば `media_type_ambiguous`。

**ffmpeg の安全対策 (`media/ffmpeg.py`)** — 細工したファイル (HLS / concat のプレイリスト等) で URL 取得や data_dir 外の読み出しをさせない。
- パスは `realpath` で data_dir の内側に限定 (`..`・絶対パス・外向き symlink を拒否) し、通常ファイルであること。フォルダは直下の画像だけを 1 つずつ同じ検査にかける。
- **拡張子から demuxer を決めて `-f` で強制し、`-format_whitelist` にもその 1 つだけを入れる** (例: `.mp4` → `mov`)。hls / concat / dash / image2 の連番などの間接参照する demuxer は選ばれない。`.mp4` に名前を変えたプレイリストは mov として読めずに失敗する。mov の外部参照 (`enable_drefs`) は既定で無効のまま。
- `-protocol_whitelist file,pipe` と、入力を `file:<絶対パス>` で渡すことで、http などのプロトコルや `concat:` 等の接頭辞を使わせない。
- 先頭を見て `#EXTM3U` / `ffconcat` / `<MPD` / `#EXTINF` があれば ffmpeg に渡す前に平易なエラーにする。
- argv のリストのみ (シェルなし)、`-nostdin`。プロセスは新しいセッションで起動し、停止時は SIGTERM → 2 秒 → SIGKILL のあと必ず `wait` する (ゾンビを残さない)。ジョブの停止でソースを閉じ、読み取り待ちのスレッドも抜ける。

**ファイルソース (`media/sources.py`)** と **送信 (`media/job.py`)**
- 画像は ffmpeg で 1 枚ずつ rawvideo / JPEG / PNG に変換 (目的の形式・大きさのファイルはそのまま)。スライドショーは 256 MB までキャッシュ。動画は `-vf fps=…,scale=…` で rawvideo (固定長) か image2pipe (JPEG は EOI、PNG は IEND で区切る) を読む。音声は `-f s16le -ar -ac` でチャンク単位に読み、最後の端数は無音で埋める。
- **スレッドは 2 本** (ジョブごと)。**リーダー** (`media/prefetch.py`) が ffmpeg からデコードして先読みし、件数と容量 (96 MB) に上限のあるキューに積む。**ペーサー** (`media/job.py` のジョブスレッド) は「キューから取る → stamp → publish」だけを行い、デコード・パイプ読み・ループ時の ffmpeg 再起動を待たない。キューの深さは `prebuffer` + 4 件以上 (`max(prebuffer + 4, 2 × prebuffer)`)。
- **プレバッファ**: 送信は、キューに `prebuffer_ms` 分 (既定 300 ms、`ceil(prebuffer_ms / 周期)` 件、最低 1 件) たまってから始める。ファイルの終わりかキューが満杯なら、その時点で始める。3 秒たまらなくても始める (ログに残す)。購読者のマッチ待ち (下記) とは並行して進む。
- ペーサーは **`t0 + k × 周期`** の絶対時刻 (`time.monotonic`) まで `Event.wait` で眠る (rclpy タイマーではない。スピンやビジーウェイトはしない。起床の誤差は実測で 0.1〜0.7 ms)。周期は動画 `1/fps`、音声 `チャンク長 / サンプルレート`、画像 `1/rate_hz`。t0 はプレバッファが埋まった時点で決める。揺らぎ (`jitter_ms`、一様分布) は予定時刻に足すだけで累積しない。欠落 (`drop_ratio`) は読んだうえで送らない (`dropped` に数える)。stamp は送信時刻。ロジックは `media/pacing.py` (時計と sleep を差し替えられる純粋な `Pacer` / `run_paced`)。
- **遅れた時の方針 `late_policy`** (ペーサーが予定より **1 周期を超えて** 遅れて起きた時、またはリーダーが追いつけずキューが空になった時):
  - `shift` (既定): その時刻で t0 を取り直す。遅れた 1 個はすぐ送り、以降は通常の間隔で続く。まとめ送りは起きない。
  - `catch_up`: t0 を変えず、追いつくまで続けて送る (まとめ送り。全体の長さは変わらない)。
  - `drop`: 遅れた分は送らず捨てる (`late_skipped`)。以降は元の時刻割りに戻る。
  - ジョブの状態に `late_events` (1 周期を超えた遅れの回数)、`max_lateness_ms` (最大の遅れ。1 周期以下も含む)、`late_policy`、`late_skipped` を出す。UI のジョブ一覧には遅れがあったときだけ「送信の遅れ N 回 (最大 M ms)」と出る。恒久ダミーノードも同じジョブ (同じコード) を使うので、同じオプション (`media.prebuffer_ms`, `media.late_policy`) と状態になる。
- **GIL 競合の根本原因 (`ros_runtime.py`)**: 以前は音声が 150 ms 止まり、直後にまとめ送りされた。原因は ffmpeg でも変換・publish・ログでもなく、roshanavi の Executor スレッドが **ビジーループ**していたこと。Jazzy の rclpy は購読ごとに既定の QoS イベントハンドラ (incompatible QoS) を登録し、トラフィック監視の購読と注入の publisher が同じノードで同じトピックを使うと、`wait()` が即座に戻るのに取れるものがなく、Executor が Python でウェイトセットを作り直し続ける (1.5 秒で 3000〜5000 回)。この間 GIL を取り続けるので、他の Python スレッド (ペーサーを含む) の起床が 50〜250 ms 遅れた。`RosRuntime.create_subscription` は既定のイベントハンドラを登録しない (`NO_SUBSCRIPTION_EVENTS`) ことで解消した。プレバッファ・リーダー分離・`late_policy` は、この種の遅れ (ffmpeg の起動、CPU 競合、他スレッドの停止) の影響を送信に出さないための備え。
- 最初の送信の前に既存の購読者とのマッチを最大 1 秒待つ (once と同じ)。publish はジョブのロックの中で状態を確かめてから行い、publisher の破棄は状態を変えた後 (既存ジョブと同じ規則)。

**ブラウザ入力 (`media/capture.py`, `/ws/capture`)**
- 最初のテキストメッセージ: `{kind: "audio"|"camera", topic, type?, frame_id, sample_rate, channels, chunk_samples, audio_info, fps, encoding, camera_info, reliability}` (pydantic、未知のキーは拒否)。型は省略すると [input-and-media.md#メディアファイル注入](input-and-media.md#メディアファイル注入) と同じ規則で判定。応答 `{event: "ready", job_id, type, companions[]}`、以後 1 秒ごとに `{event: "stats", sent, dropped}`。エラーは `{error: {code, message}}` を送ってから close 4400。
- 以降のバイナリフレーム: マイクは PCM int16 (ブラウザの AudioContext を目的のサンプルレートで作り、AudioWorklet で 20 ms ごとに送る)、サーバーが `chunk_samples` に詰め直して送る。カメラは JPEG (getUserMedia → canvas → `toBlob('image/jpeg')`、選んだ fps・解像度)。`CompressedImage` ならそのまま、`Image` なら Pillow でデコードして送る。
- 上限: 音声 1 フレーム 256 KB・実時間の 1.5 倍 (+1 秒) を超える量は捨てる。カメラ 1 フレーム 4 MB・30 fps (超えた分は間引いて `dropped`)。**1 トピックに 1 つ** (`capture_busy`, 409)。ジョブ数の上限は注入と共通。
- ブラウザ入力は注入ジョブ (`mode: capture`) として登録するので、ジョブ一覧・地図の仮想ダミーノード・停止ボタン・録画のプリセットにそのまま出る。WS が切れたら (タブを閉じた等) ジョブを止め、publisher を破棄する。
- 既存のセキュリティ middleware (Host / Origin) を通る。ブラウザのメディア取得はセキュアコンテキストが必要で、`localhost` はそれに当たる。
- **遅れ (UI に明記)**: stamp はサーバーの受信時刻。ブラウザの取得・JPEG 変換・WebSocket の分、実機より数十 ms 遅れる。カメラの解像度・fps はブラウザと Web カメラ次第 (目安 640×480・30 fps)。

**ビューア (`media/viewer.py`, `/ws/view/{topic}`)**
- 開いている間だけ購読する (参照カウントで共有、最大 16 トピック)。重い型の traffic 統計は既定で非監視のまま ([map-and-traffic.md#traffic](map-and-traffic.md#traffic))。
- 画像: 最新の 1 枚だけ保持し、**最大 10 fps**・**幅 640 px 以下**の JPEG にして送る (Pillow。幅 640 以下の JPEG はそのまま)。Image は rgb8/bgr8/mono8/rgba8/bgra8/8UC1/8UC3/mono16/16UC1 に対応 (16 bit は最大値で正規化)。
- 音声: 受信したチャンクを (最大 256 個) ためて 0.1 秒ごとにモノラルの PCM で送る。audio_common の型は兄弟の `audio_info` からサンプルレート・チャンネル数を読み、配列型は UI で指定する (既定 16000)。`coding_format` が wave 以外 (mp3 など) は表示できない旨のエラー。

## 録画 (P4)
`media/recorder.py`, `media/diskguard.py`。「自分の声やカメラ映像で 1 回録る → 以後は毎回同じ入力で再現テスト」、テスト対象ノードの出力の保存に使う。
- `ros2 bag record -s mcap -o data_dir/recordings/<YYYYmmdd-HHMMSS>_<名前>/ --topics …` をサブプロセスで起動 (同時に 1 つ、`recording_active` 409)。名前は英数字と `_` `-` (40 文字まで)、トピックは検証済みの名前だけを argv の要素として渡す。
- 停止はプロセスグループに **SIGINT** → 10 秒 → SIGTERM → 5 秒 → SIGKILL。SIGINT で rosbag2 がキャッシュを書き出し `metadata.yaml` を書く。監視スレッドがプロセスの終了と空き容量を 1 秒ごとに見る。サーバー終了時も SIGINT で確定させる。
- **空き容量**: data_dir のボリュームで、空きが 1 GiB 未満 **または** 5 % 未満で警告 (UI に表示)、256 MiB 未満または 1 % 未満で自動停止 (`stop_reason: disk_full`)。開始時点で停止の基準を下回っていれば開始しない (`disk_full`, 507)。基準は `--record-warn-free-mb / --record-warn-free-pct / --record-stop-free-mb / --record-stop-free-pct` で変更できる。空き容量の取得は差し替え可能 (テストで注入)。
- 録画中のサイズは rosbag2 のキャッシュ (既定 100 MiB) のため遅れて増える。UI は経過時間を主に出す。
- 一覧: `recordings/` 直下のディレクトリを `metadata.yaml` から要約 (長さ・メッセージ数・トピックごとの件数・サイズ)。確定していないものは「未完了」。`/api/files` には bag として出るので、注入の bag モードでそのまま再生できる。
- 削除: 名前が録画ディレクトリの形式に合い、`realpath` の親が recordings ディレクトリそのものであること (symlink・`..` を拒否)。録画中のものは消せない。UI は確認ダイアログを出す。
