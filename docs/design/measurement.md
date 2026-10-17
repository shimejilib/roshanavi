# roshanavi — 計測

C++ 計測ノード (`roshanavi_probe`)、詳細計測モード (トレース計測)、それぞれのベンチマーク。統計の意味とレートの規則は [map-and-traffic.md](map-and-traffic.md)。

## C++ 計測ノード (`roshanavi_probe`, P4.6)
トラフィックを **「ノード × トピック × 向き (送信 / 受信)」** の単位で出す。地図の線 1 本ごとに、その線自身の値を付ける。

| 向き | 方式 | 精度 | 既定 |
|---|---|---|---|
| 送信 (ノード → トピック) | C++ 計測ノード (この節) | 実測 (`basis: measured`) | 有効 |
| 受信 (トピック → ノード) | 理論値: QoS が互換な送信元の実測値の合計 ([map-and-traffic.md#送受信ごとのトラフィック・遅いトピック](map-and-traffic.md#送受信ごとのトラフィック遅いトピック-p45b)) | 推定 (BEST_EFFORT の取りこぼしは不明) | 有効 |
| 受信・処理 (トピック → ノード) | トレース計測 ([measurement.md#詳細計測モード](measurement.md#詳細計測モード-トレース計測-p47)) | 実測 | 詳細計測モードの間だけ (既定はオフ) |

**パッケージ**
- `roshanavi_msgs` (ament_cmake, rosidl): `ProbeTopic {topic, type, best_effort}`、`ProbeConfig {instance, windows_sec[], topics[]}`、`EndpointStats {publisher_gid (uint8[16]), resolved, node_name, node_namespace, count, bytes, hz, bps, dropped, rate_note, stale, first/last_source_stamp}`、`TopicStats` (トピック × 計算期間 1 つ分。`stats.py` の全項目 + `status` / `error` / `endpoints[]`)、`ProbeStats {header, instance, rmw_implementation, cpu_percent, rss_bytes, topics[]}`。null は浮動小数点が NaN、整数が -1。Jazzy の `RMW_GID_STORAGE_SIZE` は 16。
- `roshanavi_probe` (ament_cmake, C++17, rclcpp): 実行ファイル `probe`。統計の計算は ROS に依存しない `stats.hpp/.cpp` (gtest で検証)。

**購読と記録**
- トピックごとに `create_generic_subscription(topic, type, qos, cb, options)`。コールバックは `void(std::shared_ptr<const rclcpp::SerializedMessage>, const rclcpp::MessageInfo &)` (Jazzy の `any_subscription_callback.hpp` の `SharedConstPtrSerializedMessageWithInfoCallback`)。`MessageInfo::get_rmw_message_info()` から `publisher_gid`・`source_timestamp`・`received_timestamp`・`publication_sequence_number` (`RMW_MESSAGE_INFO_SEQUENCE_NUMBER_UNSUPPORTED` は 0 = 非対応として扱う)、`SerializedMessage::size()` を取り、トピックのリングバッファ (最長の計算期間 10 秒分、最大 20000 件) に積む。型のライブラリ (`rosidl_typesupport_cpp`) が無い型は `status: unsupported` (Python の型が無くても C++ の型があれば測れる)。
- QoS は Python の経路と同じ (BEST_EFFORT の送信者が 1 つでもいれば BEST_EFFORT、VOLATILE、depth 10)。**QoS イベントのコールバックは購読・設定・統計のどれにも登録しない** (`use_default_callbacks = false`。[map-and-traffic.md#ros_runtime](map-and-traffic.md#ros_runtime) の rclpy の busy loop と同じ理由で、不要な起床をなくす)。
- 実行は `SingleThreadedExecutor` 1 本 (受信・設定・1 秒タイマーが同じスレッドなのでロック不要。購読のコールバックとタイマーは `shared_ptr<TopicState>` を共有し、状態は購読を持たないので循環しない)。EventsExecutor も測ったが、小さいメッセージで CPU がわずかに減る一方、画像 30 Hz で約 2 倍になったため使わない。

**統計** (`stats.cpp`, `stats.py` と同じ意味): トピック全体の値 (`hz` は publisher ごとの source_timestamp の周期の合計、連番が単調なら落ちた分も送信数に数える、`hz_recv`、`jitter`、`dropped` / `drop_ratio`、`latency_ms`、止まったら 0 (`stale`)、遅いトピックは 10 秒で計算 (`rate_note`)) に加え、**publisher (gid) ごと** に同じ計算をその gid のサンプルだけで行う (`endpoints[]`)。gid ごとの `stale` も個別に判定するので、2 つの送信者の片方が止まると、その送信者だけ即 0 になる。計算期間は `ProbeConfig.windows_sec` (1 / 5 / 10 秒) の全部を毎秒計算して送る (UI の期間切り替えにそのまま答えられる)。

**送信元ノードの特定 (RMW ごとの確認結果)**: 毎秒 `get_publishers_info_by_topic()` の `endpoint_gid` と、受信した `MessageInfo.publisher_gid` を突き合わせる。
| RMW | `publisher_gid` と `endpoint_gid` | 連番 | 結果 |
|---|---|---|---|
| `rmw_fastrtps_cpp` (Jazzy 既定) | 一致 (どちらも DDS の writer GUID 16 バイト) | 対応 | ノードごとに `measured` |
| `rmw_cyclonedds_cpp` | 不一致 (`publisher_gid` は writer のインスタンスハンドル 8 バイト + 0 埋め、`endpoint_gid` は GUID) | 非対応 (`dropped` は null) | gid ごとには分かれるがノードに対応づかない (`resolved: false`) → トピック合計にフォールバック (従来の `rates.py` の分割、送信元 2 以上は `unknown`)。UI に「この RMW では送信元のノードを区別できない」と出す |
Cyclone DDS は手動で確認した (`roshanavi:dev` のコンテナに一時的に `ros-jazzy-rmw-cyclonedds-cpp` を apt で入れ、`RMW_IMPLEMENTATION=rmw_cyclonedds_cpp` で C++ と Python の talker を計測。イメージには入れていない)。自動テストは Fast DDS のみ、フォールバックの判定は unit test。

**制御 (どのトピックを測るか)**: 選択の規則 (重い型の opt-in、トピックごとの切替、除外) は roshanavi 本体に残し (`traffic_select.TopicSelector`、両方の経路で共有するので経路が切り替わっても切替は保たれる)、結果だけを `/roshanavi/_probe/config` (`ProbeConfig`、RELIABLE + **TRANSIENT_LOCAL**、depth 1) で送る。毎回トピック集合全体を送り、計測ノードは差分で購読を張り替える (型・reliability が変われば作り直す)。集合が変わったときだけ送る。TRANSIENT_LOCAL なので、再起動した計測ノードは最後の設定を自動で受け取る (再送の仕組みが要らない)。パラメータサービスより単純で、rclpy の非同期クライアントも要らない。
- 同じドメインに roshanavi が複数いても混ざらないよう、サーバーは起動ごとにランダムな `instance` を作って計測ノードに `-p instance:=…` で渡す。計測ノードは自分の `instance` の設定だけを受け入れ、統計にも `instance` を付ける (サーバーは自分のもの以外を捨てる)。
- 統計は `/roshanavi/_probe/stats` (`ProbeStats`、RELIABLE、VOLATILE) に 1 Hz。サーバー側は受け取った最新の 1 通を dict に変換して保持し、`snapshot(window)` はそこから選んだ期間のエントリを返す。スパークライン用の 1 秒ごとの履歴 (既定の 5 秒の値) はサーバー側で積む。
- `/roshanavi/_probe/...` は自分用のトピック (`ros_runtime.is_self_topic`) で、地図・診断・トラフィックに出さず、Python の経路でも購読しない。計測ノードのノード名 `roshanavi_probe` は自分自身 (`roshanavi*`) として地図から隠れる。

**子プロセスとしての管理** (`probe_process.py`): サーバーの起動時 (`Lab.start`) に `ament_index` で `lib/roshanavi_probe/probe` を探し、`ros2 run` を介さず直接、新しいセッションで起動する。housekeeping (1 秒) で終了を検出し、1 → 2 → 4 → 8 → 16 → 30 秒の間隔で再起動する。起動から 30 秒以上動いて統計が届いていれば失敗回数を 0 に戻す (起動直後に毎回落ちる場合も数え続ける)。5 回続けて終了したら諦め、Python の計測に切り替える (`reason: crashed`)。プロセスは生きているのに統計が 15 秒届かない (固まった) ときは SIGKILL して、同じ再起動の流れに乗せる。停止は SIGTERM (3 秒) → SIGKILL。計測ノードは毎秒 `getppid()` を確かめ、親 (サーバー) が変わったら自分で終了する (サーバーが SIGKILL されても残らない)。統計が 3.5 秒届かない間は、監視中のトピックを `status: error` / `error: probe_unavailable` (UI は「計測ノードから統計が届いていません (再起動中)」) にする。

**経路の選択と状態** (`traffic_backend.TrafficService`): `--probe auto` (既定) / `off`。auto でも計測ノードが見つからなければ `reason: not_built`、`roshanavi_msgs` を import できなければ `unavailable` で Python の経路。`GET /api/traffic` と `/ws/live` に `measurement: {mode: probe|python, reason, state, pid, restarts, receiving, cpu_percent, rss_bytes, rmw, gid_resolution: matched|unmatched|unknown}` を付ける。トラフィックタブのツールバーに「計測: C++ 計測ノード (CPU 0.4%)」、Python の経路では理由 (「計測ノードがビルドされていないため、Python で計測しています。送信元ごとの値は推定になります。」など) を出す (`traffic/measurement.ts`)。計測ノードの CPU は計測ノード自身が `getrusage` で測って送る (観測者効果の確認、[resources.md](resources.md))。

**性能** (Docker、24 論理 CPU の WSL2、20 秒平均の CPU 使用率。100% = 1 コア。publisher は rclpy、計算期間 5 秒):
| 条件 | 経路 | 計測ノード CPU | サーバー CPU | 合計 | Hz (真値) | 帯域 |
|---|---|---|---|---|---|---|
| (a) String 64 B × 10 トピック × 100 Hz | C++ 計測ノード | 8.9% | 0.6% | **9.5%** | 100.00 (全トピック) | — |
| (a) 同上 | Python | — | 32.3% | 32.3% | 99.99〜100.00 | — |
| (b) Image 1280×720 rgb8 × 30 Hz (重い型を有効化) | C++ 計測ノード | 11.4% | 0.4% | **11.8%** | 30.00 | 82.9 MB/s |
| (b) 同上 | Python | — | 17.4% | 17.4% | 30.00 | 82.9 MB/s |
- 既知の改善余地: 毎秒、トピックごとに `get_publishers_info_by_topic()` を呼び、計算期間ごとにサンプルを gid で分け直している (20000 件 × 3 期間のコピー)。上の条件では問題にならないが、トピック数・頻度がさらに大きいときはグラフ変化時だけの照合と、1 回の分割の使い回しにする。
- 何も流れていないときの計測ノードは CPU 約 0.1〜0.4%、常駐メモリ約 30 MB (busy loop なし)。
- (a) は 1 メッセージあたり約 90 µs (DDS の受信スレッドと rclcpp の take を含む) で、Python の約 1/3。サーバーの CPU がほぼゼロになるので、API・WebSocket・注入のタイミングが統計の負荷に影響されなくなる。(b) の計測ノードの CPU の大半は、受信ごとの約 2.7 MB の SerializedMessage のコピー。
- Hz の精度はどちらも送信時刻ベースなので同等 (±0.01%)。違いは、送信元ごとに分けられること。
- 測り方: test イメージの中で publisher と `roshanavi server --probe auto|off` を起動し、15 秒待ってから 20 秒間 psutil で各プロセスの CPU を測り、`/api/traffic?window=5` の Hz を読む。

## 詳細計測モード (トレース計測, P4.7)
受信側のノードの **中で** 実際に受け取った数・処理した数・1 回の処理にかかった時間を、ROS 2 に組み込まれたトレースポイント (ros2_tracing / LTTng) で測る。既定はオフで、トラフィックタブの「詳細計測モード」で有効にした間だけ記録する。

**ファイル記述子 (fd) の扱い**: チャンクの解析 (bt2) は worker の中ではなく、**使い捨ての子プロセス** (`tracing/chunk_parser.py`、worker の子) で行う。worker は子にチャンクのパスを 1 行ずつ渡し、子はイベントを長さ付きの `marshal` フレームで返す (fd 1 は stderr に付け替え、bt2 の出力がフレームに混ざらない)。子はチャンクごとに bt2 のイテレータ (グラフが自分自身を参照する循環) を `gc.collect()` で解放してストリームファイルを閉じる。babeltrace2 2.0.x が閉じない `metadata` の fd は **閉じずに残し、子を 32 チャンクごとに入れ替える** ことで子と一緒に消す (以前はパスを見て fd を手動で閉じていたが、bt2 が後で同じ番号を閉じると再利用された別の fd を閉じる危険があった。issue #17)。子が落ちた・30 秒応答がない・途中で読むのをやめた場合は kill して次のチャンクで作り直し、そのチャンクは `parse_errors` に数える。worker の CPU 使用率には動いている子の CPU 時間 (`/proc/<pid>/stat`) を足す。bt2 のハンドルを解放しないと 5 秒ごとに 1 チャンクぶん (CPU 数+1 本) の fd が漏れ、約 3 分で `RLIMIT_NOFILE` (1024) に達して worker が `Too many open files` で落ちる。`lttng` CLI の `OSError` は `LttngError` に変換し、worker の再起動時は終了途中の `lttng-sessiond` を待って 2 つ目を作らない。サーバー自身の fd が `RLIMIT_NOFILE` の 70% を超えると警告ログを出す (`fd_guard.py`)。サーバー (ROS ノードとして LTTng-UST に登録される) 側の `(deleted)` な `shm-ust-consumer-*` などは CPU 数に比例する LTTng-UST 自身の固定分で、増え続けない。回帰テストは `test_tracing_fds.py` (子を 4 チャンクごとに入れ替えて fd が有界) と `test_tracing_parser.py` (偽の解析器で、フレーム・エラー・クラッシュ・ハング・入れ替え時の fd)。

**構成 (どの層のツールか)**
```
[対象ノード]  アプリのコード
               rclcpp / rclpy   ← トレースポイント (callback_start/end, init 系)
               rcl              ← トレースポイント (rcl_*_init)
               rmw              ← トレースポイント (rmw_publish / rmw_take)
               DDS
                 │ tracetools が LTTng-UST の API でイベントを記録
                 ▼
[LTTng-UST]   対象プロセス内のライブラリ。/dev/shm 上の CPU ごとのリングバッファに書く
                 ▼
[lttng-tools] セッションデーモン / コンシューマデーモン (別プロセス)。バッファを回収しファイル (CTF) に保存
                 ▼
[roshanavi]   解析プロセス (tracing/worker.py) が 1 秒ごとに区切って babeltrace2 で読み、集計してサーバーに送る
```
- 使うのは **ユーザー空間用 (LTTng-UST) のみ**。セッションデーモンは `--no-kernel` で起動し、root 権限・カーネルモジュール・Docker の特権は要らない (確認済み: `ros:jazzy` ベースのイメージで、`--privileged` なし)。
- 必要なパッケージ: `lttng-tools` と `liblttng-ust1t64` (どちらも `ros-jazzy-tracetools` の依存で入る)、`python3-bt2` (Ubuntu 24.04 では 2.0.5)。`ros2trace` / `tracetools_trace` は使わない (`lttng` コマンドを直接使う)。Jazzy の公式バイナリはトレースポイント入り (`ros2 run tracetools status` → `Tracing enabled`)。

**実装時の確認結果**
| 項目 | 結果 |
|---|---|
| rclcpp のイベント | `rcl_node_init`、`rcl_subscription_init`、`rclcpp_subscription_init`、`rclcpp_subscription_callback_added`、`rclcpp_callback_register` (処理関数の名前)、`rcl_publisher_init`、`rmw_take` (`taken` 付き、空振りも出る)、`callback_start` / `callback_end` (`is_intra_process` 付き)、`rmw_publish` など |
| rclpy のイベント | `rcl_*_init`・`rmw_take`・`rmw_publish` だけ。`callback_start/end` も `rclpy_*` も無い (Jazzy) → Python のノードは **受信数だけ** 測れる |
| セッションデーモンより前から動いているプロセス | 記録される (LTTng-UST がデーモンの登場を待っていて自動で登録する)。ただし init 系のイベントは起動時に 1 回しか出ないので、後から来たデーモンには届かない。`lttng regenerate statedump` は LTTng 自身のもの (ライブラリの配置) だけで、ROS の init は出し直さない → 対応づけには「ノードの起動より前から init を記録している」必要がある |
| rclcpp の take と処理 | rclcpp の executor は、コールバックを実行する直前に 1 通だけ take する。処理が遅くても take ≒ 処理数で、追いつかない分は take される前に DDS のキュー (QoS の depth) から溢れる。**受信 > 処理 の差は rclcpp ではほぼ出ない** → 下の「処理が追いついていない」の判定で送信側の実測と比べる |
| /dev/shm | per-UID のリングバッファは /dev/shm に置かれる。Docker の既定 64 MB では 4 MiB × 24 CPU が入らず、**エラーも出さずに何も記録されない** (セッションデーモンが落ちることもある) → compose に `shm_size: 512m`、さらに空きの半分に収まるようバッファを自動で縮める |
| ローテーション | `lttng rotate` は完了まで 0.3〜1 秒待つ (2 セッションで 1 秒を超える)。`--no-wait` で頼み、完了した区切りが `archives/` に移ってから読む。続けて頼むと `Rotation already pending` |
| `lttng start` | コマンドが戻る前に記録が始まる (戻った時刻を開始にすると最初の窓で Hz が 5% 高く出た) → `start` を呼ぶ直前の時刻を開始とする |

**2 つのセッション** (`tracing/config.py`): どちらも `--buffers-uid`。
- **init** (サーバーの起動時から、`--tracing auto` で lttng と python3-bt2 があれば): 起動時に 1 回だけ出るイベント (`rcl_node_init` / `rcl_subscription_init` / `rclcpp_subscription_init` / `rclcpp_subscription_callback_added` / `rclcpp_callback_register` / `rcl_publisher_init`) だけ。メッセージごとのイベントは無いので対象ノードの負荷はほぼゼロ (バッファ 64 KiB × 2 / CPU)。これで、詳細計測モードを後から有効にしても、roshanavi より後に起動したノード (Launcher が起動するノードを含む) は再起動なしに測れる。`Lab.start` で Launcher の autostart より前に始める。待機中は 5 秒ごとに区切る。
- **rt** (詳細計測モードの間だけ。有効化で作り、無効化で消す): `rmw_take` (フィルタ `taken == 1`)、`callback_start`、`callback_end`、`rmw_publish`。コンテキストは vpid / vtid。roshanavi 自身 (サーバー・計測ノード) は `$ctx.vpid != …` のフィルタで記録の段階で除外する。バッファは既定 4 MiB / CPU (`--trace-buffer-kib`)、/dev/shm の空きの半分に収まるよう 2 の冪で縮め (最小 4 KiB × 2)、それも無理なら 507 `shm_too_small`。1 秒ごとに区切る。

**解析プロセス** (`tracing/worker.py`, `python3 -m roshanavi.tracing.worker`): 解析 (babeltrace2 の Python 版、1 イベント約 13〜15 µs) は重いので、サーバーとは別プロセスにする (サーバーの asyncio と rclpy の executor が GIL を取り合わない)。サーバーとは標準入出力の JSON 行でやりとりする (`enable` / `disable` / `quit`、`ready` / `state` / `snapshot` / `error`)。1 周期ごとに各セッションの完了した区切りを古い順に読み、**読んだらすぐ消し**、次の区切りを頼む。窓の終わりは最後に読んだ rt の区切りを頼んだ時刻 (まだ読んでいない時間を 0 件として数えない)。64 MiB を超える区切りは読まずに捨てる (`skipped_chunks`)。読めない区切りも捨てて続ける。
- セッションデーモン: 動いているもの (ユーザー自身のものや別の roshanavi のもの) があれば使い、止めない。無ければ解析プロセスの子として起動し (`PR_SET_PDEATHSIG` で解析プロセスと一緒に終わる)、終了時に止める。セッション名は `roshanavi-<サーバー pid>-<id>-init|rt` で、起動時にサーバーがもう居ない古いセッションを消す。解析プロセスを再起動しても同じ名前を使い、前のセッションを置き換える。
- 終了: サーバーの終了時 (`Lab.stop` と atexit) に `quit` → 両方のセッションを destroy → 自分で起動したデーモンを停止 → 一時ディレクトリ (`/tmp/roshanavi-trace-*`) を削除。サーバーが消えたら標準入力の EOF (または親 pid の変化) で同じ後片付けをする。
- 解析プロセスが落ちたら 5 秒後に起動し直す (3 回まで)。デーモンごと消えた場合は init の記録も失われるので、それまでのノードは再起動が必要になる (既知の制限)。

**集計** (`tracing/model.py`, 純粋): ハンドルはプロセス内のポインタなので、キーは常に (vpid, ハンドル)。`rcl_node_init` (ノード名) → `rcl_subscription_init` (ノード・rmw ハンドル・トピック) → `rclcpp_subscription_init` → `rclcpp_subscription_callback_added` (コールバック) の連鎖で、`rmw_take` を受信、`callback_start` / `callback_end` を (vpid, vtid) ごとに対にして処理と処理時間、`rmw_publish` を送信に数える。1 / 5 / 10 秒の窓ごとに `hz_recv`・`hz_processed`・`cb_ms {avg, p95, max}`、送信は `hz`。Hz は probe (`stats.py` の `window_rate`, [measurement.md#C++ 計測ノード](measurement.md#c-計測ノード-roshanavi_probe-p46)) と同じ規則で、窓の中のイベント時刻から (n−1)/(最後−最初) で求める (件数 ÷ 経過時間にすると 1 Hz が起動直後 1.12 Hz と出た)。窓に 2 件未満なら最長 (10 秒) の窓に広げ、それでも 2 件未満なら null (UI は「計測中…」)、止まっていれば 0。intra-process のコールバックは rmw を通らないので受信は null。10 秒ごとに終了したプロセスの記録を捨てる (ハンドルの再利用対策)。init の無いプロセスからの記録は `unknown_pids`。

**交通量への反映** (`tracing/merge.py`, 純粋): `Lab.traffic_view` の最後に、トレースが対応づいた受信行 (`subscribers[]`) を `basis: "measured"` にし、`hz` = `hz_recv` (intra-process は処理数)、`bps` = `hz × avg_size`、`hz_recv` / `hz_processed` / `cb_ms` / `lang` (`cpp` | `py`) / `intra` / `symbol` (処理関数) を付ける。元の理論値は `hz_expected`。最初の値が出るまでは理論値のまま。QoS が合わない行は `not_delivered` のまま値だけ付ける。送信行には `hz_traced` (計測ノードの実測との突き合わせ用)。
- **処理が追いついていない** (`behind`): 届く量 = max(送信側の実測の和 `hz_expected`, 受信数)。処理数がそれより 10% 以上かつ 0.5 Hz 以上少なければ `behind: {incoming_hz, processed_hz, basis: sent|received, cb_avg_ms}`、`/api/tracing` の `diagnostics[]` に `processing_behind`。届く量 0.5 Hz 未満と rclpy は判定しない。UI は「受け取っていますが処理が追いついていません: 届く量 10.0 Hz に対して処理 5.00 Hz (1 回の処理に平均 200 ms)」。
- **測れないノード** (`unsupported[]`, 理由つき): `rclpy` (受信数だけ)、`intra_process` (受信数が測れない)、`restart_needed` (起動リストのノードで、プロセスの起動が init の記録の開始より前)、`not_traced` (記録が無い: 別のコンテナや PC、または roshanavi より前から動いている外部ノード。pid が分からないので両者は区別できない)。

**API**: `GET /api/tracing` → `{available, reason: disabled|not_installed|bt2_missing|failed|null, active, active_sec, receiving, error, events_per_sec, discarded, disk_bytes, parse_ms, buffer_per_cpu, skipped_chunks, cpu_percent: {server, worker, lttng, total}, restarts, unsupported[], diagnostics[]}`。`PUT /api/tracing {"enabled": bool}` (操作。セキュリティのミドルウェアを通り、JSON 以外は 415、余計な項目は 422)。使えないときは 409 `tracing_unavailable`。`/ws/live` に `tracing`。`discarded` は `lttng --mi xml list` の `discarded_events` (CTF の packet の数と大きい方)。roshanavi の CPU はサーバー・解析プロセス (呼んだ `lttng` コマンドを含む)・LTTng のデーモンの合計。

**UI** (`traffic/TracingToggle.tsx` / `TracingStatusBar.tsx` / `tracing.ts`, `detail/NodeTracing.tsx`): ツールバーの「詳細計測モード」をオンにすると、先に負荷の説明 (計測されるノード側 / roshanavi 側、下の実測値) のダイアログを出し、「有効にする」で始める (止めるときは確認なし)。lttng や python3-bt2 が無いとチェックボックスは無効で、導入方法 (`sudo apt install lttng-tools python3-bt2`) を出す。有効な間は状態バー (経過秒・件/秒・取りこぼし・ディスク・roshanavi の CPU、追いついていないノード、測れないノードと理由)。受信行は `実測(トレース)` バッジと「受信 / 処理 / 処理時間」、Python のノードは処理・処理時間が「未対応」。窓に十分なイベントが無い間 (null) は数値の代わりに「計測中…」を出す。右ペインのノードには、受信トピックごとの受信・処理・処理時間と処理関数の名前。

**負荷: 見積もり (仕組みと文献から)**
- 対象ノード側: 有効なトレースポイント 1 回あたり数百 ns (CPU ごとのバッファへの書き込みのみ)。1 メッセージあたり送信側約 3・受信側約 5 イベントで数 µs。1 kHz でも CPU 1 コアの 0.1〜0.5%、遅延も数 µs。
- roshanavi 側: メモリはリングバッファ CPU 1 個あたり 4 MiB 程度。ディスクは 1 イベント 50〜100 B、100 Hz × 10 トピックで毎秒約 8,000 件・約 0.6 MB/秒、区切って消すので数十 MB 以内。解析 (Python の babeltrace2) は毎秒数千件で CPU 1 コアの数十%。表示は 1〜2 秒遅れる。バッファが溢れたらイベントを捨てる (対象ノードは止めない)。

**負荷: 実測** (Docker、24 論理 CPU の WSL2、`shm_size: 512m` でバッファ 4 MiB/CPU。publisher / subscriber は C++ (`roshanavi_test_nodes` の rate_talker / slow_listener、眠りなし)。`roshanavi server --probe auto --tracing auto` を動かしたまま、オフ 20 秒 → オン 20 秒を 2 回 (a は 2 回の実行で計 4 回) 測った平均。CPU は 100% = 1 コア。遅延は受信時刻 − 送信時刻 (同じ PC) の平均。`scripts/bench_tracing.py`):
| 条件 | 対象ノードの CPU (オフ → オン) | 遅延 (オフ → オン) | roshanavi のトレース分の CPU (解析 + LTTng デーモン) | 件/秒 | ディスク (最大) | 取りこぼし |
|---|---|---|---|---|---|---|
| (a) String 64 B × 10 トピック × 100 Hz (送信 10 + 受信 10 プロセス) | 33.5% → 34.5% (各回 30.0〜37.0%、差は回ごとのばらつき ±3% より小さい) | 183 µs → 189 µs | 13.0% + 3.2% = **16.2%** (オフでも 0.3% + 0.3%) | 約 6,000 | 0.69 MB | 0 |
| (b) Image 1280×720 rgb8 × 30 Hz | 6.4% → 6.4% | 5.1 ms → 5.0〜6.4 ms (ばらつきの範囲) | 2.8% + 3.1% = **5.9%** | 約 180 | 0.45 MB | 0 |
- サーバー本体の CPU (a で 1.3〜1.5%、b で 0.7%) と計測ノード (a で約 9.7%) はオン・オフで変わらない。
- **見積もりとの違い**:
  - 件/秒は見積もり (8,000) より少ない約 6,000 = 1 メッセージあたり 6 件 (受信側 take + 処理の開始・終了 = 3、送信側 publish = 1、送信側のタイマーのコールバックの開始・終了 = 2)。使うイベントを絞ったため。タイマーのコールバックも `callback_start/end` を出し、記録の段階では区別できない (集計で捨てる)。
  - 対象ノード側は、毎秒 1,000 メッセージで差が約 +1% (見積もり 0.1〜0.5%)。ただしこの PC では回ごとのばらつき (±3%) の方が大きく、1% 未満は分解できない。上限としては 1 メッセージあたり 10 µs 程度。遅延は +5 µs 程度で見積もりどおり。
  - roshanavi 側の CPU は見積もり (数十%) の下の方: 毎秒 6,000 件で 16%。ただし **記録が少なくても約 6% の固定費** がある (1 秒ごとのローテーションと取りこぼしの確認で、毎秒 3 回 `lttng` コマンドを起動し、デーモンが区切りを書き出すため)。
  - ディスクは見積もり (数十 MB) よりずっと少なく 1 MB 未満 (1 秒ごとに区切って、読んだら消すため)。
  - メモリ: リングバッファは /dev/shm を使う (24 CPU × 4 MiB = 96 MiB + init 3 MiB)。Docker の既定 (64 MB) では足りないので、空きに合わせて縮める (64 MB なら 1 MiB/CPU)。
- 取りこぼしは、8 KiB/CPU の小さいバッファで 2000 件ずつのバーストを送ると起き、件数が表示される ([testing.md の L-11](../project/testing.md#l-詳細計測モード-トレース-p47))。既定の 4 MiB/CPU では上の条件で 0。

**制約**
- 測れるのは roshanavi と同じ PC (Docker では同じコンテナ、またはセッションデーモンを共有する構成) で、roshanavi より後に起動したノード。前から動いているノードは再起動すると測れる。ラボの `demo` コンテナの external_* は `not_traced`。
- Python のノードは受信数だけ (処理数・処理時間は「未対応」)。intra-process は受信数が測れない。
- RMW は Fast DDS (Jazzy 既定) で確認した。`rmw_take` / `rmw_publish` は rmw の実装ごとのトレースポイントなので、他の RMW では受信・送信が出ない可能性がある ([testing.md の L-18](../project/testing.md#l-詳細計測モード-トレース-p47))。
- ノードの起動直後 1〜2 秒は、init の区切りがまだ読まれておらず、そのノードの記録を捨てることがある。

## CPU が高い (MultiThreadedExecutor の空回り)
**症状**: Python (rclpy) のノードが、メッセージをあまり処理していないのに CPU を 1 コア近く使う。`py-spy` やトレースでは `wait` を数千回呼んでいる。コールバックが遅れる・間引かれる。

**原因**: `MultiThreadedExecutor` + Fast DDS (`rmw_fastrtps_cpp`、Jazzy 既定) + rclpy 既定の QoS イベント通知の組み合わせ。購読のコールバックを実行中、その購読は executor の待ち受けから外れるが、QoS イベントの待ち受けは残っていて同じ「データ到着」の目印を見ているため、`wait()` が「何かあった」とすぐ戻り続ける (ros2/rmw_fastrtps#929、関連 ros2/rclpy#1223)。詳細と数え方は [nodes.md の executor_busy_demo](nodes.md#executor_busy_demo--multithreadedexecutor-の空回りを体験する-40)。

**確かめる**: サンプル `examples/busy_demo` (⚙ のプロジェクト切り替え) で 3 つの構成を 1 つずつ起動して `/busy_demo/*/stats` (1 秒ごとの JSON、ログにも 1 行) を比べる。地図ではリソース監視のバッジで、空回りしているノードが赤く光り `CPU 90% 前後` と出る (リソースタブ・右ペインでも同じ値。[resources.md#busy_demo で確かめる](resources.md#busy_demo-で確かめる))。シナリオでは `resources: {node, cpu_max}` で確かめられる (`examples/scenarios/busy_cpu.yaml`)。自分のノードで試すなら `executor_busy_demo.py` の `PassCounter` が使える。

実測 (Docker の PC、24 コア、`rmw_fastrtps_cpp` 8.4.4、`work_ms` 5、送信 100 Hz、MultiThreaded は 4 スレッド、6 秒間の中央値。同じ測定を別の実行で 3 回やって、空回りの構成は 7,900〜8,300 回/秒・CPU 85〜89% で変わらなかった):

| 構成 | 待ちの回数/秒 | うち空振り | 処理できた/秒 (送信は 100) | 1 コールバックあたりの待ち | CPU |
|---|---|---|---|---|---|
| multi + default (問題) | 8,279 | 99.5% | 38 | 219 | 89% |
| multi + off (回避) | 303 | 66.7% | 100 | 3.0 | 8% |
| single + default | 201 | 49.8% | 100 | 2.0 | 4% |

正常でも空振りの割合が約 50〜67% なのは、executor 自身の「処理が終わった」合図で 1 コールバックあたり 1〜2 回起きる分。見るのは回数 (数千/秒) と CPU、そして処理できた数が送信より減っていること。

**直す**: (1) 購読に `event_callbacks=SubscriptionEventCallbacks(use_default_callbacks=False)` を渡して QoS イベントを外す (upstream の回避策、roshanavi も同じ)。(2) 並列で動かす必要がなければ `SingleThreadedExecutor` にする。
**トレードオフ**: (1) は購読と送信側の QoS が合わないときの「incompatible QoS」の警告ログも消えるので、データが来ない原因に気づきにくくなる。CPU が問題になる購読だけ外す。
