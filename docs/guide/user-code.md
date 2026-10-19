# 自分のコードを関数・クラスノードにする

roshanavi の **関数ノード** と **クラスノード** は、普通の Python の関数やクラスを、そのまま ROS 2 のノードとして動かします。ROS のコード (rclpy) は書きません。この章では、自分のコードをどこに置けば使えるか、最初の一歩 (「ひな形を作る」)、ライブラリの入れ方、つまずいたときの直し方を説明します。

- 関数: 受け取った値で関数を呼び、戻り値を送ります (`def convert(text: str) -> str`)。
- クラス: 状態を持つ処理 (`__init__` / `process` / `reset`)。`__init__` の引数は ROS のパラメータになり、`reset` はボタンで呼べます。

作り方は、地図の上の **「＋ 関数・クラスノードを作る」** から始めます。

## 1. まずは「ひな形を作る」

まだコードが無い、どこに何を置けばよいか分からない、という場合はここから始めます。

1. 「＋ 関数・クラスノードを作る」を開き、**「コードの場所」** を開きます。
2. 下の **「ひな形を作る」** にパッケージ名を入れて (既定は `my_logic`)、ボタンを押します。
3. ワークスペースの `src/my_logic/` に、次のファイルができます。そのまま画面が `my_logic.logic` の `convert` を選んだ状態になります。

```
src/my_logic/
  package.xml          依存ライブラリの書き方の例 (コメント)
  setup.py / setup.cfg colcon build もできる最小の構成
  resource/my_logic
  my_logic/__init__.py
  my_logic/logic.py    関数 convert と、クラス Processor (__init__ / process / reset)
  test/test_logic.py   ROS なしで動くテスト
  README.md            動かし方
```

4. 入力のトピック (トピック、例: `/chatter`) と出力のトピックを選んで「作成」 (空のまま作って、あとで地図の上で線を引いてつないでもかまいません。[線でつないで作る](wiring.md))。もう動いています (**ビルドは要りません**)。
5. `my_logic/logic.py` を書き換えて保存すると、動いているノードが **すぐに読み直します**。

![ひな形を作ったところ](../images/user-code-scaffold.png)

- クラスノードにするときは、「作るもの」で「クラス」を選びます (クラス `Processor` が選ばれます)。`process` を入力・出力につなぎ、`reset` を「操作メソッド」にすると、地図の右クリックや右ペインのボタンで呼べます。
- テストは ROS なしで動きます: `cd src/my_logic && python3 -m pytest test`
- 普通の ROS パッケージとしてビルドもできます: `colcon build --packages-select my_logic`
- 名前は小文字で始め、小文字・数字・`_` だけにします。既にあるフォルダは上書きしません。

## 2. コードを置ける場所 (A / B / C)

roshanavi が探すのは、次の 3 か所です。**B と C は、自分で登録したときだけ** 探します。「コードの場所」で、範囲ごとに見つかったものと、見つからなかった理由が見られます。

![コードの場所](../images/user-code-locations.png)

### A. ワークスペースの ROS パッケージ (いつも使えます)

ROS パッケージ (`package.xml` がある) の中の Python パッケージ (`__init__.py` があるフォルダ) です。ament_python の普通の形はこうです。

```
<ワークスペース>/src/my_pkg/package.xml
<ワークスペース>/src/my_pkg/my_pkg/__init__.py     ← 空のファイルでかまいません
<ワークスペース>/src/my_pkg/my_pkg/logic.py        ← ここに関数・クラスを書く
```

C++ のパッケージ (ament_cmake) の中の Python も使えます。`CMakeLists.txt` の `ament_python_install_package(${PROJECT_NAME})` が読み込むフォルダ (`PACKAGE_DIR` で場所を変えていればそのフォルダ) を探します。

### B. 登録した場所 (ROS と関係ない Python のプロジェクト)

`~/work/vision_lib/` のような普通の Python プロジェクトは、「コードの場所」の **B** にフォルダを追加すると使えます (プロジェクトファイルの `code_paths:` に保存されます)。次の形を認識します。

```
~/work/vision_lib/vision_lib/__init__.py        (flat レイアウト)
~/work/vision_lib/src/vision_lib/__init__.py    (src レイアウト)
```

**登録した場所は、ライブラリの置き場所としても使えます。** たとえば自分のパッケージ (A) の中で `import simple_pid` と書き、`simple_pid` が登録した `/opt/third_party/simple-pid` にあるなら、そのまま動きます (rosdep や pip で入れる必要はありません)。ノードの Python に同じ名前のライブラリが入っていれば、そちらが先に使われます。標準ライブラリや `rclpy`・`numpy` と同じ名前は使われません。登録を変えたら、動いているノードを再起動してください (登録したフォルダの中のライブラリを書き換えたときは、関数やクラスと同じようにすぐ読み直します)。

登録したフォルダの外を指すシンボリックリンクは、安全のため読み込みません。Docker で roshanavi を動かしている場合は、そのフォルダをコンテナから見えるようにマウントしてから、コンテナの中のパスで登録します。

### C. インストール済みのモジュール (pip / apt で入れたライブラリ)

社内ライブラリなど、既にインストールしてあるものの関数を使うときは、**C** にモジュール名 (例: `vision_lib.filters`) を登録します (`installed_modules:` に保存)。

