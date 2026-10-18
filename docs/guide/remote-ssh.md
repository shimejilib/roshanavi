# 別のマシンから roshanavi を見る (SSH)

roshanavi は、安全のため、動いている PC の中 (localhost) からしか開けません。別のマシン (手元のノート PC など) から見たいときは、**SSH のポート転送** を使います。roshanavi 側の設定は何も変えずに使えます。

## できること・できないこと

| | |
|---|---|
| できる | 開発 PC やロボットの PC で動く roshanavi を、手元のブラウザで見て操作する。通信は SSH で暗号化される。**手元のブラウザのマイク・カメラも使える** (ブラウザからは localhost へのアクセスに見えるため) |
| できない | SSH のアカウントを持たない人に見せる、「見るだけ」の権限で渡す、誰が何を操作したかの記録。SSH で入れる人は、すべての操作ができます |

チームで共有したい、権限を分けたい、という場合のための仕組み (デバイスの登録と権限) は、今後の予定です ([docs/planned/remote-access.md](../planned/remote-access.md))。

## 手順

### 1. つなぐ

手元のマシンで実行します。`開発PC` は、roshanavi が動いている PC のホスト名か IP アドレスです。

```bash
ssh -L 6871:localhost:6871 ユーザー名@開発PC
```

この SSH の接続を開いたまま、手元のブラウザで http://localhost:6871 を開きます。

- 別のポートで動かしている roshanavi (例: 6872) を見るときは、`-L 6872:localhost:6872` のように両方の番号を合わせます。複数を同時に見るときは `-L` を並べます。
- 手元で 6871 が使用中なら、手元側の番号だけ変えます (例: `-L 7000:localhost:6871` → http://localhost:7000)。
- **`-g` や `-L 0.0.0.0:…` は使わないでください。** 手元のマシンのネットワーク上の誰でも roshanavi を操作できるようになってしまいます。

毎回打つのが面倒なら、手元の `~/.ssh/config` に書いておきます。

```
Host roshanavi-dev
    HostName 開発PCのホスト名
    User ユーザー名
    LocalForward 6871 localhost:6871
```

以後は `ssh roshanavi-dev` だけでつながります。

### 2. roshanavi を Docker で動かしている場合

`docker compose` の既定の設定は、roshanavi のポートを開発 PC の `127.0.0.1:6871` に出しています。そのため、上の手順がそのまま使えます (SSH の転送先の `localhost:6871` が、そのポートを指します)。

### 3. 開発 PC が Windows + WSL2 の場合

roshanavi が WSL2 の中で動いている場合、手元のマシンから WSL2 に SSH で入る準備が必要です。どちらか一方を選びます。

**方法 A: WSL2 の中に SSH サーバーを立てる** (WSL2 のネットワークを mirrored にしている場合に簡単)

1. Windows の `%UserProfile%\.wslconfig` に次を書き、`wsl --shutdown` で WSL を再起動します (Windows 11 の新しめの版が必要です)。
   ```
   [wsl2]
   networkingMode=mirrored
   ```
2. WSL の中で SSH サーバーを入れて起動します。
   ```bash
   sudo apt install openssh-server && sudo service ssh start
   ```
3. 手元のマシンから、Windows の IP アドレスに向けて「1. つなぐ」の手順を行います (WSL の SSH サーバーが、Windows のアドレスで受け付けます)。Windows のファイアウォールで、SSH (22 番) の受け付けを許可する必要がある場合があります。

**方法 B: Windows の SSH サーバーを経由する**

Windows の「オプション機能」から OpenSSH サーバーを有効にし、手元のマシンから Windows に SSH で入ります。roshanavi のポートは、WSL2 の localhost 転送により Windows の `localhost:6871` からも見えるので、「1. つなぐ」の手順がそのまま使えます。

### 4. ロボットの PC で動かしている場合

ロボットの PC で roshanavi を動かし、手元の PC から「1. つなぐ」の手順で入ります。ロボットのネットワークに手元の PC がつながっていれば、それだけで使えます。

## うまくいかないとき

| 症状 | 確認すること |
|---|---|
| ブラウザで「接続できません」 | SSH の接続が開いたままか。開発 PC で roshanavi が動いているか (開発 PC で `curl http://localhost:6871/api/health`) |
| 「bind: Address already in use」 | 手元で 6871 が使用中。手元側の番号を変える (`-L 7000:localhost:6871`) |
| 画面は出るが「接続済み」にならない | SSH の接続が途中で切れていないか。長時間使うなら `ssh -o ServerAliveInterval=30 …` |
| 403 (forbidden_host) と出る | ブラウザで `localhost` 以外の名前 (開発 PC のホスト名など) で開いていないか。必ず `http://localhost:6871` で開く |
