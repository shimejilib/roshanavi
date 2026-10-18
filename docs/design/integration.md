# roshanavi — 既存の launch ファイルを引き取る (launch takeover)

利用者の既存の launch ファイルを roshanavi が引き取って起動し、中のノードを 1 つずつ止める・再起動する・ログを見る・計測する、を主な組み込み方にする (2026-10-18 決定、実装済み)。横から観察するだけのサイドカーは「手を入れたくない・入れられないシステム (実機、他人が動かしているシステム) を観察する」用途として残す ([planned/integration.md](../planned/integration.md) の 2. A)。使い方は [guide/takeover.md](../guide/takeover.md)。`roshanavi/launch_import/takeover.py` (流れ)、`takeover_plan.py` (純関数: 起動設定・差分・報告)、`skip.py` + `launch/takeover_rest.launch.py` (残りの部分)。

| | サイドカー (観察) | launch を引き取る (主) |
|---|---|---|
| ノードの停止・再起動・ログ | できない | できる (ノード単位、`whole` ではまとめて) |
| リソース監視 | 推定 / コンテナ単位 | 正確 |
| 詳細計測 (トレース) | 使えない | 使える |
| ビルド → 再起動のループ | 回らない | 回る |
| 既存のファイルへの変更 | compose にサービスを 1 つ足す | launch ファイルはそのまま使う |

