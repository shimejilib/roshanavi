// UI strings for the diagnostics (docs/design/map-and-traffic.md#診断) and the leak wording
// (docs/design/resources.md#メモリリークの見せ方); merged into `ja`.

export const diagJa = {
  // Info (quiet): not counted in the badge, shown on the map and in topic / node details.
  'diag.no_subscriber': '{topic} を受信しているノードはまだありません (今は送信だけです)',
  'diag.no_publisher': '{topic} に送信しているノードはまだありません (今は受信待ちです)',
  'diag.quiet.no_subscriber': '受信なし',
  'diag.quiet.no_publisher': '送信なし',
  'diag.similar_names':
    '{published} (送信) と {subscribed} (受信) は名前が似ていて、つながっていません。打ち間違いや名前の付け替え (リマップ) 漏れではありませんか?',
  'diag.subscriber_lost': 'さっきまで {who} が {topic} を受信していましたが、いなくなりました',
  'diag.publisher_lost': 'さっきまで {who} が {topic} に送信していましたが、いなくなりました',
  'diag.mine_no_input': '開発中のノード {node} の入力 {topic} に送信元がいません',
  // Memory growth (docs/design/resources.md#メモリリークの見せ方)
  'diag.mem_leak': '{who} のメモリが毎分 {rate} MB で {duration}増え続けています (減速なし)。メモリリークの疑いがあります',
  'diag.gpu_mem_leak': '{who} の GPU メモリが毎分 {rate} MB で {duration}増え続けています (減速なし)。解放し忘れの疑いがあります',
  'diag.who.self': 'roshanavi 自身 ({label})',
  'res.leak.suspect': '毎分 {rate} MB で {duration}増え続けています (減速なし)。リークの疑い',
  'res.leak.watch': '増加中ですが、増え方は収まりつつあります (様子見)',
  'res.leak.watchHelp': 'メモリが増えましたが、増え方は小さくなっています。バッファが埋まる途中や、一度だけの増加によくあるパターンです。増え続けるようなら「リークの疑い」に変わります。',
  'res.duration.min': '{n} 分',
  'res.duration.hour': '{n} 時間',
} as const;