- ノードを動かす Python から探します (「コードの場所」の下に、どの Python かが出ます)。
- 拡張モジュール (`.so`) だけのものは中身を一覧できないので、関数名を入力します。
- 保存しても読み直しません。入れ直したら、ノードを再起動します。
- Python の標準ライブラリ (`os` など) は登録できません。

### 置き場所の決め方

| 状況 | 置き場所 |
|---|---|
| これから書く | 「ひな形を作る」(A) |
| もう ROS パッケージの中にある | そのまま (A) |
| ROS と関係ないプロジェクトにある | そのフォルダを B に登録 |
| pip / apt で入れたライブラリ | モジュール名を C に登録 |
| git のサブモジュールにある | 下の「git のサブモジュール」 |

同じ名前のパッケージが 2 か所にあると、A → B → C の順で先のものを使います (「候補にならなかったもの」に出ます)。

## 3. 依存ライブラリ (numpy、OpenCV など)

**roshanavi は pip を自動では実行しません。** 足りないライブラリがあると、ノードの右ペインに「`cv2` が見つかりません」と出て、入れ方を 2 通り案内します。

![足りないライブラリの案内](../images/user-code-dependency.png)

どちらの方法でも、入れたあとはノードを **再起動** します (右ペインの「再起動」。ファイルを保存し直しても読み直します)。

### ① 推奨: package.xml に書いて rosdep で入れる

apt で入るので、OS の Python を壊しません。画面に出た 1 行を、パッケージの `package.xml` の `<package>` の中に足します。

```xml
<exec_depend>python3-opencv</exec_depend>
```

そのあと、ワークスペースで次を実行します (画面にはパッケージの実際のパスで出ます)。

```bash
rosdep install --from-paths src/my_pkg --ignore-src -y
```

- import の名前と rosdep のキーは違うことがあります (`cv2` → `python3-opencv`、`yaml` → `python3-yaml`、`PIL` → `python3-pil`)。roshanavi は rosdep 自身のデータベースで確かめたキーを出します。
- 「rosdep のデータベースが使えない」と出たら、`sudo rosdep init` (初回だけ) と `rosdep update` を実行してから開き直します。
- numpy は、ROS 2 のノードなら必ず入っています (rclpy が使っているため)。

### ② apt に無いとき: 仮想環境 (venv) に pip で入れる

ROS も見える仮想環境を作り、その中で roshanavi を起動し直します。

```bash
sudo apt install python3-venv            # 初回だけ
python3 -m venv --system-site-packages ~/roshanavi-venv
source ~/roshanavi-venv/bin/activate
pip install -r requirements.txt          # または pip install <ライブラリ>
# この端末で roshanavi を起動し直す
```

- `--system-site-packages` を付けると、ROS や apt で入れたライブラリも見えます。
- 仮想環境を有効にした端末で roshanavi を起動すると、関数・クラスノードもその Python で動きます (右ペインに「仮想環境 (venv) で動いています」と出ます)。
- pip の名前は import の名前と違うことがあります (`cv2` → `opencv-python`)。画面に出ます。
- システムの Python に `pip install --break-system-packages` で入れるのはおすすめしません。

### requirements.txt の照合

コードの隣 (ROS パッケージのフォルダ、または登録したフォルダ) に `requirements.txt` があると、書かれているものと、ノードの Python に入っているものを照らし合わせて、足りないもの・版が合わないものを右ペインに出します。「venv に入れたのに見つからない」ときは、右ペインの「Python:」の行で、ノードがどの Python で動いているかを確かめます。

## 4. よくあるつまずき

| 症状 | 原因と直し方 |
|---|---|
| モジュールが一覧に出ない | 「コードの場所」の「候補にならなかったもの」に理由が出ます。多いのは `__init__.py` が無い、`package.xml` が無い、`.py` を `package.xml` の隣に置いた (`<pkg>/<pkg>/` の中に移す) |
| 関数が一覧に出ない | トップレベル (インデントなし) の `def` だけが候補です。クラスの中の関数、`if __name__ == '__main__':` の中、名前が `_` で始まるもの、`async def` は出ません (モジュールを選ぶと理由が出ます) |
| 構文エラー | ファイル名と行番号が出ます。直して保存すると、動いているノードも読み直します (それまでは前の版で動き続けます) |
| `from .utils import x` | 使えます (パッケージとして読み込みます)。同じパッケージの別のファイルを保存しても読み直します |
| 保存のたびに読み直しが遅い | モジュールの直下で重い処理 (モデルの読み込みなど) をしていると、「読み込みに時間がかかっています」と出ます。クラスの `__init__` に移します |
| 「rclpy を import しています」の注意 | 動きますが、関数・クラスノードの中でさらに ROS を使うと混乱の元です。ROS とのやり取りは roshanavi に任せます |
| 拡張モジュール (.so) | 読み込めますが、保存しても `.so` は読み直しません (ノードを再起動) |
| パッケージ名を `json` や `test` にした | Python の標準ライブラリなどと同じ名前は使えません。名前を変えます |

## 5. git のサブモジュール

ロジックが git のサブモジュール (例: `src/vision_lib`) にある場合:

- roshanavi は git を実行しません。先に、自分で取得しておきます (Docker を使っている場合はコンテナの外で):

```bash
git submodule update --init --recursive
```

- 取得していないサブモジュールは中身が空なので、「コードの場所」に「サブモジュール `src/vision_lib` の中身がありません」とコマンド付きで出ます。
- 取得したサブモジュールは、普通のフォルダと同じです。ROS パッケージなら A でそのまま、そうでなければ B に登録して使います。
