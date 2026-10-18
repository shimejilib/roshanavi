# roshanavi — 配布とインストールの設計

P7 (公開準備) で実施し、実装後に `docs/design/` へ統合する。

## 0. 対応ディストロ

| ディストロ | Ubuntu / Python | 扱い |
|---|---|---|
| **Jazzy Jalisco** (LTS) | 24.04 / 3.12 | 正式対応 (既定) |
| **Lyrical Luth** (LTS、2031 年ごろまで) | 26.04 / 3.14 | 正式対応 (#36) |
| Kilted Kaiju | 24.04 / 3.12 | 動作確認のみ (#37)。サポート期限が 2026 年末ごろと近いため継続的には確認しない。2026-10-18 にバックエンドのテスト全体を確認した (gtest 12 + 11 passed、pytest 1089 passed / 1 failed: 0.3 秒のタイミングのテストで、単独では通る)。E2E は Kilted では未実施 |

- 1 つのソースで全ディストロを扱う。ディストロで違う所は小さな互換の層に閉じ込める: pydantic 1.10 / 2 は `roshanavi/pydantic_compat.py`、それ以外は実装の中で両方の形を受け付ける ([testing.md の R](testing.md#r-ディストロ対応-36-37))。
- apt で配るとき (将来) は `ros-jazzy-roshanavi` と `ros-lyrical-roshanavi` を作る。Docker では `ROS_DISTRO=lyrical docker compose ...` (イメージ `roshanavi:dev-<distro>`)。

## 1. 前提: 「1 ノードとしてつなぐだけ」では足りない
roshanavi はノード (DDS の参加者) でもあるが、次の機能は **利用者のワークスペースと同じ環境** で動いていないと成り立たない。
- 独自 msg 型の扱い (エコー・注入・シナリオ): 型の Python モジュールを import する必要がある。
- ランチャー: 利用者のパッケージを `ros2 run` / `ros2 launch` する。
- ビルドボタン: 利用者のワークスペースで `colcon build` する。
- リソース監視・トレース計測: 同じ PC のプロセスを見る。

**原則: 利用者のワークスペースを source したターミナルで起動する。**
```bash
source ~/ros2_ws/install/setup.bash
ros2 run roshanavi app          # ブラウザが開く
```
観察だけ (グラフ・トラフィック) なら、同じ ROS_DOMAIN_ID の別 PC からも動く。独自型は Hz・帯域までで、中身の表示はできない (UI で案内する)。

## 2. 配布形態

| 形態 | 対象 | 内容 |
|---|---|---|
| **ソースから** (当面の本命) | 一般利用者 | ワークスペースの `src/` に clone → `rosdep install` → `colcon build`。Web UI はビルド済みのものを GitHub Releases のソースアーカイブに同梱し、**利用者に npm を要求しない** |
| **apt** (将来の本命) | 一般利用者 | bloom でリリースし `sudo apt install ros-jazzy-roshanavi` (Lyrical は `ros-lyrical-roshanavi`)。Web UI はパッケージに同梱 |
| **Docker イメージ** | お試し・CI | `docker compose up` でデモ一式が動く。CI ではシナリオの実行に使う。日常の開発用途には推奨しない (利用者のノードと環境が分かれるため) |
| pip | 対象外 | rclpy が pip で配布されていないため |

## 3. パッケージ構成 (予定)
- `roshanavi`: 本体 (Python。サーバー、ダミーノード、シナリオ CLI)
- `roshanavi_msgs`: 内部用の msg (計測ノードの統計など)
- `roshanavi_probe`: C++ 計測ノード ([measurement.md#C++ 計測ノード](../design/measurement.md#c-計測ノード-roshanavi_probe-p46))
- `roshanavi_examples`: サンプルノード (P5)

依存はすべて rosdep キーで解決できるものに限る (python3-fastapi、python3-uvicorn、python3-psutil、ffmpeg など)。追加の pip パッケージは使わない。

## 4. 起動の形
- `ros2 run roshanavi app`: 既定の起動。カレントディレクトリをワークスペースとして扱い、ブラウザを開く。
- `ros2 launch roshanavi roshanavi.launch.py workspace:=~/ros2_ws`: launch ファイルから。既存の bringup に組み込む場合にも使える。
- 起動時のチェック: ワークスペースが source されていない、ROS_DOMAIN_ID が異なる、などを検出して平易に案内する。

## 5. ポート
- 既定のポートは **6871** (8080 はよく使われるため変更)。`--port` で変更できる。
- 選定理由:
  - ROS 2 (DDS/RTPS) が使うポート範囲 (7400 + 250 × ドメイン ID + α。ドメイン 0〜101 で約 7400〜32900) より下にあり、ROS の通信と衝突しない。
  - Linux の一時ポート範囲 (32768〜60999) と重ならない。
  - よく使われる開発用ポート (3000, 5000, 5173, 8000, 8080, 8888)、X11 (6000〜6063)、Redis (6379)、Kubernetes (6443) を避けている。

## 6. 複数 PC 構成
- roshanavi は開発 PC で動かす。ロボット PC のノードも、同じドメインなら地図とトラフィックに現れる。
- ランチャーとリソース監視は、roshanavi が動いている PC のみ (他 PC の対応は Lv2 の将来課題)。
