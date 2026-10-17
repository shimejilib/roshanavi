# roshanavi — メディア入力・録画の設計 (P4)

DESIGN.md §4.6.1 を拡張する。P2 完了後に DESIGN.md へ統合する。

## 1. 方針
- **型は送信先トピックから自動で検出する** (グラフ上の subscriber / publisher の型)。ユーザーに型を選ばせない。
- メディアを msg に変換するには型ごとの知識が要るため、**対応型 (アダプタ) は事前に定義する**。
- 対応外の型は **bag 再生** で扱う (シリアライズ済みデータをそのまま再生するため型を問わない。再生環境に型パッケージがビルド済みであることが前提)。
- 対応外の型にメディアを送ろうとした場合は、bag の利用または録画機能 (§4) を平易に案内する。

## 2. 対応型 (MVP)

| 種類 | 型 | 変換 |
|---|---|---|
| 画像 | `sensor_msgs/msg/Image` | デコードして rgb8 / bgr8 / mono8 (送信先の慣習に合わせ設定可) |
| 画像 | `sensor_msgs/msg/CompressedImage` | JPEG / PNG をそのまま格納 (必要なら再エンコード) |
| 画像付随 | `sensor_msgs/msg/CameraInfo` | 画像と同じ stamp・frame_id で同時送信。既定値またはキャリブレーション YAML |
| 音声 | `audio_common_msgs/msg/AudioData` (+ `AudioInfo` を別トピックに送信) | PCM S16LE。wave/mp3 の区別は AudioInfo で伝える |
| 音声 | `audio_common_msgs/msg/AudioDataStamped` | 上記 + header |
| 音声 | `std_msgs/msg/Int16MultiArray` / `UInt8MultiArray` / `Float32MultiArray` | PCM を配列に直接格納 |

将来の拡張: 独自型の変換を Python で追加できるアダプタのプラグイン機構を用意する (`roshanavi.adapters` の entry point)。

## 3. 入力ソース

| ソース | 内容 |
|---|---|
| 画像ファイル / フォルダ | 単体、または名前順のスライドショーとして周期送信 |
| 動画ファイル (MP4/MKV/AVI) | ffmpeg でフレームに分解して送信。fps・区間・リサイズ・loop を指定可 |
| 音声ファイル (WAV/MP3/FLAC/OGG) | ffmpeg で PCM に変換し、チャンクに分けて送信 |
| **ブラウザのマイク** | getUserMedia → AudioWorklet で PCM チャンク化 → WebSocket → publish |
| **ブラウザのカメラ** | getUserMedia → canvas で JPEG 化 → WebSocket → `CompressedImage` で送信、または `Image` にデコードして送信。CameraInfo を併送 |

### 音声ストリームの再現性
本物のマイク (例: `audio_capture`) と同じ流れ方を再現する。
- サンプルレート、チャンネル数、チャンク長 (既定 1024 サンプル) を送信先に合わせて変換する。
- **実時間ペースで等間隔に送信**する (VAD・音声認識ノードはペースが崩れると誤動作するため)。
- オプション: 揺らぎ (jitter) と欠落を意図的に注入して、取りこぼし耐性をテストできる。

### ブラウザ入力の注意点
- ブラウザのメディア取得はセキュアコンテキストが必要。`localhost` はセキュアとして扱われるので、既定の構成のまま使える。
- WebSocket は既存のセキュリティ middleware (Host/Origin) の対象にする。
- カメラの解像度・fps はブラウザと Web カメラ次第 (目安 640×480・30 fps)。stamp はサーバー受信時刻であり、実カメラより数十 ms 遅れる。UI に明記する。

## 4. 録画 (bag record) と再利用
- **録画ボタン**: 選んだトピックを `ros2 bag record` (mcap) で `data_dir/recordings/<日時>_<名前>/` に保存する。
- 対象はブラウザ入力に限らない。テスト対象ノードの出力も同時に録れる (「前回の正常な出力」の保存や比較に使う)。
- 録った bag はファイル一覧に出て、注入の bag モードやシナリオの `play` から再生できる。
- 典型的な流れ: 自分の声やカメラ映像で 1 回録る → 以後は毎回同じ入力で再現テストを回す。

## 5. 出力の確認 (UI)
- 画像トピック: ビューアで表示する (Image / CompressedImage)。
- 音声トピック: 波形を表示し、ブラウザで再生する。
