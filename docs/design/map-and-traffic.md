# roshanavi — 地図とトラフィック

ノード ⇄ トピックのグラフ、診断 (QoS 互換など)、トラフィック統計とレートの意味 (ノード × トピック × 向きごとの行を含む)。計測の仕組み (C++ 計測ノード・トレース) は [measurement.md](measurement.md)、画面は [ui.md](ui.md)。

## ros_runtime
- 単一ノード `roshanavi` を生成し、`MultiThreadedExecutor` をデーモンスレッドで spin。
- FastAPI (asyncio) からの操作はロックで保護したメソッド経由。購読コールバックは統計更新のみ行い軽量に保つ。
- 自分自身 (ノード名 `roshanavi*`) はグラフ・統計から既定で除外 (`show_self` オプション)。

## graph
- `get_node_names_and_namespaces()`, `get_topic_names_and_types()`, `get_publishers_info_by_topic()`, `get_subscriptions_info_by_topic()` から構築。
  - rmw の付属トピック (区切りが `_buf_` で始まるもの。Lyrical の rmw_fastrtps がバイト列を持つ型の C++ の購読ごとに `<topic>/_buf_cpu` を足す) は `RosRuntime.topic_names_and_types()` の時点で除き、地図・計測・エコーのどれにも出さない (購読すると付属トピックが連鎖して増える)。rclpy が問い合わせを拒むトピック (長すぎる名前など) は警告を出して飛ばし、地図の更新は止めない。