## 起動のしかた
- `ros2 run roshanavi server --launch <パッケージ> <launch ファイル> [name:=value ...] [--mine <ノード名>]... [--launch-mode node|whole]` (`ros2 run roshanavi app` も同じ)。対象は **パッケージの launch ファイルだけ** (`ros2 launch <pkg> <file>` で指定できるもの。分解取り込みと同じ信頼範囲、[launcher.md#launch の分解取り込み](launcher.md#launch-の分解取り込み-p45b))。
- bringup に組み込むとき: `ros2 launch roshanavi takeover.launch.py package:=<pkg> launch_file:=<file> args:='a:=1 b:=2' mine:='patrol' mode:=node port:=6871` (`args` / `mine` / `extra` は空白区切り。中で上と同じ `server --launch ...` を起動するだけ)。
- 起動中に別の launch ファイルを引き取る API: `POST /api/takeover/start {package, launch_file, args, mode, mine}` (E2E とこれからの UI 用)。
- `--launch` のときは、前回「プロジェクトを切り替える」で開いたプロジェクトではなく `--project` のファイルで始める (引き取りの結果をどこに書くかを固定するため)。

## 2 つのモード
| | `node` (既定) | `whole` |
|---|---|---|
| 起動のしかた | 分解できたノードを 1 つずつの起動設定 (`kind: run`) にし、残り (ExecuteProcess、コンテナ、TimerAction、イベント、検査を通らなかったノード) を「残りの部分」として 1 つの launch で起動 | launch ファイル全体を 1 つの起動設定 (`kind: launch`) にする |
| 停止・再起動 | ノード単位 | まとめて |
| launch の動作 | 一部が元どおりにならない (下表、画面と起動ログに出す) | `ros2 launch` と同じ |
| ノード ⇄ プロセスの対応・ログ | ノードごと | プロセスの `__node:=` から対応づける。ログは launch 全体で 1 つ |

**残りの部分** (`node`): `ros2 launch roshanavi takeover_rest.launch.py roshanavi_package:=<pkg> roshanavi_launch_file:=<file> roshanavi_skip:=<一覧> <元の引数...>`。元の launch ファイルを `IncludeLaunchDescription` で読み込み、`launch_ros` の `Node.execute` / `LifecycleNode.execute` を包んで、roshanavi が別に起動するノード (`package:executable:name:namespace`、`,` 区切り。分解取り込みと同じ `extract.node_identity` で求めるので一致する) だけを起動しない。それ以外 (TimerAction の遅れ、イベントハンドラー、ExecuteProcess、コンテナ) は元どおりに動く。launch ファイルはパッケージ名とファイル名で探す (`ament_index` の share/<pkg>/launch、2 階層まで。任意のパスは受け取らない)。一覧が 4000 文字を超えるときと、分解できたノードが 1 つも無いときは `whole` にする (`notes`: `too_many_nodes` / `nothing_decomposed`)。

**引き継ぐもの・元どおりにならないもの** (`node`、`takeover_plan.report`。画面のバナー「詳しく」と差分ダイアログ、起動ログに出す。1 つでも元どおりにならないものがあれば `suggest_whole` で `whole` を勧める)

| launch の動作 | 扱い |
|---|---|
| `respawn=True` | 引き継ぐ: `auto_restart: true` (待ち時間は roshanavi の 1, 2, 4 … 30 秒。`respawn_delay` は使わない → `respawn_delay` として報告) |
| 環境変数 (`SetEnvironmentVariable` / `AppendEnvironmentVariable`、launch ファイル自身の `os.environ`、`Node(additional_env=...)`) | 引き継ぐ: ノードに届くときの環境の差分を `TargetSpec.env` に入れる。プログラムの読み込み先を左右する名前 (`LD_*`、`PYTHON*`、`PATH` など、[security.md](security.md)) は引き継がない (`env_blocked`)。`env=` (環境を丸ごと置き換え) と環境変数の削除は引き継がない (`env_replaced` / `env_unset_not_carried`) |
| `on_exit=Shutdown()` (required ノード) | 元どおりにならない (`required`): そのノードが終わってもほかは動き続ける |
| イベント (`RegisterEventHandler`、`EmitEvent`、`LifecycleTransition`、`OpaqueCoroutine`) | 残りの部分で動くが、きっかけのノードを roshanavi が別に起動するため働かないことがある (`events`) |
| `TimerAction` | 残りの部分で元どおり遅れて起動するが、1 つずつ起動するノードとの順番は保証しない (`timer_order`) |
| 条件 (`if` / `unless`) | 取り込んだときの引数で決まる (`conditions_fixed`)。引数を変えるときは `--launch` の引数を変えて起動し直す |
| コンポーザブルノードのコンテナ | 残りの部分でまとめて動く (1 つずつは止められない、`container`) |
| `prefix=` / `ros_arguments` | 使わない (`prefix_ignored` / `ros_arguments_ignored`) |

## launch ファイルが正 (二重管理にしない)
- プロジェクトファイルに残すのは「どのファイルをどの引数で引き取ったか」だけ: `takeover: {package, launch_file, args: ["name:=value"], mode}`。引き取りで作った起動設定には `takeover: true` と `imported_from: <pkg>/<file>` を付ける。役割 (`role`)・`autostart`・`auto_restart` は roshanavi 側の選択なので、取り込み直しても変えない (`--mine` で明示したノードだけ `mine` にする)。
- **起動し直したとき (冪等)**: 起動設定を「ノードの同一性」(`package / executable / name / namespace`、残りの部分、launch 全体) で突き合わせ、一致するものは同じ ID のまま使う (重複させない)。
  - 同じファイル・引数・モード: 前回の起動設定をそのまま起動する。前回の取り込みから launch ファイルが変わっていれば、差分を「取り込み直しますか?」(`reason: changed_since_last`) として聞く (勝手に変えない)。
  - 引数やモードが変わった: コマンドラインの指定に従い、差分をその場で当てる (同じノードは ID を保ったまま更新)。
  - 起動はすべてのターゲット (`--no-autostart` なら登録だけ)。保存する `autostart` は false のまま (`--launch` なしで起動したときに勝手に動かない)。
- **変更の検出**: 解析で読んだすべての launch ファイル (本体と include) とパラメータファイルを 2 秒ごとに `stat` (mtime・サイズ・inode) で見る。サーバーはそれらのファイルを開かない (中身を読むのはサンドボックスの子プロセスだけ)。変わったら次の回も同じであることを確かめてから (書き込み途中を避ける) 子プロセスで解析し直し、差分があれば `pending` (UI のバナー「launch ファイルが変更されました。取り込み直しますか?」)、差分が無ければ (ビルドで同じ内容がコピーされただけ等) 黙って新しい基準にする。`colcon build --symlink-install` (ビルドボタンの既定) では install 側が src へのリンクなので、src を保存しただけで検出される。リンクでないインストールでは、ビルドし直したときに検出される。
- **差分と取り込み直し**: `added` (起動設定を追加して起動) / `removed` (止めて外す) / `changed` (launch ファイルが決める項目 `params`・`remaps`・`args`・`env`・パラメータファイルに書き出した値が変わったもの。更新し、動いていれば再起動) / `unchanged` (触らない)。取り込み直しの時点で差分を計算し直す (確認の間に利用者がノードを削除した等にも合わせる)。
- 別のプロジェクトを開いている間は検出を止める (`state: inactive`)。

## Docker の場合
- 利用者のイメージの上に roshanavi を重ねたコンテナ 1 つで、`--launch` を使って起動する (例: turtle_demo の `dev` サービス)。元の起動方法 (roshanavi なし) は compose の profile (例: `plain`) で残し、切り替えられるようにする。
- roshanavi が強制終了されたときは `docker restart <コンテナ>` でコンテナごとやり直す ([launcher.md#子プロセスの後始末](launcher.md#子プロセスの後始末-12))。

## API
`GET /api/takeover` (状態: `state` `off|starting|ready|error|inactive`、`report`、`pending`、`targets`)、`POST /api/takeover/start`、`POST /api/takeover/check` (今すぐ解析し直す)、`POST /api/takeover/apply {preview_id}`、`POST /api/takeover/dismiss {preview_id}`。詳細は [api.md](api.md)。
