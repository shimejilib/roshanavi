// UI strings for the map: per-publisher rates and node controls (merged into `ja`).

export const mapJa = {
  'graph.rate.estimated': '推定',
  'graph.rate.estimatedHelp': 'この送信元の値は推定です: トピック全体の受信量から、roshanavi が送っている分 (正確に分かる) を引いて求めています。ROS 2 (Jazzy) では受信したメッセージがどの送信元のものか区別できないためです。',
  'graph.rate.configured': 'パラメータ',
  'graph.rate.configuredHelp': 'ダミーノードの設定 (周期) の値です。実際の送信数は数えていません。',
  'graph.rate.exactHelp': 'roshanavi が実際に送った件数から求めた値です。',
  'graph.rate.unknownHelp': '送信元が複数あるため、送信元ごとの値は分かりません (トピックの合計を見てください)。',
  'graph.rate.total': '合計 {hz} / 送信元 {n}',

  'control.title': 'ノードの操作',
  'control.start': '起動',
  'control.stop': '停止',
  'control.restart': '再起動',
  'control.stopJob': 'ジョブを停止',
  'control.menuLabel': '{node} の操作',
  'control.notOwned': 'roshanavi が起動したノードではないため停止できません。ランチャーから起動すると操作できます',
  'control.confirmTitle': '停止の確認',
  'control.confirmSingle': '{node} を停止します。よろしいですか?',
  'control.confirmLaunch': 'このノードは launch ファイル {file} で起動されています。停止すると次の {n} 個のノードも停止します: {nodes}',
  'control.confirmGroup': 'このノードは起動リストの {target} のプロセスで動いています。停止すると次の {n} 個のノードも停止します: {nodes}',
  'control.confirmRestart': '再起動すると、次の {n} 個のノードもいったん停止します: {nodes}',
  'control.confirmOk': '停止する',
  'control.confirmRestartOk': '再起動する',
  'control.done': '{action}しました',
} as const;