- 出力: `{nodes:[{id,name,namespace,role}], topics:[{name,types[]}], edges:[{node,topic,dir:"pub"|"sub",qos:{reliability,durability,history,depth,deadline_ms,liveliness,lease_ms}}], diagnostics:[...]}`
  - `deadline_ms` / `lease_ms` は未設定・無制限なら `null`。
  - `role`: 実ノードは Launcher の対応づけ ([launcher.md#Launcher](launcher.md#launcher-p3)) で `mine` / `dependency` / `dummy` になり、`target_id` と `confidence` (`exact`/`heuristic`) が付く。対応づかないノードは `"other"`。同じ完全修飾名のノードが複数あっても 1 つにまとめる。実行中の注入ジョブ (topic を持つもの) は仮想ノード `dummy:<job id>` (`role:"dummy"`, `job_id`) として pub エッジ付きで含める。注入の publisher は roshanavi 自身のノード (既定で非表示) に属するため、ジョブ単位の仮想ノードにしないと注入が地図に現れない。bag ジョブは `rosbag2_player` が通常ノードとして見えるので仮想ノードにしない。
  - `diagnostics` (`diagnostics.py` / `qos_compat.py`, 純関数): `{code, severity, topic, nodes[], detail}`。重大度順 (error → warning → info) で決定的に並べる。
    - `qos_incompatible` (error): topic ごとに pub × sub の全組を判定。reliability (BEST_EFFORT pub → RELIABLE sub)、durability (VOLATILE pub → TRANSIENT_LOCAL sub)、deadline (pub の deadline > sub の要求、pub 無制限で sub 有限も不可)、liveliness (AUTOMATIC pub → MANUAL_BY_TOPIC sub)、lease (pub > sub)。`detail.reasons=[{policy,pub,sub}]`。
    - `similar_names` (warning): 片側しかいないトピック A (送信だけ・受信だけ) と、その欠けている側が使っている別のトピック B の名前が似ている。`_`/`-`/大小文字を除くと同一、または同じ名前空間で最後の区切りの Levenshtein 距離 ≤ 2 (4 文字以下の名前は ≤ 1)。B が A と同じく片側だけでも、つながっているトピックでもよい (`/chater` を送っていて、受信側は `/chatter` を待っている、が典型の打ち間違い)。同じ組は 1 件にまとめる (`topic` は片側だけのトピック。両方が片側だけなら送信のみの方)。`detail={published, subscribed}`。初心者にとっての価値はここにあるので、片側だけのトピックそのものは警告にしない (次項)。
    - `no_subscriber` / `no_publisher` (**info**): 片側しかいないトピック。センサーを作ってまだ誰も受け取っていない、は組み立て中の普通の状態なので警告にしない。診断パネルのバッジ (件数) には数えず、パネルにも出さない。地図ではトピックの名前の下に小さく「受信なし」「送信なし」、トピック・ノードの詳細ペインでは控えめな行として出す。
    - `subscriber_lost` / `publisher_lost` (warning、履歴が要るので `diag_history.py`): 直近 5 分に受信者 (送信者) がいたトピックが、送信者 (受信者) が残っているのに、受信者 (送信者) 0 になった。「さっきまで /x が受信していましたが、いなくなりました」。0 の状態が 3 秒続いてから出す (ノードの再起動で一瞬点滅しない)。`detail.lost=[いなくなったノード]`、`nodes` は残っている側。
    - `mine_no_input` (warning): `role: mine` のノードが購読しているトピックに送信元がいない (ノードが現れて 3 秒たち、トピックの送信元なしが 3 秒続いた後)。「開発中のノード /n の入力 /t に送信元がいません」。同じトピックの `publisher_lost` は出さない (こちらの方が具体的)。地図ではそのノードとトピックを警告色で囲む。
    - `type_mismatch` (error): 同名トピックに複数の型。
  - **診断に数えないもの (インフラ)**: 隠しトピック (`_` で始まる区切り。アクションの `*/_action/*` を含む)、`/rosout`、`/parameter_events`、`/events/write_split` (録画中に `ros2 bag record` 自身が出す内部トピック)、ライフサイクルノードの `*/transition_event`。隠しノード (名前が `_` で始まるもの。ROS CLI のデーモン `_ros2cli_daemon_*` と、`ros2 topic echo` などが一時的に作る `_ros2cli_*`) と roshanavi 自身のノード (ビューア・エコー・計測ノード) は、送信者・受信者として数えない。これらが購読していても「受信者がいる」とは見なさず、いなくなっても `subscriber_lost` にならず、QoS の判定にも入れない。UI の「内部トピック・内部ノードを隠す」トグル (既定でオン) も同じ規則で、これらのトピックとノードを地図から外す (`lib/topics.ts` の `isHiddenTopic` / `isHiddenNode` はバックエンドの `is_hidden_topic` / `is_hidden_node` と同じ規則)。トラフィックタブの「畳む」対象 (`/rosout`、`/parameter_events`、`/events/write_split`、ライフサイクルの `*/transition_event`) は別の仕組み (`traffic_select.DEFAULT_COLLAPSED`) で、同じ内部トピックを畳む。
  - 文言は UI 側の i18n 辞書で組み立てる (API は英語のコードと構造化データのみ)。
  - **診断の履歴 (`diag_history.py`)**: `GraphHistory.update(now, snapshot)` が 1 秒ごとのスナップショットを受けて、トピックごとの「最後に受信者 / 送信者がいた時刻と顔ぶれ」、トピックの「送信者なしが始まった時刻」、ノードの「初めて見えた時刻」を覚える。時刻は呼び出し側が渡す (単調時計)ので、テストでは任意のタイムラインで動かせる。経過秒数は `detail` に入れない (毎秒スナップショットが変わって再送されるため)。覚えている間はウィンドウ (5 分) で切る。roshanavi の再起動直後は履歴が空なので `*_lost` は出ない。
- 1 秒周期でスナップショットを更新し、変化時のみ WS 送信 (ハッシュ比較)。

## traffic
- **計測の経路**: 既定 (`--probe auto`) は C++ の計測ノード `roshanavi_probe` ([measurement.md#C++ 計測ノード](measurement.md#c-計測ノード-roshanavi_probe-p46)) が測り、送信元ノードごとの値も出す。計測ノードがビルドされていない・繰り返し異常終了する・`--probe off` のときは、この節の Python の計測 (`TrafficMonitor`) を使う。どちらもエントリの形は同じで、`measurement: "probe" | "python"` で区別する。以下の統計の意味は両方に共通 (C++ 側は `stats.py` と同じ計算を移植)。
- 新規トピックを 1 秒周期で検出し `create_subscription(msg_type, topic, cb, qos, raw=True)` で購読 (デシリアライズしない)。
- QoS 互換: 当該トピックの publisher に BEST_EFFORT が 1 つでもあれば BEST_EFFORT で購読、それ以外 RELIABLE。durability は VOLATILE、depth 10。
- 購読コールバックは 2 引数 `(data, info)` で、rclpy Jazzy が `raw=True` でも渡す `MessageInfo` (dict: `source_timestamp`, `received_timestamp` [ns], `publication_sequence_number`, `reception_sequence_number`) を使う。`publisher_gid` は rclpy Jazzy では公開されないため gid は none。Lyrical の rclpy 10 は `publisher_gid` を dict (`{'implementation_identifier', 'data': bytes}`) で渡すので `data` を gid にする (`stats.sample_from_info`)。publisher 別集計はどちらでも C++ の計測ノードだけ (Python 側の gid は今は使っていない)。サンプルは (受信 monotonic 時刻, size, source_ts, received_ts, gid, seq)。純粋な統計計算は `stats.py` (時計注入可)。
- **計算期間 (P4.5a)**: サンプルは最長の 10 秒分を保持し、`GET /api/traffic?window=1|5|10`・`/ws/live?window=…` で指定した期間の平均を返す (各エントリに `window_sec`)。それ以外の値は 400 `invalid_window` (WS はエラーを送って close 1008)。UI は選んだ期間を「直近 5 秒の平均」のように表示する。
- **止まったら即 0 (P4.5a, `stats.is_silent`)**: 最後の受信から max(3 × 期待周期, 1 秒) 何も届かなければ、`hz` / `hz_recv` / `hz_source` / `bytes_per_sec` を 0 にし `stale: true` を付ける (期間平均の残留で、止まったトピックが数秒間動いて見えるのをなくす)。期待周期は保持中のサンプルの平均受信間隔 (選んだ期間によらない)。サイズ・ジッタ・遅延は最後の値のまま。1 秒ごとの hz 履歴も 0 になる。
- 統計 (スライディングウィンドウ既定 5 秒): `hz`, `hz_basis` (`"source"`|`"receive"`), `hz_recv`, `hz_source`, `bytes_per_sec`, `avg_size`, `jitter_ms`, `jitter_recv_ms`, `dropped`, `drop_ratio`, `latency_ms`, `last_seen`, `total_count`。スパークライン用に 1 秒刻みの hz 履歴を 60 点保持。
  - `hz_recv`/`jitter_recv_ms`: 受信時刻の間隔 ((n-1)/span, 標準偏差)。`ros2 topic hz` 相当で、欠落・購読遅れで過小評価し転送ジッタを含む。
  - `hz_source`: publisher 側レート。publisher (gid) ごとに source_timestamp 間隔から算出して合算。連番が単調ならロスした分も publish 数に数える。全サンプルの source_timestamp が 0/未対応なら null で、`hz`/`jitter_ms` は受信側にフォールバック (`hz_basis="receive"`)。`jitter_ms` は source 間隔の標準偏差 (publish ジッタ)。
  - `dropped`/`drop_ratio`: ウィンドウ内の publication_sequence_number の欠番 (publisher ごと)。連番が 0 / 非単調 (publisher 再起動、gid 無しでの複数 publisher の混在、RMW が未設定) の場合は `null`。
  - `latency_ms`: mean(received_timestamp - source_timestamp)。publisher と subscriber が同一ホスト (同一クロック) の場合のみ意味を持つ。
- 重い型 (`sensor_msgs/msg/Image`, `CompressedImage`, `PointCloud2`, `PointCloud`。LaserScan は含まない) は既定で購読せず `status:"not_monitored"`, `monitored:false` で一覧に残す (グラフ情報は表示)。`--monitor-heavy` で全て監視、`PUT /api/traffic/{topic}/monitor` `{"enabled": bool}` でトピック単位に実行時切替 (既定より優先、任意のトピックを無効化も可)。購読の張り替えは次回の housekeeping (<=1 s) で反映され、`monitored` は即時に更新される。**この切り替えはプロジェクトファイルの `traffic_monitor: {<トピック>: true|false}` に保存され** (`Lab.set_topic_monitoring` → `Launcher.set_traffic_monitor`、自動保存)、再起動やプロジェクトの切り替え・読み直しで復元される (`TopicSelector.replace_overrides`。housekeeping が、プロジェクト側の値が変わったときだけ適用し直す)。エントリには `heavy` (型が上の重い型か) も付く。
- 除外: 正規表現リスト (既定で `/rosout`, `/parameter_events`, `/events/write_split`, `*/transition_event` は統計対象だが UI で畳む)。型解決できないトピックは `unsupported` として記録し購読しない。
- 消えたトピックは購読解除。
- **送信元ごとの値 (`rates.py`, 純関数)**: `/api/traffic` と `/ws/live` の各エントリに `source_count` と `publishers:[{node, hz, bps, basis}]` を付ける。
  - **計測ノードの経路** (`measurement: "probe"` で、全 publisher の gid がグラフと対応づいたとき): 各送信ノードの値は計測ノードが数えた値 (`"measured"`、同じノードの publisher が複数あれば合計)。注入ジョブ (`dummy:<id>`) は送った件数から求めた値 (`"exact"`) のまま。送った件数がまだ無いジョブが 1 つだけなら、roshanavi 自身のノードの実測値をそのジョブに当てる。グラフにいるのに何も届いていない送信者は `0 Hz` の `"measured"` (計測ノードは QoS を全送信者に合わせて購読するので、届かない = 送っていない)。
  - **Python の経路**、または gid が対応づかない RMW ([measurement.md#C++ 計測ノード](measurement.md#c-計測ノード-roshanavi_probe-p46)) では、統計はトピック単位で受信したサンプルの送信元は区別できない。そこで roshanavi が正確に分かる値から地図のエッジ用に分ける。
  - 注入ジョブ (`dummy:<id>`): 実際に送った件数から求めた送信レート (`Job.send_rate`、直近 5 秒、bytes/s は最初のメッセージのシリアライズ後サイズ × Hz) → `basis:"exact"`。恒久ダミーノード: 設定の `rate_hz` → `"configured"`。
  - それ以外の送信元が 1 つだけ: ダミーが無ければトピック合計そのもの (`"measured"`)、あれば `max(0, 合計 − ダミーの合計)` (`"estimated"`、UI に「推定」と説明)。bytes/s はダミー全員のサイズが分かるときだけ分ける。
  - それ以外の送信元が 2 つ以上: 分けられないので `"unknown"` (エッジに数値を出さず、トピックに「合計 X Hz / 送信元 N」)。受信側のエッジ (topic → sub) は常にトピック合計。
  - **計測していないトピック** (`status:"not_monitored"`、#61): 数字が無いのは「分けられない」のではなく「見ていない」なので、`"unknown"` になる送信元は `"not_monitored"` にする (注入ジョブ・恒久ダミーの既知の値はそのまま)。受信側の行も、数字が無ければ `basis:"not_monitored"` (`delivered` は QoS の判定のまま)。
  - **詳細計測モード** ([measurement.md](measurement.md)) がオンのとき、計測していないトピックの送信元の行は、トレースが数えた送信回数 (`hz_traced`) を Hz にする (`basis:"traced"`、帯域は `null`)。エントリには全送信元がトレースされたときだけ合計の `hz_traced` を付ける。受信側は従来どおり、ノードの中で数えた受信 Hz (`"measured"`)。データの大きさと関係なく測れるが、帯域は測れない。

## 送受信ごとのトラフィック・遅いトピック (P4.5b)
- **受信者ごとの理論値** (`sub_rates.py`, 純関数): 受信側のノードの中で実際に受け取った量は外から測れない ([ui.md#ライブ通信マップ](ui.md#ライブ通信マップ-graph-タブ))。受信者の値は、QoS が合う送信者が送っている量 = 届くはずの量: 全送信者が合う → トピック全体の実測、一部だけ → 合う送信者の値 (rates.py の分割) の和 (分けられなければ null)、1 つも合わない → 0 と `delivered: false`。計測ノードの経路 ([measurement.md#C++ 計測ノード](measurement.md#c-計測ノード-roshanavi_probe-p46)) では、全送信者が合うときも送信者ごとの実測値の和を使う (止まった送信者の分がすぐ消える)。同じノードが同じトピックに複数の publisher を持っていても 1 回だけ数える。`basis` は `theoretical` / `not_delivered`。詳細計測モード ([measurement.md#詳細計測モード](measurement.md#詳細計測モード-トレース計測-p47)) でトレースが対象のノードを測れていれば `measured` に置き換わる (理論値は `hz_expected` に残る)。
- **遅いトピック**: 計算期間 (1 / 5 / 10 秒) より遅いトピックは、期間内のメッセージが 2 個未満になり 0 Hz と誤読される。生きている (`stale` でない) のに 2 個未満なら最長の 10 秒で計算し直し `rate_note: extended`、`rate_window_sec: 10` を付ける。10 秒でも 2 個未満なら `rate_note: too_few` (hz は 0、UI は「—」)。
