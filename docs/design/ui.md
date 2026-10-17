# roshanavi — UI (フロントエンド)

タブ・ライブ通信マップ・右クリックメニュー・各パネルの設計と実装メモ。スクリーンショットは [../images](../images/)。

## フロントエンド (タブ構成)

タブ: **Graph** / **ノード一覧** / **Traffic** / **お試し送信** (旧 Inject) / **Launcher** / **録画** / **Scenarios** / **リソース**。右ペインに選択トピックの詳細 (統計・エコー・注入ショートカット)。
- Graph (**ライブ通信マップ**, [ui.md#ライブ通信マップ](ui.md#ライブ通信マップ-graph-タブ))
- Traffic: ソート可能な表 + 行内 uPlot スパークライン。停止トピック (last_seen > 3 s) を強調。
- Inject: トピック選択 → 型自動入力 → テンプレ YAML エディタ → mode 別フォーム → 開始。実行中ジョブ一覧と停止ボタン。
- **シナリオ** (Scenarios): プロジェクトとサンプルのシナリオの一覧 / 実行 / ステップ別の結果 / 編集 / 削除 / 記録モード ([ui.md#実装メモ (P6: シナリオ)](ui.md#実装メモ-p6-シナリオ))。
- Launcher ([ui.md#実装メモ (P3: Launcher)](ui.md#実装メモ-p3-launcher)): パッケージ選択 → 起動設定 → 起動対象の一覧・ログ・ビルド。
- **リソース**: この PC の CPU・メモリ・ディスク・ネットワーク・GPU、ROS ノード / roshanavi 自身 / その他の内訳、役割ごとのプロセスの表、外部との接続先 ([ui.md#実装メモ (リソース監視)](ui.md#実装メモ-リソース監視))。
- **チュートリアル**: ⚙ 設定の一覧と初回の案内から始まる、画面上のガイドツアー ([ui.md#実装メモ (アプリ内チュートリアル)](ui.md#実装メモ-アプリ内チュートリアル))。

## ライブ通信マップ (Graph タブ)
ノードとトピックがどうつながり、いまどこに通信が流れているかを、リアルタイムに一目で分かるようにする。

**レイアウト**
- Cytoscape + dagre で左→右のデータフロー配置にする (入力元 → 処理 → 出力先)。トポロジーが変化してもアニメーションで追従し、既存要素の位置は保つ。
- ノード=角丸、トピック=楕円。ノードは役割で色分けする: **自分のノード** (Launcher で起動) / **依存ノード** / **ダミーノード** / その他。

**通信の見せ方**
- エッジの太さ ∝ log(帯域)。エッジ上に `10.0 Hz · 1.2 MB/s` のラベルを付ける (ズームに応じて省略)。
- **流れのアニメーション**: publisher → トピック → subscriber の向きに粒が流れ、粒の頻度が Hz に比例する (上限あり)。1 Hz 以下の低頻度トピックは、受信のたびにエッジを一瞬光らせる。
- 状態の色分け: 通信中 / 停止 (`last_seen` > 3 s, 破線グレー) / 取りこぼしあり (`drop_ratio` > 0, 橙) / 非監視 (heavy 型, 点線)。
- ノードの縁取りの濃さ = そのノードの入出力帯域の合計。

**ROS 初心者向けの指摘 (診断)**
- **QoS 不一致**: reliability / durability が非互換で、つながっていない pub–sub を赤い破線で描き、理由を平易に表示する (例: 「送信側は BEST_EFFORT、受信側は RELIABLE のため届きません」)。
- **相手がいない**: publisher しかいない / subscriber しかいないトピックに印を付ける。
- **名前の取り違え候補**: 編集距離が近いトピック名 (`/cmd_vel` と `/cmdvel` など) で、片方に pub、片方に sub しかない場合に警告する。
- **型の不一致**: 同名トピックで型が異なる場合に警告する。

**操作**
- ノードやトピックをクリックすると、上流・下流の経路を強調し、それ以外を薄くする (フォーカスモード)。右ペインに詳細 (統計、エコー、注入、ログ) を出す。
- 名前フィルタ、`/rosout` 等の非表示トグル、一時停止 (スナップショットを固定して観察する)。

**計測の限界 (UI に明記する)**
- 帯域や Hz は、送信側は送信ノードごとの実測 (C++ 計測ノード, [measurement.md#C++ 計測ノード](measurement.md#c-計測ノード-roshanavi_probe-p46)。Python の経路ではトピック単位)。subscriber ごとに実際に届いた量は、外部からは測れない (理論値, [map-and-traffic.md#送受信ごとのトラフィック・遅いトピック](map-and-traffic.md#送受信ごとのトラフィック遅いトピック-p45b))。詳細計測モード ([measurement.md#詳細計測モード](measurement.md#詳細計測モード-トレース計測-p47)) を有効にすると、同じ PC のノードはトレースで受信・処理を実測する。
- 更新は 1 秒周期。流れのアニメーションは見た目の表現であり、1 粒 = 1 メッセージではない。

**バックエンドへの追加要件**
- `/ws/live` に、トピックごとの直近 1 秒の受信イベント数を含める (低頻度トピックを光らせるため)。
- グラフスナップショットに QoS 互換性の判定結果と、診断の警告リストを含める (判定はバックエンドで行い、テスト可能にする)。
- ノードの役割 (自分 / 依存 / ダミー) は、Launcher とダミーノードの管理情報から付与する。

## 実装メモ (P2)

**構成 (`web/`)**: Vite + React 19 + TypeScript (strict)。依存はすべて完全一致でピン留め (`package-lock.json`)。
- `src/tabs/registry.tsx`: タブ定義 `{id, label, keepMounted, render}`。Launcher / Scenarios は ここに追加する。Graph と Inject は非表示中もマウントしたまま (レイアウト・入力を保持)。
- `src/detail/DetailPane.tsx`: 右ペイン。選択 (topic / node) ごとにセクションを並べる (統計・エコー・注入ショートカット・監視切替)。ログや画像ビューアは後のフェーズで追加する。
- `src/i18n/messages.ts`: UI 文言の唯一の辞書 (既定は日本語)。英語は同じキーで `locales.en` を足せば切り替わる (欠けたキーは日本語にフォールバック)。
- 純粋ロジック (vitest): `graph/model.ts` (スナップショット → 要素、状態・太さの写像、フィルタ)、`graph/diff.ts` (差分パッチ)、`graph/focus.ts` (上流・下流)、`graph/particles.ts` (粒のシミュレーション)、`graph/diagnosticsText.ts` (診断の文章化)、`traffic/sort.ts`、`inject/buildRequest.ts`、`state/live.ts`、`api/reconnect.ts`、`lib/format.ts`。

**ライブ通信マップの決定事項**
- **差分更新**: 毎秒の要素リストを前回と比較し、追加・削除・data 更新だけを cytoscape に適用する。dagre レイアウトは **トポロジーが変わったときだけ** アニメーション付きで再実行する (統計の変化では位置は動かない)。新しい要素は隣接ノードの位置から生えるように置く。dagre は決定的なので、変化のない部分の位置はほぼ保たれる。**ドラッグした位置は固定 (ピン留め, #8)**: ユーザーがドラッグした頂点 (ノード・トピック) は `dragfree` で位置を記録し、以後の dagre レイアウトでは `transform` でその位置に戻す (他の頂点だけが動く)。一度消えて戻ってきた頂点にも効く。位置は **プロジェクトごと** に localStorage (`roshanavi.mapPins.v1:<プロジェクトのパス>`、最大 500 件、保存・読み込みは try/catch で、使えない環境ではそのページの間だけ有効) に保存し、再読み込みや再起動後も保つ。プロジェクトを切り替えると、そのプロジェクトのピンに差し替える。**空白の右クリック「整列し直す」はすべてのピンを外して** 最初から配置し直す。純ロジックは `graph/pins.ts`、プロジェクトの取得は `graph/useProjectKey.ts`。
- **流れの粒は canvas オーバーレイで描く**: cytoscape のスタイル (例: `line-dash-offset`) をフレームごとに変えると、そのたびに cytoscape がグラフ全体を再描画するため、200 要素 × 60 fps では重い。オーバーレイなら cytoscape の再描画はデータ更新時 (1 Hz) だけで、粒は色ごとに 1 本の Path2D でまとめて描く。エッジ端点 (モデル座標) はノード移動時だけ再計算してキャッシュし、描画時に pan/zoom で変換する。粒の頻度は `min(6, 1 + sqrt(hz - 1))` 個/秒、総数上限 1200。計測 (Playwright, headless Chromium, 180 要素 + 粒): 約 60 fps (`web/e2e/perf.spec.ts`)。
- **低頻度 (≤ 1 Hz)**: 連続放出せず、`recent_count > 0` の tick ごとにエッジを光らせて 1 粒流す (実際の受信に同期)。
- **状態**: 通信中 = 青実線 / 停止 (`last_seen` > 3 s) = 灰破線 / 取りこぼし (`drop_ratio` > 0) = 橙 / 非監視 = 灰点線 / QoS 不一致 = 赤破線 + 終端 T 字。QoS 不一致は受信側エッジ (topic → sub) に付け、ホバーで理由を表示する。粒は流さない。
- **太さ**: エッジ = `1.5 + 1.2·log10(1 + B/1000)` px (上限 10)、ノード縁取り = `1 + log10(1 + 入出力帯域合計/1000)`。
- **ラベル**: `10.0 Hz · 1.2 KB/s`。cytoscape の `min-zoomed-font-size` でズームアウト時に自動で省略する。
- **一時停止**: 表示中のスナップショットと粒を固定する。裏では受信を続け、再開時に最新へ追従する。
- **フォーカス**: クリックした要素から有向辺をたどった上流・下流以外を薄くする。エッジのクリックはそのトピックの選択として扱う。診断のクリックで対象トピックを選択・フォーカスする。
- **アクセシビリティ / E2E**: 地図の内容を視覚的に隠したリスト (`data-testid="graph-outline"`) としても出力する。

**エコー**: 右ペインでトピックを選ぶと、監視対象 (重い型でない) なら自動で `/ws/echo` を開始する。重い型は「エコーを開始」で明示的に開始する。

**配信とビルド**
- `npm run build` は `ros2_ws/src/roshanavi/roshanavi/static/` (git 管理外) に出力し、`setup.py` が package data としてインストールする → `ros2 run roshanavi server` が `/` で UI を配信する。
- Docker: `docker/Dockerfile` の第 1 段 (`node:24.14.0-bookworm-slim`) で `npm ci` + build し、成果物を `/opt/roshanavi/static` に焼き込む。`lab` はソースを bind mount するため package data に頼らず、`ROSHANAVI_STATIC_DIR` 環境変数 (main.py の `--static-dir` 既定値) で参照する。UI を変更したら `docker compose build lab`。

**実行方法**
```bash
# Docker で UI + デモ
docker compose up -d --build lab demo        # http://localhost:6871
# UI 開発 (ホットリロード; /api と /ws は :6871 にプロキシ)
cd web && npm ci && npm run dev              # http://localhost:5173
# テスト
cd web && npm test                           # vitest (純粋ロジック)
docker compose --profile test run --rm test  # 計測ノードの gtest + バックエンド pytest
# (ROSHANAVI_TEST_PROBE=auto を -e で渡すと、共通の lab fixture も計測ノードの経路で動く)
scripts/e2e.sh                               # Playwright を隔離スタックで一括実行 (下記)。スクリーンショットは docs/images/
```
**E2E の隔離**: `scripts/e2e.sh` は profile `e2e` の `lab-e2e` / `demo-e2e` / `e2e` を build → 起動 → 実行 → 後片付けまで 1 コマンドで行う (等価: `docker compose --profile e2e up --build --abort-on-container-exit --exit-code-from e2e lab-e2e demo-e2e e2e`。ただし後片付けと下記の検査はスクリプトだけ)。
- `lab-e2e` は利用中の `lab` と別の `ROS_DOMAIN_ID` (既定 77, `E2E_ROS_DOMAIN_ID` で変更)、`/data` は tmpfs (毎回空から `examples/demo_project/roshanavi.yaml` で初期化)。`./data` はマウントしない。ポートはホストに公開しない (`--allowed-host lab-e2e`)。healthcheck は `GET /api/health`。
- `e2e` ランナーは `lab-e2e` のネットワークを共有し `http://localhost:6871` で UI を開く (ブラウザのマイク / カメラ取り込みは secure context が必要で、`http://lab-e2e` では使えないため)。メディアテストの素材は `lab-e2e` の `/data/e2e` と共有する揮発ボリューム `e2e-media` に書く。
- スクリプトは前後で `lab` の `/data/roshanavi.yaml` の sha256 を比べ、変わっていたら失敗する。後片付けは e2e のサービスとボリュームだけを消す (`docker compose down` は使わない: `lab` / `demo` まで止まるため)。

## 実装メモ (P3: Launcher)
- **Launcher タブ** (`src/launcher/`): 左にパッケージ一覧 (検索、ワークスペースのパッケージを先頭、「ワークスペース」「システム」「未ビルド」「未 source」バッジ、ビルドボタン)、中央に起動設定フォーム・ビルド結果・起動対象のカード、右にログビューア。上部のプロジェクトバーに保存先、未保存バッジ、保存・読み直しボタン (P4.5a で自動保存と設定メニューに変更、[ui.md#実装メモ (P4.5a: デモ体験・ランチャー・地図の操作)](ui.md#実装メモ-p45a-デモ体験ランチャー地図の操作))。
  - 起動設定: ノード名、名前空間、パラメータ (名前・値の行。`true`/`false` と数値はその型)、リマップ、パラメータファイル、追加引数 / launch 引数、「開発中 (自分のノード)」、自動起動、自動再起動。クライアント側でもサーバーと同じ規則で先に検査し、平易な文で示す (`launcher/form.ts`)。
  - カード: 状態チップ、起動コマンド、稼働時間・再起動回数、対応づいたノードと「確実 / 推定」バッジ (説明はツールチップ)、起動・停止・再起動・ログ・編集・削除。
  - ログビューア (`/ws/logs/{id}`): 最新に追従、stderr と `[ERROR]`/`error:` 行を強調、検索、エラー・警告だけ表示、クリア。表示は最大 5000 行 (`launcher/logs.ts`)。
  - ビルド結果: 成功 / 失敗、最初のエラー行、再起動したノード、未 source の案内。
- **注入タブのファイル一覧**: ファイルを使う送り方 (stream / bag / media) を選ぶと `/api/files` を取得し、モード切替・ウィンドウのフォーカス復帰・タブが見える状態に戻ったとき・「ファイル一覧を更新」ボタンで取り直す (録画やコピーで後から増えたファイルが、ページの再読み込み無しで選べる)。
- **注入タブ**: 実行中ジョブに「常駐ノードにする」(ノード名を入力、既定 `dummy_<トピック末尾>`)、常駐ダミーノードの一覧 (起動・停止・自動起動・ログ・削除) と launch ファイルへの書き出し。
- **右ペイン (ノード)**: 起動対象、プロセスの状態と pid、対応づけ (確実 / 推定と理由)、稼働時間、再起動ボタン、「ログを開く」(Launcher タブへ)。
- 地図の役割色は P2 の凡例どおり (自分 = 緑、依存 = シアン、ダミー = マゼンタ、その他 = グレー)。注入ジョブの仮想ノードはジョブ ID 付きのラベル、恒久ダミーはノード名で表示する。
- スクリーンショット: [`launcher.png`](../images/launcher.png), [`graph-roles.png`](../images/graph-roles.png), [`graph-node-launcher.png`](../images/graph-node-launcher.png) (`e2e/launcher.spec.ts`)。
- **地図からノードを操作** (`graph/nodeControl.ts` 純関数, `NodeMenu.tsx`, `detail/NodeControls.tsx`): 地図のノードの右クリックメニューと右ペインに 停止 / 再起動 (止まっている起動対象には 起動)。新しい API は作らず既存の `POST /api/targets/{id}/start|stop|restart` と `DELETE /api/inject/{id}` を使う。
  - 対象は roshanavi が起動したものだけ: Launcher の起動対象 (自分 / 依存 / 恒久ダミー) と注入ジョブ。その他のノードはボタンを無効にし、理由 (「roshanavi が起動したノードではないため停止できません…」) を出す。外部のプロセスにはシグナルを送らない。
  - launch ファイルや 1 プロセスに複数ノードがある起動対象 (composable container など) は、対応づけ ([launcher.md#Launcher](launcher.md#launcher-p3)) で分かっている全ノードを確認ダイアログに列挙してから止める。
  - 右クリック (cytoscape `cxttap`) だけを使うので、左クリックの選択とドラッグでの移動はそのまま。メニューは矢印キーで移動、Escape / Tab で閉じる。キーボードだけの操作は右ペインのボタンで行える。

## 実装メモ (P4: メディア・ブラウザ入力・録画)
- タブ: **録画** を追加 (Graph / Traffic / Inject / Launcher / 録画)。
- **注入タブ**: 送り方に「メディアファイル (画像・動画・音声)」。型の欄は空でもよく、トピックの型の自動判定結果 (または「まだ誰も使っていない」「この型は作れない → bag を使う」) を表示する。ファイルの種類 (画像 / フォルダ / 動画 / 音声) に応じて、周期・fps、区間、リサイズ、ピクセル形式・圧縮形式、frame_id、CameraInfo (送り先を表示) とキャリブレーション、サンプルレート・チャンネル・チャンク長 (何 ms ごとかを表示)、揺らぎ・欠落、AudioInfo を出し分ける (`media/MediaFields.tsx`, 純ロジック `media/buildMediaRequest.ts`)。
- **ブラウザ入力パネル** (注入タブの右列、`media/CapturePanel.tsx`): マイク / カメラ、デバイス選択、送信先トピック、型 (自動判定 / 対応型から選択)、カメラは解像度・fps とプレビュー、マイクはサンプルレートと入力レベルメーター (RMS → dBFS、-60 dB を 0 %、ゆっくり下がる)。送信数・間引き数と、stamp の遅れの注意書き。AudioWorklet のコードは Blob URL で読み込む (追加のビルド設定なし)。送信の詰まり (bufferedAmount > 2 MB) はフレームを飛ばす。純ロジック: `media/pcm.ts` (float→int16、ダウンミックス、チャンク化)、`media/level.ts`、`media/captureRequest.ts`。
- **右ペイン (トピック)**: 画像の型なら画像ビューア、音声の型なら波形 (直近 2 秒、canvas に min/max) と再生 (WebAudio で隙間なく予約再生)。開いている間だけサーバーが購読する。音声の型ではエコーは自動で始めない (配列が大きいため)。純ロジック: `media/waveform.ts`。
- **録画タブ** (`recordings/`): トピックのチェックリスト、プリセット「今の注入・ブラウザ入力のトピック」(実行中のジョブのトピック + CameraInfo / AudioInfo) と「自分のノードの出力」(役割 mine のノードの publish 先、内部トピックを除く) (`recordings/presets.ts`)、名前、録画開始 / 停止、経過時間と空き容量の警告。一覧はサイズ・長さ・メッセージ数・トピックごとの件数、再生 (bag モードのジョブを開始)、削除 (確認ダイアログ)。
- i18n: `i18n/messagesMedia.ts` (地図の操作は `i18n/messagesMap.ts`) を `ja` に合流させる。
- スクリーンショット: [`inject-media.png`](../images/inject-media.png), [`capture-panel.png`](../images/capture-panel.png), [`image-viewer.png`](../images/image-viewer.png), [`audio-waveform.png`](../images/audio-waveform.png), [`recordings.png`](../images/recordings.png) (`e2e/media.spec.ts`。Chromium の `--use-fake-device-for-media-stream --use-fake-ui-for-media-stream` を使う。動画の素材はテスト中にブラウザの MediaRecorder で作り `data/e2e/` に書く)。

## 実装メモ (P4.5a: デモ体験・ランチャー・地図の操作)
**デモの基本の流れ**: (1) 「＋ 入力ノードを作る」で入力 (= 新しいトピック) を作る → (2) ランチャーでサンプル / デモ用ノードを起動 → (3) 地図で流れと出力の中身を見る → (P6) 操作を記録してシナリオにする。

**入力ノード (`input/`)**: 地図のツールバー・お試し送信タブ・空白の右クリック「ここにトピックを追加」・トピックの右クリック「入力ノードを作る」から、同じダイアログ (`CreateInputDialog`) を開く。トピック名 (先頭の `/` は補う。新しい名前なら「新しいトピックです」と案内)、型 (既存トピックなら自動)、ノード名 (既定 `dummy_<末尾>`)、中身 (文字列 / 式 / 画像・動画・音声ファイル / データファイル JSONL・CSV)、頻度、次回も自動起動 を選び、`POST /api/dummies?start=true` で **1 ステップで常駐ダミーノードを作って起動する** (注入してから常駐化する 2 段階は不要。注入ジョブは「お試し送信」として残す)。ROS 2 のトピックは publish された時点で存在するので、新しい名前を入れればトピックも地図に現れる。編集 (「内容・レートの変更」) は同じダイアログで PUT → 再起動。純ロジック `input/inputForm.ts`。
- 右ペインのエコーは、トピックがグラフに現れてから始める (作成直後の `unknown topic` を避ける)。

**右クリックメニュー (`graph/menuModel.ts` 純関数, `MapMenu.tsx`, `useMenuActions.ts`)**
| 対象 | メニュー |
|---|---|
| 自分 / 依存ノード | 停止・再起動 (止まっていれば起動)、ログを見る、起動設定を編集、ビルドして再起動 (ワークスペースのパッケージのみ)、パラメータを見る・変更する、入出力だけ表示 |
| 常駐ダミー (入力ノード) | 停止・再起動、一時停止 / 再開 (`paused` パラメータの現在値を取得して、合う方だけを出す。取得できない間は両方)、内容・レートの変更、launch に書き出し、ログ、パラメータ、入出力だけ表示 |
| 注入ジョブ (お試し送信) | 停止、一時停止 / 再開 (periodic・stream・media のみ)、内容の変更と書き出しは無効 (理由を表示) |
| 関数・クラスノード | 停止・再起動、(クラスのみ) 操作メソッドごとの「<メソッド> を呼ぶ」、設定の変更 (関数 / クラス)、launch に書き出し、ログ、パラメータ、入出力だけ表示 |
| 外部ノード | 停止は無効 (理由を表示)、パラメータを見る (閲覧のみ。変更は確認ダイアログの後)、入出力だけ表示、詳細 (送受信トピックと QoS) |
| トピック | 中身を見る、お試し送信、入力ノードを作る、録画 (録画タブで選択済み)、監視 ON/OFF、型の定義を見る、上流・下流だけ表示 |
| エッジ | QoS の詳細、届かない理由 (両側の QoS の表と、診断・送信者なし・最近流れていない の平易な説明) |
| 空白 | ここにトピックを追加、ノードを起動 (ランチャーの追加画面へ)、整列し直す、全体を表示 |
- 無効な項目は理由をツールチップと小さな文で示す。停止・再起動は従来の確認ダイアログ (`useNodeControl`) を通る。「入出力だけ表示」「上流・下流だけ表示」は地図を絞り込み (`graph/isolate.ts`)、ツールバーの「すべて表示」で戻る。
- ダイアログは `AppState.dialog` + `DialogHost` で 1 つずつ出す (入力ノード / パラメータ / 型の定義 / エッジ / launch 書き出し)。

**ノードの入出力 (`detail/NodeIO.tsx`, 純関数 `detail/nodeIO.ts`)**: ノードをクリックすると右ペインに「受信しているデータ」「送信しているデータ」をトピックごとに出す (型・Hz・最新メッセージ。画像はビューア、音声は波形)。表示しているのは **トピックに流れているデータ** であり、そのノードが受け取ったとは限らないことを明記する。QoS 不一致 (診断の subscriber がこのノード) は「このノードには届いていません」。各トピックは折りたたみで、開いている間だけ購読する。最初の 3 つ (heavy 型と届かないものを除く) を自動で開く。heavy 型 (Image など) は開いたときだけ表示する。`/rosout` などの内部トピックは出さない。

**ランチャー**
- 初回の案内 (`FirstRunGuide`): 起動リストに run / launch が無ければ 3 ステップの説明と「試しに talker を起動してみる」(demo_nodes_cpp の talker を名前付き・自分のノードとして登録して起動)。
- 「＋ ノードを起動」→ 一覧から選ぶ →「起動」。ノード名・名前空間・パラメータ・リマップ・パラメータファイル・引数・役割・自動起動は「詳細設定」に畳む。起動したものは自動で起動リストに残り、プロジェクトに自動保存される ([launcher.md#プロジェクトファイル](launcher.md#プロジェクトファイル-p3))。「起動対象」の表記は「起動リスト」に変えた。
- 一覧は既定でワークスペースのパッケージとデモ用 (demo_nodes_cpp / demo_nodes_py / roshanavi_examples) だけ。「ROS 標準パッケージも表示」で全件。ワークスペースに自分のパッケージが無い (roshanavi 以外が無い) ときは、マウント・設定方法を案内する。
- 用語のツールチップ (`lib/Term.tsx`, `term.*`): launch ファイル、リマップ、名前空間、パラメータ、パラメータファイル、ノード、トピック、型、ワークスペース、QoS、パッケージ、実行ファイル、Hz。

**更新タイミングの表示 (`timing/`)**
- 計算期間のセレクタ (1 / 5 / 10 秒、地図とトラフィックで共有) は `/ws/live?window=` を張り直す。選択肢の文言自体が「直近 5 秒の平均」。止まったトピックはバックエンドで即 0 (`stale`)、地図のエッジも停止表示になる。
- 「最終更新 HH:MM:SS (N 秒前)」を地図とトラフィックのツールバーに常に出す。最後の `/ws/live` フレームの受信時刻で、5 秒を超えると警告色 (切断・サーバーの停止が分かる)。各行の「最終受信」(last_seen) とは別物であることをツールチップで説明する。
- Hz の計測方法: 「(送信側)」は誤読されるため既定では出さず、受信時刻ベースに落ちたときだけ「(受信時刻で概算)」。詳細は ⓘ のツールチップ。
- i18n: `i18n/messagesUx.ts`, `messagesUx2.ts`。スクリーンショット: [`menu-blank.png`](../images/menu-blank.png), [`menu-node.png`](../images/menu-node.png), [`menu-topic.png`](../images/menu-topic.png), [`menu-input-node.png`](../images/menu-input-node.png), [`create-input-dialog.png`](../images/create-input-dialog.png), [`params-dialog.png`](../images/params-dialog.png), [`node-io-pane.png`](../images/node-io-pane.png), [`launcher-guide.png`](../images/launcher-guide.png) (`e2e/ux.spec.ts`)。E2E は lab を変更するテストがあるため `workers: 1`。

## 実装メモ (P4.5b: ノード一覧・lifecycle・launch の取り込み)
**ノード一覧タブ** (`nodelist/`): リストとチェックボックスで、ノードを一括で ON/OFF する。`GET /api/node-list` をタブ表示中だけ 2 秒ごとに取る。
- 列: チェックボックス、ノード名、役割 (自分 / 依存 / ダミー / 外部)、状態 (lifecycle ノードは状態と「状態を変える」)、起動元、PID、対応づけ (確実 / 推定 / ノード未確認)。(CPU・メモリはリソースタブと地図のバッジで見る)
- 検索 (名前・パッケージ・実行ファイル・launch ファイル・取り込み元、空白区切りで AND)、役割と状態 (動いている / 止まっている / 問題あり) での絞り込み、全選択 (表示中の操作できる行だけ。一部選択は indeterminate)、グループ単位の選択。純ロジック `nodelist/model.ts`。
- グループ: launch の起動設定と composable container などのプロセスは見出し行の下にまとめ、「この N 個のノードはまとめて止まります」と書く。
- 一括の起動・停止・再起動 (`nodelist/bulk.ts`): 起動設定ごとに 1 回だけ既存の `POST /api/targets/{id}/start|stop|restart` を呼ぶ。止める起動設定の全ノードを地図と同じ規則 (`graph/nodeControl.affectedNodes`) で求め、**選択していないのに一緒に止まるノード** も確認ダイアログに列挙する。状態が合わないもの (止まっているものの停止など) は「対象外」として理由を出す。
- 外部ノード: チェックボックスを無効にし、理由をツールチップと行内の小さな文で示す。外部ノードがあれば一覧の上に「launch ファイルを取り込むと 1 つずつ操作できる」案内と取り込みボタンを出す。ただし **lifecycle ノード** は外部でも選べ、起動 = active へ (必要なら configure → activate)、停止 = deactivate (プロセスは止めない)。再起動は対象外。外部の lifecycle ノードを含むと確認ダイアログに注意を足し、`allow_external` を付ける。
- キーボード: チェックボックス・ボタンは通常のフォーカス順。表の中は ↑ / ↓ で同じ列の次の行へ、Space で選択。表に説明の caption (読み上げ用)。
- **lifecycle ダイアログ** (`lifecycle/LifecycleDialog.tsx`): 現在の状態と、いまできる操作だけを「設定する (configure)」「有効にする (activate)」「無効にする (deactivate)」「設定を破棄する (cleanup)」として出し、平易な説明付きの確認の後に実行する。ノード一覧、地図の右クリック (lifecycle ノードだけに「lifecycle の状態を変える」)、右ペイン (`detail/NodeLifecycle.tsx`、3 秒ごとに状態を更新) から開く。
- **launch の取り込みダイアログ** (`launchImport/`): (1) パッケージ + launch ファイル、またはワークスペースからの相対パスを選び「解析する」、(2) 宣言された launch 引数の欄 (既定値入り、必須は赤) を直して「この引数で解析し直す」、(3) 取り込まれるノード (名前空間込みの名前、起動リストの ID、パラメータ・リマップ・引数の要約、警告、取り込めない理由・重複) をチェックで選ぶ、分解できない部分と理由、条件で起動されない部分、(4) 取り込み方 (ノードごと / launch 全体) と役割を選んで「取り込む」。純ロジック `launchImport/importModel.ts`。解析で Python を実行することと対象ファイルの制限をダイアログに書く。
- 一時停止中は「最終更新」バッジを警告色にせず「一時停止中 (HH:MM:SS の表示)」にする。Hz は `rate_note` に応じて「0.50 Hz (直近 10 秒で計算)」/「— (1 秒窓では測定不可)」(`timing/timing.ts rateText`)。
- i18n: `i18n/messagesNodes.ts`, `messagesImport.ts`, `messagesTraffic.ts`。スクリーンショット: [`node-list.png`](../images/node-list.png), [`lifecycle.png`](../images/lifecycle.png), [`launch-import-preview.png`](../images/launch-import-preview.png) (`e2e/nodes.spec.ts`)。

## トラフィックの送受信ごとの表示 (P4.5b)
- トラフィックタブの各トピック行は ▸ で展開でき (既定は折りたたみ、「すべて展開」で全部)、送信ノードごとの行 (Hz・帯域・根拠: 実測 / 推定 / 設定値 / 分けられない、`publishers[]`) と受信ノードごとの行 (理論値。ⓘ に「受信側のノードの中で数えた値ではない」。QoS が合わなければ「届いていません」、`subscribers[]`) を出す。
- 「トピック別 / ノード別」の切り替え: ノード別は同じ行をノードごとにまとめ (送信 → 受信、トピック順)、「このノードが何を送って何を受けているか」を見る。純ロジック `traffic/endpoints.ts`。
- 地図の受信側エッジの値も同じ理論値を使う (一部の送信者だけ QoS が合うときに表と地図がずれない)。C++ 計測ノード ([measurement.md#C++ 計測ノード](measurement.md#c-計測ノード-roshanavi_probe-p46)) が動いていれば送信側は送信ノードごとの実測 (`実測` バッジ、ⓘ に「このノードが送った分だけ数えた値」)。詳細計測モード ([measurement.md#詳細計測モード](measurement.md#詳細計測モード-トレース計測-p47)) では、トレースが測れた受信行が `basis: measured` になり、バッジは `実測(トレース)`、行に「受信 / 処理 / 処理時間 (平均 / p95 / 最大)」と、追いついていなければ「受け取っていますが処理が追いついていません」を出す。スクリーンショット: `traffic-tracing.png` (`e2e/tracing.spec.ts`)。
- Hz の後ろの「(受信時刻で概算)」は、止まったトピック (hz 0 / `stale`) には付けない (`timing.hzBasisNote`)。
- ツールバーに計測の経路 (C++ 計測ノードの CPU、または Python で測っている理由) を出す (`data-testid="traffic-measurement"`)。スクリーンショット: `traffic-endpoints.png`, `traffic-by-node.png` (`e2e/smoke.spec.ts`)。

## 実装メモ (P5: 変換ノードの編集画面・プロジェクトの切り替え)
- 「＋ 変換ノードを作る」(地図のツールバーと注入タブ、「＋ 入力ノードを作る」の隣)、トピックの右クリック「このトピックを受けて変換するノードを作る」(入力にそのトピックと型が入る)、変換ノードの右クリック「変換の内容を変更」「launch に書き出し」。役割 `transform` のメニューは起動・停止・再起動・ログ・パラメータ・I/O だけを見る (一時停止とビルドは無い)。
- 編集画面 (`transform/CreateTransformDialog.tsx`): ノード名、入力 (トピック・型・式での名前。「＋ 入力を足す」で最大 8、複数なら「送るタイミング」)、変換のしかた (式で作る / そのまま中継。大きい型は中継だけで理由を出す)、出力トピックと型、出力メッセージ (YAML。出力の型のテンプレートから作り、入力に同じフィールドがあれば `${msg.<path>}` で埋める = 最初は「そのまま写す」対応づけ。YAML を触った後は上書きしない)、送る条件、**プレビュー**、遅延・間引き・取りこぼし、自動起動。
- プレビュー (`TransformPreview.tsx`): 左に入力の最新メッセージ (`/ws/echo` を入力ごとに購読、`useLatestMessages.ts`)、右にサーバーの試算 (`useTransformPreview.ts`、300 ms のデバウンス)。左はエコーの表示用の値 (長い配列は 32 個まで)、試算は切り詰めない値で計算する (`useFullSamples.ts`: 切り詰めのあるトピックだけ `GET /api/echo/<topic>/sample` を 1 秒ごとに引く。サイズの上限を超えたら切り詰めた値のままで、出力の下に注意書き `transform-preview-truncated` を出す。判定は `sampleTruncation.ts`)。届いていない入力は「型の既定値で計算しています」。式のエラーは出力のフィールドごとに平易な日本語で出す (`previewText.ts` がエラーの `code` と `params` を訳す。知らない code はサーバーの英文を添える)。フォームの段階で作れない (トピック名が不正など) ときはその理由を出す。純ロジック `transformForm.ts` (既定値・仕様の組み立てと検査・編集時の復元・入力を増減したときの別名の振り直し)。
- ⚙ 設定メニュー (ランチャーのプロジェクト行) の「プロジェクトを切り替える」(`transform/ProjectsDialog.tsx`): サンプルと保存済みのプロジェクトを並べ、確認 (いま動いているものを止める旨) の後に開く。サンプルにはコピー先のパスを示す。
- 画面の保護: `lib/ErrorBoundary.tsx` をアプリ全体・各タブ・地図・右ペイン・ダイアログに置き、描画中の例外は日本語の「エラーが起きました」パネル (エラー内容・再読み込み・知らせてほしい旨) に置き換わる。1 か所の不具合で全画面が真っ黒にならない。`t()` は存在しないキーでも例外を投げずキーを表示する (原因: `detail.role.transform` が未定義で変換ノードを選ぶと全画面が消えた。回帰: `e2e/transform-crash.spec.ts`、`i18n.test.ts`)。
- i18n: `i18n/messagesTransform.ts`。スタイル: `styles-transform.css`。スクリーンショット: [`transform-editor.png`](../images/transform-editor.png) (`e2e/transform.spec.ts`)、[`perception-demo-map.png`](../images/perception-demo-map.png) (`e2e/perception.spec.ts`)。

## 実装メモ (P5.5: データの種類・詳細設定モード・関数ノード・クラスノード)
- `datakind/DataKindField.tsx`: 入力ノードの作成画面、変換ノードの入力と出力、お試し送信、関数ノードの入力と出力で共通。既存のトピック (地図のトピックに型がある) なら検出結果だけを出し (`<id>-detected`)、新しいトピックなら種類の選択 (`<id>-kind`)。詳細設定モードでは ROS の型の検索 (`<id>-raw-search`) とグループ付きの一覧 (`<id>-raw-type`、`optgroup` = よく使う型 / ワークスペースの独自型 / パッケージ名)。純ロジックは `datakind/kinds.ts` (表示・検索・既存の型 → 種類)、カタログは `useDataKinds.ts` (1 ページ 1 回取得)。
- 画面右上の ⚙ 設定 (`datakind/SettingsMenu.tsx`) に「詳細設定モード」。`advancedMode.ts` が `localStorage` を try/catch で読み書きし、同じページの全ダイアログに即時に反映する。
- 関数ノード: 地図のツールバー「＋ 関数・クラスノードを作る」(`function/CreateFunctionDialog.tsx`。先頭の「作るもの」で 関数 / クラス を選ぶ。関数は `function/FunctionMode.tsx`)。モジュール (ワークスペースの Python パッケージ) → 関数 (シグネチャ付き。ファイル:行と docstring を表示) → 呼び出し方 (引数の数から推す: 0 → 周期、1 → 受信ごと、必須 2 以上 → 複数入力) → 入力 (引数ごとに トピック + データの種類。注釈から種類を推す) → 出力 (戻り値の注釈から種類を推す)。純ロジック `function/functionForm.ts`。編集時 (地図の右クリック「関数ノードの設定を変更」) は動作状況 (`FunctionStatusPanel.tsx`: 状態・数・最後のエラーと場所) と「ROS ノードのコードとして書き出す」。右ペインのノードの「起動」欄にも同じ動作状況を出す。
- クラスノード (#43、`function/ClassMode.tsx`): 「作るもの」で「クラス」→ モジュール → クラス (`__init__` のシグネチャ付き。ファイル:行を表示) → ノード名 → **初期化の設定** (`__init__` の引数 = ROS パラメータ。型ヒントのある引数ごとに既定値入りの入力欄。値は種類 (整数・小数・true/false・数値の並び・JSON・文字列) で検査し、既定値と同じなら保存しない。`on_param_change` があるかで「変えると状態が残る / 作り直す」を説明) → **メソッドの使い方** (公開メソッドごとに 使わない / トピックにつなぐ / 操作メソッド (引数なしのものだけ)。「トピックにつなぐ」は呼び出し方 (受信ごと・周期・複数入力) と入力・出力 (関数ノードと同じデータの種類の選択) と「dict を返し、キーごとに別のトピックへ送る」)。最初に、引数のあるメソッド 1 つを「つなぐ」、引数のないメソッドを「操作メソッド」に仮決めする (`classForm.ts applyClass`)。出力トピックの仮の名前はノード名に追従する (利用者が書き換えた分は動かさない)。純ロジックは `function/classForm.ts` と `ClassNodeFields.tsx` (部品)。編集 (右クリック「クラスノードの設定を変更」) では `ClassStatusPanel.tsx` が動作状況 (状態・パラメータの現在値・数・最後のエラーと場所・**「状態をリセットしました」の通知**・操作メソッドごとの「<メソッド> を呼ぶ」ボタンと最後の呼び出し) と「ROS ノードのコードとして書き出す」(「ライフサイクルノードとして書き出す」チェック) を出す。右ペインのノードの「起動」欄にも同じ動作状況とボタンを出す。
- 役割の表示: クラスノードは関数ノードと同じ役割 `function` (同じ色。ターゲットの種類は `class`)。凡例「関数・クラスノード」、ノード一覧の役割「関数・クラス」(絞り込みも)、由来「roshanavi クラスノード (→ トピック)」。右クリックメニューは、動いている間「<メソッド> を呼ぶ」(操作メソッドごと。止まっていれば無効で理由を出す) / クラスノードの設定を変更 / launch に書き出し / ログ / パラメータ / 入出力だけ表示。「<メソッド> を呼ぶ」は `POST /api/classes/{id}/call`。
- シナリオの編集画面・記録モード: ステップ `call` (ノード・メソッド) を編集でき、記録モード中にボタンを押すと `call` ステップが記録される (`scenarios/editSteps.ts`、`record.ts`)。
- ノード一覧 ([ui.md#実装メモ (P4.5b: ノード一覧・lifecycle・launch の取り込み)](ui.md#実装メモ-p45b-ノード一覧lifecyclelaunch-の取り込み)) の行と一括操作の計画は、`GET /api/node-list` の同じ応答 (`rows` と `targets`) から作る (`nodelist/bulk.ts planFromSnapshot`)。以前は行が 2 秒ごとのポーリング、計画が WebSocket の `live.targets` で、停止直後に一括起動すると計画が空になることがあった (issue #1)。
- i18n: `i18n/messagesKinds.ts`、`i18n/messagesFunction.ts`、`i18n/messagesClass.ts`。スタイル: `styles-function.css`。スクリーンショット: [`data-kind-picker.png`](../images/data-kind-picker.png) (`e2e/datakind.spec.ts`)、[`function-dialog.png`](../images/function-dialog.png) (`e2e/function.spec.ts`)、[`class-node-dialog.png`](../images/class-node-dialog.png)・[`class-node-pane.png`](../images/class-node-pane.png) (`e2e/class.spec.ts`)。

## 実装メモ (P6: シナリオ)
仕様と判定のルールは [scenarios.md](scenarios.md)。
- **シナリオ** タブ (`scenarios/ScenariosTab.tsx`、`keepMounted`: 記録中にほかのタブへ行っても期待を失わない。`fullWidth`: このタブでは右ペインを出さない)。左に一覧 (このプロジェクトのシナリオ・サンプル。最後の結果のバッジ、実行・編集・削除 (確認ダイアログ)。サンプルは「コピーして編集」)、右に結果・編集・記録の画面。
- 結果 (`RunResultView.tsx`): 全体の成否と要約、セットアップ・ガード・ステップごとに ✔ / ✘ / − / ■、失敗の説明、「原因の候補:」、`近似` バッジ (`match: order`)、「くわしい数値」(受信件数・最後に届いた値・Hz・比・p50/p95 など)。実行中は `/ws/scenarios` で進み具合が更新され、「中止」できる。
- 編集 (`ScenarioEditor.tsx`): ステップのフォーム (トピック・秒数・しきい値・`where` の条件 (フィールド / 比べ方 / 値 / 許す差)・送る値、並べ替え・削除・追加)。開始・停止・再生の細かい設定とセットアップ・ガードは、詳細設定モードの YAML (検査は保存前に `POST /api/scenarios/validate`、誤りは行番号付き) で変える。純ロジック `editSteps.ts`。
- 記録モード (`RecordView.tsx`、`FieldPicker.tsx`、純ロジック `record.ts`): 見張るトピックを選んで開始 → 上部に「● シナリオを記録中」のバッジ (`RecordingBadge`、クリックで記録の画面へ) → ほかのタブの操作とメッセージが時刻付きのタイムラインに並ぶ (操作は青い行) → メッセージをクリックして「これが来るはず」(フィールドのチェックボックス・値・何秒以内) / Shift+クリックで区間を選んで「ずっと条件どおり・来ないはず・周期・件数の比・処理時間」→ 期待のカード (種類・数値を変えられる) → 「できるステップ」の一覧を見ながら名前を付けて保存。記録のタイムラインと状態は `ScenarioLiveProvider` (`/ws/scenarios`) が持つ。
- i18n: `i18n/messagesScenario.ts`。スタイル: `styles-scenario.css`。スクリーンショット: [`scenario-record.png`](../images/scenario-record.png)、[`scenario-result.png`](../images/scenario-result.png) (`e2e/scenario.spec.ts`)。

## 実装メモ (リソース監視)
仕様は [resources.md](resources.md)。
- **地図のバッジ** (`graph/model.ts` の `buildElements(..., resources)`): ノードのラベルの 2 行目に `CPU 12% · 45 MB` (推定なら「(推定)」)。`load` (none / low / mid / high、1 コアの 40% / 80%) と `leak` をデータに持ち、`style.ts` が光 (underlay) の色にする。凡例に「CPU やや高め / 高い」。2 行目が現れたり消えたりしたときは配置をやり直し (`diff.ts`)、dagre の配置はラベルの大きさを含める (`nodeDimensionsIncludeLabels`)。
- **診断パネル**: `/ws/live` の `resources.diagnostics` を地図の診断と並べる (`diagnosticsText.ts` が文を作る。リークはノードを、UDP はトピックを選ぶ)。
- **右ペイン** (`detail/NodeResources.tsx`): ノードを選ぶと「リソース」の節 (確実 / 推定 / n ノードで共有 / 起動設定全体のバッジ、CPU・RSS・USS・増え方・I/O・スレッド・ファイル・GPU メモリ、5 分のスパークライン、接続先)。`GET /api/resources/history?node=` を 2 秒ごと。
- **リソースタブ** (`resources/ResourcesTab.tsx`、`fullWidth`、開いている間だけ `/ws/resources`): 「この PC だけ」の注記と一覧の範囲 (自分のユーザー / root ならコンテナ全体)、PC 全体のカード (`HostOverview.tsx`)、内訳の帯 (`ProcessTable.tsx` の `BreakdownView`)、プロセスの表 (ROS ノード / roshanavi 自身 / その他。`ros2 run` のラッパーは薄く。ノード名で地図へ)、接続先とタイムライン (`ConnectionsView.tsx`、この PC 内の接続は既定で隠す)、計測そのものの負荷。純ロジック `resources/model.ts`。
- シナリオのステップ `resources` / `mem_growth` の表示と編集 (ノード名と上限の欄) は `editSteps.ts`。
- i18n: `i18n/messagesResources.ts`。スタイル: `styles-resources.css`。スクリーンショット: [`resources-tab.png`](../images/resources-tab.png)、[`resources-map.png`](../images/resources-map.png)、[`resources-scenario.png`](../images/resources-scenario.png) (`e2e/resources.spec.ts`)。

## 実装メモ (アプリ内チュートリアル)
ROS を知らない人の最初の一歩のために、画面の一部を強調して吹き出しで「ここを押してください」と案内する (Issue #41)。詳しい説明は文書へ誘導する (オフラインでは GitHub の文書に届かないため、文書名はリポジトリ内のパスで短く示すだけ)。

**ライブラリ**: [driver.js](https://driverjs.com/) 1.8.0 (MIT)。選定の理由とライセンスの確認は [dependencies.md](../project/dependencies.md)。ライブラリは「切り抜いて吹き出しを置く」ところだけを担当し、進行は自前のエンジンが決める。吹き出しの中身は DOM ノード (`textContent`) で組み、`innerHTML` は使わない (文言中の `` `code` `` だけコード表示にする `richText.ts`)。

**構成** (`web/src/tour/`)
- `types.ts` / `engine.ts` (純関数。vitest の対象): ツアーは**データ**として書く (`tours/*.ts`)。1 手順は `{id, kind, target, tab, side, done}`。
  - `kind: 'show'` は「次へ」で進む。`kind: 'do'` は `done(ctx)` が真になったら**自分で**次へ進む (ユーザーが先に操作して条件を満たしていれば、続く手順も一気に進む)。最後の手順はユーザーが閉じる。条件が例外を投げても「まだ」として扱う (壊れたツアーでアプリを壊さない)。
  - `ctx` は読み取り専用: アプリの状態 (タブ・選択・開いているダイアログ)、ライブのデータ (`/ws/live` のグラフ・ターゲット、`/ws/scenarios` の記録と実行)、画面 (表示中の `data-tour` 要素の値・チェック・属性)。タイマー (250 ms) で見直す: 入力欄の値などは変化を通知しないため。
  - `target`: `data-tour` の名前 (`'map'`)、`[` を含む CSS セレクタ、または `ctx` から作る関数。省略すると画面中央。
  - 文言は i18n 辞書 (`i18n/messagesTour.ts`): `tour.<ツアー>.<手順>.title|body|hint`。`hint` は任意で、「やる」手順の下に小さく出る。
- `TourProvider.tsx`: 進行中のツアー (`RunState`) と操作 (`start / next / back / pause / resume / quit / finish`)。別のタブの手順に入ると**タブを自動で切り替える**。Esc は中断 (ダイアログが開いていれば先にダイアログが閉じる)。
- `TourOverlay.tsx`: driver.js の描画、初回の案内カード、中断中のピル、エラー表示。`ErrorBoundary scope="tour"` の中に置く (壊れてもアプリは真っ白にならず、右下に小さなエラー表示が出る)。設定の一覧 (`TourSettings`)・ⓘ ヘルプ (`TourHelp`) も同じ境界で包む。
- `progress.ts`: 進み具合をブラウザ (`localStorage` の `roshanavi.tour.v1`) に記憶する。読み書きは `try/catch` で、プライベートウィンドウでも動く (記憶しないだけ)。形式が壊れていれば空として扱う。
- `fixtures.ts`: ツアーが API で作るものと片づけ。作るものの id は `tour_` で始まる。ツアー開始時に「いま在るものの id」(`Baseline`) を控え、**もとから在ったものは決して触らない**。

**目印 `data-tour`**: 画面の要素に付ける安定した名前 (`data-tour="create-input"` など)。ツアーと E2E のセレクタが同じものを使う。ツアー定義が指す名前が画面のコードに存在することは vitest が検査する (UI の変更で目印が消えると落ちる)。`data-testid` とは別物で、ツアーが使うものにだけ付ける。ツアーが指すだけの目的で、右ペインのノード詳細に「内容・レートの変更」ボタンを足した (入力 / 変換 / 関数ノードの編集。右クリックメニューと同じダイアログ。キーボードでも辿れる)。

**画面の扱い**
- 強調された要素と吹き出しの中だけ操作できる (driver.js の仕様。Tab キーも吹き出しと強調された要素の間を回る)。地図の粒子の層などクリックを通す要素は `styles-tour.css` で通すまま保つ。
- 要素が見つからないとき (別のタブにある・まだ表示されていない): その手順は**画面中央**に出し、「この部分はいまの画面に見つかりません」と書く。見つかれば強調に切り替わり、見つからなくても「この手順を飛ばす」で進める (止まったままにならない)。
- 「見る」手順は「次へ」にフォーカスが当たる (Enter で進む)。「やる」手順は、入力欄・ボタンならそこにフォーカスが当たる。「戻る」「この手順を飛ばす」がいつでもある。`prefers-reduced-motion` ならアニメーションを切る。ライト・ダークは本体の色の変数で決まる (`styles-tour.css`)。
- 中断 (Esc / ×) は「中断中」のピル (右下) に変わり、「続ける」「やめて片づける」を選べる。ページを再読み込みしても中断中として残り、手順は**続けられる場所** (`resume: true` の手順。ダイアログは再読み込みで消えるため、その手前) まで戻る。⚙ 設定の一覧からも「続きから」で再開できる。

**入口**: ① 初回起動で、地図が読み込まれたら右下に「チュートリアルを始めますか?」のカード (操作を邪魔しない。「あとで」でも始めても 1 度きり)。② ⚙ 設定 → 「チュートリアル」: 5 つのツアーと、完了のチェック、「始める / もう一度 / 続きから」。③ 空の状態の ⓘ: 地図が空 → 「はじめての入力ノード」、診断が空 → 「届かない原因を見つけて直す」、シナリオが空 → 「シナリオを記録する」。

**ツアー** (終わりの手順で文書名を示し、作ったものを片づける)

| ツアー | 手順 | 種類 | 作るもの (終了時に片づける) |
|---|---|---|---|
| 画面の見方 | 10 | 見る | なし (地図・凡例・診断・最終更新・トラフィックのタブと「トピック別/ノード別」・ノード一覧・⚙ 設定) |
| はじめての入力ノード | 10 | やる | ユーザーが作った入力ノード (開始後に増えた `/hello` の入力ノード。「残して終わる」も選べる) |
| 届かない原因を見つけて直す | 9 | やる | `tour_qos_pub` (BEST_EFFORT の入力ノード) と `tour_qos_sub` (`demo_nodes_cpp` の listener。ROS の既定の RELIABLE で購読) を API で作る |
| 関数ノードを作る | 9 | やる | ユーザーが作った関数ノード (`/shouted` を出す)。`/chatter` に送り手がいなければ `tour_chatter_src` を作る |
| シナリオを記録する | 19 | やる | `tour_shout` (関数ノード `/tour_in` → `/tour_out`) と、保存したシナリオ |

- 「届かない原因を見つけて直す」: 画面から作る入力ノードは常に RELIABLE で送り (どの受信側とも合う)、roshanavi の変換・関数ノードも BEST_EFFORT で購読する (どの送信側とも合う) ため、画面の部品だけでは QoS 不一致を作れない。そこで送り手 (BEST_EFFORT) と受け手 (RELIABLE) をツアー自身が API で作る。直し方は「入力ノードを編集して保存し直す」: 編集の保存は RELIABLE で送り直すので、赤い破線が実線に変わる。
- 「シナリオを記録する」はデモの `/chatter` / `/shouted` を使わず専用のトピックを使う (デモの talker の流れが記録に混ざらない)。保存したシナリオの結果が前回の同名の結果のまま画面に残っていても数えないよう、開始時の最後の実行の id を控える。
- 「関数ノードを作る」はデモの `text_shout` (同じ `/shouted` を出す関数ノード) と同じ出力トピックだが、開始前から在ったものは数えない。

**スクリーンショット** (`e2e/tour.spec.ts` が書く。各ツアーの途中の 1 手順): [`tour-welcome.png`](../images/tour-welcome.png)、[`tour-overview.png`](../images/tour-overview.png)、[`tour-first-input.png`](../images/tour-first-input.png)、[`tour-qos-fix.png`](../images/tour-qos-fix.png)、[`tour-function-node.png`](../images/tour-function-node.png)、[`tour-scenario.png`](../images/tour-scenario.png)、[`tour-dark.png`](../images/tour-dark.png)。

**新しいツアー・手順を足すとき**: `tours/<name>.ts` に手順を書き、`tours/index.ts` に登録し、`tour.<名前>.<手順>.title|body` の文言を足す。必要な要素に `data-tour` を付ける。vitest (文言・目印の検査) と E2E (`e2e/tour.spec.ts`: 画面に出ている指示のとおりに最後まで操作し、終了後に作ったものが無いことまで確かめる) を足す。ツアーが作るものの id は `tour_` で始める。
