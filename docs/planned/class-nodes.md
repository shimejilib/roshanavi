# クラスノード (状態を持つロジックをノードにする) — 設計・未実装

関数ノード ([nodes.md](../design/nodes.md)) の拡張。実際のロジックは「初期化 → 処理のたびに内部状態を更新 → 必要に応じてリセット」というクラスで書かれることが多いため、ROS を import しない普通の Python クラスを、そのままノードとして動かす。

## 利用者が書くもの
```python
class MovingAverage:
    def __init__(self, window: int = 5):
        self.window = window
        self.values = []

    def process(self, x: float) -> float:
        self.values = (self.values + [x])[-self.window:]
        return sum(self.values) / len(self.values)

    def reset(self) -> None:
        self.values = []
```

## 対応づけ
| クラスの部分 | roshanavi の仕組み |
|---|---|
| `__init__` の引数 (型注釈と既定値) | ROS のパラメータにする。UI のパラメータ画面や `ros2 param set` で変更すると、インスタンスを作り直す。`on_param_change(name, value)` があればそれを呼んで作り直さない |
| 処理メソッド | 関数ノードと同じ呼び出し方 (受信ごと / 周期 / 複数入力)。1 つのクラスの複数メソッドを、別々のトピックに割り当てられる |
| 操作メソッド (`reset` など、引数なし) | 地図の右クリック・ノード詳細に「<メソッド名> を呼ぶ」ボタン。トピック `/<ノード名>/<メソッド名>` (`std_msgs/Empty`) でも呼べる。サービス対応 (#35) 後は `std_srvs/Trigger` でも呼べるようにする |
| `close()` / `shutdown()` | ノード停止時に呼ぶ (後片付け) |
| 戻り値が dict | キーごとに別の出力トピックへ送る |

- すべてのメソッドを 1 本のスレッドで順に呼ぶ (同時に呼ばれない)。利用者はロックを書かなくてよい。
- 例外は関数ノードと同じ扱い (ログと画面に行番号付きで表示、ノードは止めない)。`__init__` の例外は「初期化に失敗」として表示し、修正 (保存) を待つ。

## ホットリロード時の状態
- 既定: インスタンスを作り直し、状態はリセットされる。画面に「状態をリセットしました」と表示する。
- クラスに `get_state()` / `set_state(state)` があれば、作り直しの前後で状態を引き継ぐ。

## UI
- 「＋ 関数ノードを作る」を「＋ 関数・クラスノードを作る」に拡張する。モジュール内のトップレベルのクラスを静的解析 (ast) で列挙し、`__init__` の引数・各メソッドのシグネチャから、パラメータと割り当ての候補を作る (サーバーでは import しない)。

## シナリオ
- 新しいステップ `call: {node: <ノード名>, method: <メソッド名>}` (操作メソッドを呼ぶ)。例: reset 後に出力が初期値に戻ることを確かめる。

## ROS への卒業 (コード書き出し)
- クラスを包む普通の rclpy ノードを生成する。
- オプションで lifecycle ノードとして書き出す (`__init__` → on_configure、処理メソッドの購読 → on_activate、`close` → on_cleanup)。ROS の lifecycle を学ぶ教材にもなる。

## 対象外
- C++ のクラス。C++ のロジックは普通の ROS ノードとして書き、ランチャーから起動する。

## サンプル
- `MovingAverage` (window パラメータ、reset)、`Counter` (reset)、複数出力の例 (平均と件数を dict で返す)。
