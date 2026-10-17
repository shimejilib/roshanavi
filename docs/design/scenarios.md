# roshanavi — シナリオ (実装予定)

> **実装予定 (P6)**。この文書はシナリオの仕様で、runner / CLI / JUnit / 記録モード / Scenarios タブはまだ実装していない ([roadmap.md](../overview/roadmap.md))。

## シナリオ (G4)

対象ユースケース: **センサー処理パイプライン** (画像・点群の前処理・認識) と **自作ノード群** (独自 msg, 状態遷移)。MVP はトピックのみ (サービス・アクションは今後対応、README に明記)。

## ステップの種類

| ステップ | 意味 |
|---|---|
| `send` | 1 件送る (式 `${}` 可) |
| `start` / `stop` | 周期送信やストリームを裏で開始・停止する (`id` で参照) |
| `play` | bag を再生する (`topics` で絞り込み可、`wait: true` で再生終了まで待つ) |
| `wait` | 指定秒待つ |
| `expect` | `within` 秒以内に、`where` を満たすメッセージが `count` 件届く |
| `always` | `for` 秒間、届くメッセージがすべて `where` を満たす (最低 1 件届くこと、`min_count` で変更可) |
| `never` | `for` 秒間、`where` を満たすメッセージが 1 件も来ない (`where` 省略時は「何も来ない」) |
| `rate` | `for` 秒間の周期が `min_hz..max_hz` に入る |
| `throughput` | 入力トピックの件数に対する出力トピックの件数の比が `min_ratio` 以上 (取りこぼし・フレーム落ちの検出) |
| `latency` | 入力と出力を `match` (`header.stamp` または `order`, [scenarios.md#latency の対応づけモード](scenarios.md#latency-の対応づけモード)) で対応づけ、処理時間の `p50/p95/max` を上限で判定 |

加えて、シナリオ全体に掛かる **`guards`** を持てる。例: 「シナリオ中ずっと `/state` が ERROR にならない」。`never`/`always` と同じ書き方で、どのステップの最中に破れても fail にする。

## 例

```yaml
# センサー処理: bag の画像を流し、検出ノードの出力・取りこぼし・処理時間を確認
name: detector_basic
setup:
  - cmd: ["ros2", "launch", "my_perception", "detector.launch.py"]
    wait_for_node: /detector
steps:
  - play: {id: cam, bag: bags/street_30s, topics: [/camera/image_raw]}
  - expect: {topic: /detections, within: 3.0}
  - throughput: {input: /camera/image_raw, output: /detections, for: 10.0, min_ratio: 0.95}
  - latency: {input: /camera/image_raw, output: /detections, match: header.stamp, p95_ms: 100}
  - stop: cam
  - never: {topic: /detections, for: 1.0}    # 入力が止まれば出力も止まる
```

```yaml
# 自作ノード: 状態遷移
name: state_machine
guards:
  - never: {topic: /state, where: [{field: data, op: eq, value: ERROR}]}
steps:
  - send: {topic: /cmd, data: {data: start}}
  - expect: {topic: /state, within: 1.0, where: [{field: data, op: eq, value: RUNNING}]}
  - send: {topic: /cmd, data: {data: stop}}
  - expect: {topic: /state, within: 1.0, where: [{field: data, op: eq, value: IDLE}]}
```

```yaml
# センサー途絶
name: lidar_dropout
steps:
  - start: {id: scan, topic: /scan, stream: streams/scan.jsonl, rate_hz: 10, loop: true}
  - wait: 2.0
  - stop: scan
  - expect: {topic: /diagnostics, within: 1.0, where: [{field: status.0.level, op: eq, value: 2}]}
```

## 判定ルール
- **取りこぼし防止**: runner はシナリオ開始時に、シナリオ内で参照される全トピックを先に購読し、受信時刻付きでバッファする。各判定ステップは「そのステップ開始時刻以降」に受信したメッセージを評価する。heavy 型 ([map-and-traffic.md#traffic](map-and-traffic.md#traffic)) も、シナリオ中は参照トピックに限って購読する。
- `where` の op: `eq ne lt le gt ge range approx(tol) regex contains exists len_eq len_range`。field はドット区切り + 配列添字 (`detections.0.bbox.center.position.x`)。`len_*` は配列長 (例: 検出数)。
- 失敗時は「何が来て何が足りなかったか」を平易に出す (受信件数、最後に受信した値、条件ごとの不一致箇所)。参照トピックに publisher がいない、QoS が不一致、などの原因候補も併記する。
- CLI: `ros2 run roshanavi scenario run <file|dir> [--junit out.xml]` → 失敗時 exit 1。
- Python API (`roshanavi.scenario.run_scenario(path) -> Result`) を公開し、launch_pytest からも使える。

## UI での作り方: 記録モード (主軸)
YAML は保存・CI 用の形式であり、ユーザーは原則として手で書かない。

1. **記録開始**: 確認したい出力トピック (watch) を選び、記録を始める。
2. **入力操作がステップになる**: UI からの送信・開始・停止・bag 再生が、そのまま `send`/`start`/`stop`/`play` になり、操作の間隔は `wait` になる。
3. **出力をクリックして期待値にする**: watch トピックのタイムラインに流れたメッセージをクリックし、「これが来るはず」を選ぶと `expect` ができる。
   - フィールドは自動で選ぶ: スカラー値は `eq`、浮動小数は `approx`。`header.stamp` やカウンタのように毎回変わる値は既定で除外し、チェックボックスで調整できる。
   - `within` は実測の応答時間に余裕を持たせた値 (例: 実測 × 3、最低 0.5 秒) を既定にする。
4. **種類を変える**: 作った期待を `always`/`never`/`rate`/`throughput`/`latency` に切り替えられる (範囲選択した区間を `for` に使う)。
5. **保存して再実行**: 保存すると YAML になり、Scenarios タブと CLI から再実行できる。

## latency の対応づけモード
- `match: header.stamp` (既定): 出力が入力の stamp を引き継ぐノード向け。
- `match: order`: 受信順に対応づける近似。stamp を引き継がないノード向け。取りこぼしがあるとずれるため、`throughput` と併用を推奨し、結果に「近似」と表示する。
