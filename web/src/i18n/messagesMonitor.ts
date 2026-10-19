// UI strings for "not measured" topics (docs/design/map-and-traffic.md#計測していないトピック):
// a topic roshanavi does not subscribe to (images and point clouds by default) is never shown as
// 受信なし / 未受信 / 分けられない; it says it is not measured, and offers 計測する.
// Merged into `ja`.

export const monitorJa = {
  'monitor.off.heavy': '計測していません (画像などの重いデータは既定でオフ)',
  'monitor.off': '計測していません',
  'monitor.on': '計測する',
  'monitor.onHelp': 'このトピックを購読して計測します (Hz も帯域も測れます)。重いデータは負荷がかかるので、必要なときだけ使ってください。この設定はプロジェクトに保存されます。',
  'monitor.traceHint': 'Hz は詳細計測モードで確認できます',
  'monitor.failed': '計測を始められませんでした',
  'monitor.noBandwidth': '— (詳細計測では帯域は測れません)',
  'monitor.traced': 'トレース',
  'traffic.basis.not_monitored': '計測していません',
  'traffic.basisHelp.not_monitored': 'このトピックは購読していないので、値がありません (受信がないという意味ではありません)。重いデータは既定でオフです。「計測する」で購読して測れます。詳細計測モードがオンなら、Hz はトレースから分かります。',
  'traffic.basis.traced_pub': '実測(トレース)',
  'traffic.basisHelp.traced_pub': '詳細計測モードで、このノードが実際に送った数を数えた値です。購読しないので、データが大きくても測れます。帯域は測れません。',
  'graph.rate.notMonitoredHelp': 'このトピックは計測していません。Hz は詳細計測モードか、トピックを選んで「計測する」で見られます。',
  'graph.rate.tracedHelp': '詳細計測モードで数えた、このノードの送信回数です (帯域は測れません)。',
} as const;
