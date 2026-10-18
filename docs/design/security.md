# roshanavi — セキュリティ

roshanavi は **認証なしのローカル開発ツール** で、利用者の ROS 環境の中でノードを起動・停止し、ファイルを読み書きし、式を評価する。そのため、この文書は設計上の判断を 1 か所に集めた索引で、各項目の詳細はリンク先の節にある。新しい機能を足すときは、ここの項目に当てはまるものがないか確認する (`CLAUDE.md` の「Rules that have bitten this project」にも要約がある)。

## ネットワークの入口

- **ローカルだけで待ち受ける**: サーバーは既定で `127.0.0.1` に bind する。Docker では `0.0.0.0` を明示指定し、ポート公開は compose 側で `127.0.0.1:6871:6871` にして、ホストの外からは届かない。認証付きのリモート公開は非ゴール ([vision.md#ゴールと非ゴール](../overview/vision.md#ゴールと非ゴール))。別マシンからのアクセスは [remote-access.md](../planned/remote-access.md) に設計だけある (未実装)。詳細: [api.md#既定ポート・入力検証・エラー形式](api.md#既定ポート入力検証エラー形式)。
- **Host / Origin / Content-Type を全ルートで検査する**: ブラウザ経由の攻撃 (DNS rebinding、WebSocket のなりすまし、CSRF) を防ぐための ASGI ミドルウェア。`Host` は許可リスト、WebSocket の `Origin` は許可リスト内のみ、ボディのある POST / PUT / PATCH / DELETE は `application/json` のみ (違反は 415)。新しい REST・WebSocket は必ずこの検査の内側に置く。詳細: [api.md#ローカル Web からの攻撃対策](api.md#ローカル-web-からの攻撃対策)。
  - 状態を変える操作も同じ検査を通る例: 詳細計測モードの `PUT /api/tracing` ([measurement.md#詳細計測モード](measurement.md#詳細計測モード-トレース計測-p47))、ブラウザ入力の `/ws/capture` ([input-and-media.md#メディア](input-and-media.md#メディア-アダプタファイルソースブラウザ入力ビューア-p4))、パラメータの変更 ([launcher.md#ノードのパラメータと型の定義](launcher.md#ノードのパラメータと型の定義-p45a))。
- **入力は入口で検証する**: API の入力は pydantic モデルで検証し、エラーは `{error: {code, message}}` で返す。プロジェクトファイルもスキーマで検証し、未知のキーは拒否する。詳細: [api.md#既定ポート・入力検証・エラー形式](api.md#既定ポート入力検証エラー形式)、[launcher.md#プロジェクトファイル](launcher.md#プロジェクトファイル-p3)。

## 入力された式・コード

- **`eval` / `exec` を使わない**: ダミー入力の式 (`${...}`) と変換ノードの式は、`ast.parse` した木の許可ノードだけを評価する自前の評価器で動かす。属性アクセス・添字・内包表記・lambda は拒否し、べき指数や文字列長に上限を置く (DoS 防止)。詳細: [input-and-media.md#expr](input-and-media.md#expr-安全な式評価)。
- **入力メッセージのフィールド参照の境界**: 変換ノードの式が受信メッセージを読めるのは、`Expression(..., message_names=...)` で許可した名前に限る。メッセージは素のデータにして読み取り専用の `MsgView` で包み、`getattr` は一切使わないので Python のオブジェクトの属性には届かない。`_` で始まるフィールド名は拒否し、ビューは変更・反復・ハッシュができない。この評価器を広げるときは、安全の境界のテストを必ず足す。詳細: [input-and-media.md#expr](input-and-media.md#expr-安全な式評価)。
- **関数ノードの利用者コードはサーバーの外で動かす**: サーバーは関数の一覧とシグネチャを `ast` の静的解析だけで作り、利用者のコードをサーバー内で実行も import もしない (「コードの場所」の理由の一覧も、ファイルを読んで構文解析するだけ。`.gitmodules` は文字として読み、git は実行しない)。import できるのは A: `<workspace>/src` の ROS パッケージの中の Python パッケージ、B: 利用者がプロジェクトに登録したフォルダ (`code_paths:`)、C: 利用者が登録したインストール済みのモジュール (`installed_modules:`) だけで、B・C は既定で空。利用者自身のコードなので、信頼の水準は自分でノードを起動するのと同じ (サンドボックスはしない)。詳細: [nodes.md#関数ノード](nodes.md#関数ノード-ふつうの関数をそのままノードにするp55)、[user-code.md#2](user-code.md#2-置き場所-探す範囲)。
  - インストール済みのモジュール (C) の場所は、`find_spec` (親パッケージを import してしまう) を使わず、検索パスのディレクトリを自分で調べて決める。C に **Python の標準ライブラリは登録できない** (`os.system` などを関数ノードにすると、そのトピックに送れる誰でもコマンドを実行できてしまうため。スキーマと解決の両方で拒否)。
  - 利用者のパッケージ (A・B) に、標準ライブラリやノード自身が使うライブラリ (`rclpy`、`numpy` …) と同じ名前は使えない (ノードの中のそれを置き換えてしまうため。ノードの中でも、既にある別物の名前なら読み込まない)。
- **クラスノードも同じ**: クラス・`__init__` の引数・メソッドの一覧は `ast` の静的解析だけで作り、クラスのインスタンスも別のノードのプロセスの中で作る (サーバーでは import も実行もしない)。import できる範囲・ホットリロード・信頼の水準は関数ノードと同じ。クラスのメソッドはすべてノードの 1 本の作業スレッドで動き、キューは 1000 件までで、`close()` を待つのは最大 3 秒 (停止が止まらない)。詳細: [nodes.md#クラスノード](nodes.md#クラスノード-状態を持つ処理をそのままノードにする)。
- **操作メソッドは登録したものだけが呼べる**: `POST /api/classes/{id}/call` が呼べるのは、そのクラスノードの `actions` に書いたメソッドだけ (メソッド名は先頭が `_` でない識別子の正規表現、`close` / `get_state` などのフックは登録できない)。サーバーは `std_msgs/Empty` を `/<ノード名>/<メソッド名>` に送るだけで、任意のメソッドや引数を指定する手段は無い。そのトピックと ROS のパラメータ (`on_param_change(name, value)` に渡す値は ROS が型を検査し、JSON の引数は `json.loads` で読む。`eval` はしない) は、ほかの ROS のトピック・パラメータと同じ信頼の水準で、同じ ROS ドメインの誰からでも触れる ([ネットワークの入口](#ネットワークの入口))。
- **シナリオの判定も `eval` を使わない**: `where` のフィールドは受信メッセージの素のデータを `MsgView` で辞書引きするだけ、送る値の `${...}` は同じ式評価器。正規表現は 500 文字まで、比べる文字列は 10,000 文字まで。詳細: [scenarios.md#判定ルール](scenarios.md#判定ルール-runnerpy--checkspy)。

## ファイルとパス

- **ユーザーが指定するパスは realpath で包含を確かめる**: `..`・絶対パス・外向き symlink を拒否する。対象ごとの許可範囲は次のとおり。
  - 注入の stream / bag のファイル: `data_dir` の中 (パストラバーサル防止)。[input-and-media.md#injector](input-and-media.md#injector)
  - メディアファイルとフォルダ: `data_dir` の中の通常ファイル。CameraInfo のキャリブレーション YAML は ワークスペースか `data_dir` の中。[input-and-media.md#メディア](input-and-media.md#メディア-アダプタファイルソースブラウザ入力ビューア-p4)
  - Launcher のパラメータファイル: ワークスペースか `data_dir` の中の既存の `.yaml`。[launcher.md#Launcher](launcher.md#launcher-p3)
  - ダミー・変換ノードの launch の書き出し先、関数ノード・クラスノードのコードの書き出し先: ワークスペースの中 (制御文字は拒否)。[nodes.md#恒久ダミーノード](nodes.md#恒久ダミーノード-p3)、[nodes.md#関数ノード](nodes.md#関数ノード-ふつうの関数をそのままノードにするp55)
  - 録画の削除: 録画ディレクトリの形式に合い、親が recordings ディレクトリそのものであるもの (symlink・`..` を拒否)。[input-and-media.md#録画](input-and-media.md#録画-p4)
  - launch ファイルの取り込み: `ros2 launch` で利用者が実行するのと同じ範囲 (走査で見つかったパッケージの launch ファイル、またはワークスペースの中のファイル) だけ。`data_dir` (アップロード・録画) の下のファイルは評価しない。[launcher.md#launch の分解取り込み](launcher.md#launch-の分解取り込み-p45b)
  - 関数ノード・クラスノードのモジュール: A は `<workspace>/src`、B は登録したフォルダの、realpath が内側にある通常ファイル (内向きの symlink は使え、外向きは拒否。`.git` と隠しディレクトリは辿らない)。[nodes.md#関数ノード](nodes.md#関数ノード-ふつうの関数をそのままノードにするp55)、[user-code.md#2](user-code.md#2-置き場所-探す範囲)
  - 「コードの場所」に登録するフォルダ (B): 存在するフォルダ、制御文字なし、`/`・`/usr`・ホームディレクトリそのものなどの広すぎる場所、`.git` の中、data フォルダ (アップロード・録画の置き場) とその中・それを含むフォルダは拒否 (アップロードしたファイルがノードで実行されないように)。[user-code.md#2](user-code.md#2-置き場所-探す範囲)
  - 「ひな形を作る」の書き出し先: `<workspace>/src/<名前>` だけ。名前は ROS のパッケージ名の規則 (`[a-z][a-z0-9_]*`) で検査し、既にあるフォルダ・パッケージ名・標準ライブラリなどの名前は断る。[user-code.md#4](user-code.md#4-ひな形を作る)
  - シナリオのファイル: クライアントは一覧の id (`project:<file>` / `example:<file>`) だけを送り、ファイル名は厳しいパターン、realpath がシナリオのディレクトリの直下であること。サンプルは読み取り専用。シナリオが使う stream / bag / メディアのファイルは注入と同じく `data_dir` の中。結果は `data_dir/scenario_results/` に新しい 50 件まで。[scenarios.md#サーバー](scenarios.md#サーバー-scenarios-タブ-servicepy--storepy)
- **プロジェクトの切り替えは一覧の `id` だけを受け付ける**: クライアントから任意のパスを送って開かせることはできない。サンプルはコピーして開き、サンプル自体と元のプロジェクトファイルには書かない。詳細: [launcher.md#プロジェクトファイル](launcher.md#プロジェクトファイル-p3)。
- **既存のファイルを壊さない**: 「ひな形を作る」は既にあるフォルダ (symlink も) を使わず (409)、フォルダは `mkdir`、ファイルは `O_EXCL` で作り、途中で失敗したら自分が作ったものだけを消す。プロジェクトファイルの保存は一時ファイル → fsync → `os.replace` (原子的)。テンプレートのコピーは `O_EXCL` で、既存は上書きしない。読み込みに失敗したファイルは自動では上書きしない。関数ノード・クラスノードのコードの書き出しは、roshanavi が生成したファイルだけを置き換え、利用者のファイルは上書きしない (409。生成ファイルの先頭の印は `# Generated by roshanavi from function node` / `class node`)。詳細: [launcher.md#プロジェクトファイル](launcher.md#プロジェクトファイル-p3)、[nodes.md#関数ノード](nodes.md#関数ノード-ふつうの関数をそのままノードにするp55)。

## サブプロセス

- **シェルを使わず、argv のリストで起動する**: Launcher のノード、ffmpeg、`ros2 bag play` / `record`、計測ノード、launch 取り込みの子プロセスのすべて。詳細: [launcher.md#Launcher](launcher.md#launcher-p3)、[input-and-media.md#メディア](input-and-media.md#メディア-アダプタファイルソースブラウザ入力ビューア-p4)、[input-and-media.md#録画](input-and-media.md#録画-p4)、[measurement.md#C++ 計測ノード](measurement.md#c-計測ノード-roshanavi_probe-p46)、[launcher.md#launch の分解取り込み](launcher.md#launch-の分解取り込み-p45b)。
- **pip は実行しない**: 足りないライブラリは、`package.xml` の 1 行と `rosdep install`、または venv の手順を **表示するだけ** で、roshanavi は pip も apt も実行しない。キーを確かめるために実行するのは `rosdep resolve <key>` だけ (argv のリスト、シェルなし、10 秒。キーは `[a-z0-9][a-z0-9._+-]*` に限る)。ノードの Python を知るために、その Python に `-c` で `sys.path` などを尋ねる (argv のリスト、10 秒。利用者のコードは import しない)。[user-code.md#5](user-code.md#5-依存ライブラリ)
- **venv の Python でノードを起動する**: サーバーが venv の中で動いている、または起動した環境で venv が有効 (`VIRTUAL_ENV`) なときだけ、関数・クラスノードを `ros2 run --prefix <venv>/bin/python3 …` で起動する。`--prefix` の値はサーバーが決め (`shlex.quote`)、API から指定する手段は無い。[user-code.md#5](user-code.md#5-依存ライブラリ)
- **利用者の値を argv に紛れ込ませない**: `ros2 run` / `ros2 launch` / rcl 自身が解釈する argv (`--prefix`, `--ros-args`, `--params-file`, `__node:=` …) を、パッケージ名・実行ファイル名・パラメータ・リマップ・追加引数に混ぜられないよう、正規表現と走査結果で検査する。起動できるのは走査結果に存在するパッケージ・実行ファイル・launch ファイルだけ。詳細: [launcher.md#Launcher](launcher.md#launcher-p3)。
- **シナリオの setup も Launcher と同じ検査を通る**: `run` / `launch` / 関数・変換・入力ノードは Launcher の仕様にして同じ検証で起動し、`cmd` は `ros2 run` / `ros2 launch` の形だけを受け付けて同じ仕様に読み替える (ほかのコマンドは起動しない)。API から保存したシナリオで起動できる範囲は Launcher の API と同じ。詳細: [scenarios.md#ステップの種類](scenarios.md#ステップの種類)。
- **まだ source されていないパッケージの環境**: colcon が書く `package.dsv` (宣言的な形式) を読んで適用し、シェルスクリプトは実行しない。詳細: [launcher.md#Launcher](launcher.md#launcher-p3)。
- **ffmpeg に外部参照を読ませない**: 細工したファイル (HLS / concat のプレイリスト等) で URL 取得や `data_dir` 外の読み出しをさせないため、拡張子から demuxer を決めて `-f` で強制し、`-format_whitelist` にもその 1 つだけを入れる。`-protocol_whitelist file,pipe` と、入力を `file:<絶対パス>` で渡すことで http などのプロトコルや `concat:` 等の接頭辞も使えない。プレイリストらしき先頭は ffmpeg に渡す前に拒否する。詳細: [input-and-media.md#メディア](input-and-media.md#メディア-アダプタファイルソースブラウザ入力ビューア-p4)。
- **launch ファイルの評価はサンドボックスの子プロセスで行う**: Python の launch ファイルの評価はその Python コードの実行になるため、サーバーのプロセスでは行わない。新しいセッションの子プロセスで、20 秒で打ち切り、終了後もプロセスグループごと SIGKILL し、結果は 8 MB まで。評価中もプロセスは起動せず、`LaunchContext` を変えるだけの action だけを訪れ、`Node` は実行せずに設定を読み取る。`OpaqueFunction` は中の Python が実行されるので警告を出す。パラメータファイルの中身は子プロセスが読み、取り込みは `preview_id` で行って、クライアントから中身を受け取らない。詳細: [launcher.md#launch の分解取り込み](launcher.md#launch-の分解取り込み-p45b)。
- **書き出すコードには検証済みの値だけを埋め込む**: launch ファイルの書き出しは、ノード名・ID を検証済みの値だけ `repr()` で埋め込む。関数ノード・クラスノード (通常の rclpy ノードも lifecycle も) のコードの書き出しも検証済みの値を `repr()` で埋め込み、書く前に `compile()` で確かめる。詳細: [nodes.md#恒久ダミーノード](nodes.md#恒久ダミーノード-p3)、[nodes.md#関数ノード](nodes.md#関数ノード-ふつうの関数をそのままノードにするp55)。
- **自分が起動したものだけを止める**: プロセスは新しいセッション (プロセスグループ) で起動し、停止は SIGINT → SIGTERM → SIGKILL の順。サーバー終了時は全ターゲットを止め、計測ノードは親が変わったら自分で終了する。詳細: [launcher.md#Launcher](launcher.md#launcher-p3)、[measurement.md#C++ 計測ノード](measurement.md#c-計測ノード-roshanavi_probe-p46)。
- **シナリオは後片付けを必ず行う**: セットアップのプロセスはシナリオ専用のプロセス管理 (プロセスグループ) で起動し、成功・失敗・中止のどれでも止める。プロジェクトの起動設定はシナリオの前の状態に戻す。[scenarios.md#判定ルール](scenarios.md#判定ルール-runnerpy--checkspy)

## 他人のプロセスに触らない

- **roshanavi が起動していないプロセスにはシグナルを送らない**: 地図・ノード一覧から停止・再起動できるのは Launcher の起動対象と注入ジョブだけで、外部のノードはボタンを無効にして理由を出す。lifecycle の遷移は ROS の正規のサービスだけを使い、プロセスにシグナルは送らない。詳細: [ui.md#実装メモ (P3: Launcher)](ui.md#実装メモ-p3-launcher)、[launcher.md#lifecycle ノード](launcher.md#lifecycle-ノード-p45b)、[ui.md#実装メモ (P4.5b: ノード一覧・lifecycle・launch の取り込み)](ui.md#実装メモ-p45b-ノード一覧lifecyclelaunch-の取り込み)。
- **外部ノードのパラメータ・lifecycle の変更は確認を挟む**: roshanavi が起動していないノード (role `other`) は閲覧のみが既定で、変更には `allow_external: true` が必要。UI は確認ダイアログの後にだけこれを付け、無ければ 403 (`external_node_readonly`)。roshanavi 自身のノードは変更できない (403 `self_node`)。グラフにいまいるノードだけが対象で、任意のサービス名は作らせない。詳細: [launcher.md#ノードのパラメータと型の定義](launcher.md#ノードのパラメータと型の定義-p45a)、[launcher.md#lifecycle ノード](launcher.md#lifecycle-ノード-p45b)、[ui.md#実装メモ (P4.5b: ノード一覧・lifecycle・launch の取り込み)](ui.md#実装メモ-p45b-ノード一覧lifecyclelaunch-の取り込み)。
- **リソース監視は読むだけ・自分のプロセスだけ**: `/proc` を読むだけで、シグナル・ptrace・パケットキャプチャはしない。一覧に出すのは自分のユーザーのプロセスだけ (root のとき、例えばコンテナの中では、そのコンテナのすべて)。接続の一覧は接続先と状態だけで、通信の中身は見ない (TLS の中継もしない)。接続先の逆引きは別スレッドでキャッシュ付き、`--no-reverse-dns` で止められる。API は GET と WebSocket だけで、Host / Origin の検査を通る。詳細: [resources.md#権限とプライバシー](resources.md#権限とプライバシー)。
- **一括操作は巻き込まれるノードを見せる**: 起動設定ごとに 1 回だけ操作し、選択していないのに一緒に止まるノードも確認ダイアログに列挙する。詳細: [ui.md#実装メモ (P4.5b: ノード一覧・lifecycle・launch の取り込み)](ui.md#実装メモ-p45b-ノード一覧lifecyclelaunch-の取り込み)。

## 資源の上限と権限

- **入力の大きさに上限を置く**: 式の評価 (べき指数・文字列長・10,000 文字・添字 ±1,000,000)、パラメータの値 (文字列 4096 文字、配列 1000 要素など)、ブラウザ入力 (音声 256 KB / フレーム、カメラ 4 MB / フレーム・30 fps、1 トピックに 1 つ)、ビューア (最大 16 トピック)、launch 取り込み (深さ 40・5000 要素・結果 8 MB・案は最大 16 個 / 30 分)、変換ノードの遅延キュー (最大 10,000 件)。詳細: [input-and-media.md#expr](input-and-media.md#expr-安全な式評価)、[launcher.md#ノードのパラメータと型の定義](launcher.md#ノードのパラメータと型の定義-p45a)、[input-and-media.md#メディア](input-and-media.md#メディア-アダプタファイルソースブラウザ入力ビューア-p4)、[launcher.md#launch の分解取り込み](launcher.md#launch-の分解取り込み-p45b)、[nodes.md#変換ノード](nodes.md#変換ノード-p5)。
- シナリオ: ファイル 512 KB・ステップ 500・`where` 32 条件、受信のためは 1 トピック 20,000 件 (大きい配列は長さと先頭だけ)、実行は 1 つずつ、記録モードは見張るトピック 8・タイムライン 5,000 件・30 分。
- **録画はディスクの空きを守る**: 空きが少ないと警告し、さらに少なければ自動停止、開始もしない。リソース監視も同じしきい値で data_dir の空きを診断パネルに出す。詳細: [input-and-media.md#録画](input-and-media.md#録画-p4)、[resources.md#ディスクの安全装置](resources.md#ディスクの安全装置)。
- **リソース監視は軽く保つ**: 1 秒ごとの計測は専用スレッドで行い、イベントループや ROS の executor を止めない。1 コアの 2% 未満が目標で、計測そのものの負荷を画面に出す。接続の一覧は 1 プロセス 100 件・タイムライン 300 件、逆引きの待ちは 64 件まで。
- **詳細計測モードに特権は要らない**: LTTng のユーザー空間 (UST) だけを使い、root 権限・カーネルモジュール・Docker の特権は要らない。詳細: [measurement.md#詳細計測モード](measurement.md#詳細計測モード-トレース計測-p47)。
- **E2E は利用者のデータに触らない**: E2E は別の `ROS_DOMAIN_ID`・空の `/data` (tmpfs)・ポート非公開の隔離したスタックで動かし、前後で `lab` のプロジェクトファイルが変わっていないことを確かめる。詳細: [ui.md#実装メモ (P2)](ui.md#実装メモ-p2)。
