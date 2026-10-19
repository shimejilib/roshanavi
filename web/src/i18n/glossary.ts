// The one glossary of ROS terms (docs/design/wiring.md, glossary section).
//
// Rule (user decision, reverses the earlier wording audit): the OFFICIAL ROS term is THE word in every
// UI string, tour, guide page and backend message: トピック, パラメータ, パラメータファイル,
// launch ファイル, QoS, メッセージ型, リマップ, ノード. One name per concept, so that a user can
// match the UI with the ROS docs, `ros2 topic ...`, error messages and Q&A threads. The plain-language
// explanation lives only in the term tooltips (`<Term>`, ⓘ / hover, the `term.*` messages built from
// `explain` below), in the pub/sub primer and in the guide's 用語集. The plain words that used to
// replace the terms (`avoid`) must NOT appear in any other UI string: glossary.test.ts fails on them.
// 送信側 / 受信側 stay as direction words in running sentences ("the side that sends / receives");
// the concept names パブリッシャー / サブスクライバー are used where the ROS role itself is named
// (tooltips, primer, labels). Each entry has the same structure in every language (only `ja` is shown today).

export type GlossaryId =
  | 'node' | 'topic' | 'publisher' | 'subscriber' | 'qos' | 'parameter' | 'paramsFile'
  | 'launch' | 'msgType' | 'remap' | 'namespace' | 'package' | 'workspace' | 'executable'
  | 'lifecycle' | 'rate';

export interface Words {
  ja: string;
  en: string;
}

export interface GlossaryEntry {
  id: GlossaryId;
  /** The ROS term (what the ROS docs and `ros2` commands call it). THE word in every UI string. */
  ros: Words;
  /** One-line plain-language explanation (tooltip of `<Term>`, the guide's 用語集). Starts with the term. */
  explain: Words;
  /** The old plain-word replacement (earlier wording audit). Allowed only in `explain`; a UI string using it fails the test. */
  avoid?: RegExp;
}

export const GLOSSARY: Readonly<Record<GlossaryId, GlossaryEntry>> = {
  node: {
    id: 'node',
    ros: { ja: 'ノード', en: 'node' },
    explain: {
      ja: 'ノード = 処理の箱。データを受け取り、処理して、送り出す 1 つのプログラムです。地図の角丸の四角',
      en: 'node = a box of processing: one program that receives data, works on it and sends it on. The rounded boxes on the map',
    },
  },
  topic: {
    id: 'topic',
    ros: { ja: 'トピック', en: 'topic' },
    explain: {
      ja: 'トピック = 名前の付いたデータの通り道 (チャンネルのようなもの)。ノードはトピックに送り、トピックを購読して受け取ります。地図の楕円',
      en: 'topic = a named path for data (like a channel). Nodes send to a topic and subscribe to a topic to receive. The ovals on the map',
    },
    avoid: /チャンネル(?!数|変換)/,
  },
  publisher: {
    id: 'publisher',
    ros: { ja: 'パブリッシャー', en: 'publisher' },
    explain: {
      ja: 'パブリッシャー = トピックにデータを送る側 (送信側) のノード (の口)',
      en: 'publisher = the sending side: a node (or its port) that sends data to a topic',
    },
  },
  subscriber: {
    id: 'subscriber',
    ros: { ja: 'サブスクライバー', en: 'subscriber' },
    explain: {
      ja: 'サブスクライバー = トピックを購読してデータを受け取る側 (受信側) のノード (の口)',
      en: 'subscriber = the receiving side: a node (or its port) that subscribes to a topic and receives its data',
    },
  },
  qos: {
    id: 'qos',
    ros: { ja: 'QoS', en: 'QoS' },
    explain: {
      ja: 'QoS = 届け方の設定。確実に届けるか、後から来た受信側にも渡すか、などの約束。送信側と受信側で合わないと届きません',
      en: 'QoS = delivery settings: promises such as "always deliver" or "also give it to late joiners". Sender and receiver must agree or nothing arrives',
    },
    avoid: /届け方の設定/,
  },
  parameter: {
    id: 'parameter',
    ros: { ja: 'パラメータ', en: 'parameter' },
    explain: {
      ja: 'パラメータ = ノードの設定値 (周期、しきい値など)。起動時に渡したり、動いている間に変えたりできます',
      en: 'parameter = a setting of a node (a period, a threshold ...). Given at start or changed while it runs',
    },
    avoid: /設定値/,
  },
  paramsFile: {
    id: 'paramsFile',
    ros: { ja: 'パラメータファイル', en: 'parameter file' },
    explain: {
      ja: 'パラメータファイル = パラメータをまとめて書いた YAML ファイル (設定値のファイル)',
      en: 'parameter file = a YAML file with many parameters at once (a settings file)',
    },
  },
  launch: {
    id: 'launch',
    ros: { ja: 'launch ファイル', en: 'launch file' },
    explain: {
      ja: 'launch ファイル = 複数のノードを、パラメータごとまとめて起動するファイル (起動セット)',
      en: 'launch file = a file that starts several nodes with their parameters at once (a start set)',
    },
    avoid: /起動セット/,
  },
  msgType: {
    id: 'msgType',
    ros: { ja: 'メッセージ型', en: 'message type' },
    explain: {
      ja: 'メッセージ型 = トピックに流すデータの形。roshanavi では「データの種類」(文字列・画像 …) を選べば決まります (例: 文字列なら std_msgs/msg/String)',
      en: 'message type = the shape of the data on a topic. In roshanavi, choosing a data kind (text, image ...) decides it (text is std_msgs/msg/String)',
    },
    avoid: /データの形(?!式)/,
  },
  remap: {
    id: 'remap',
    ros: { ja: 'リマップ', en: 'remap' },
    explain: {
      ja: 'リマップ = 名前の付け替え。ノードの中で決まっているトピック名などを、起動時に別の名前にすること',
      en: 'remap = renaming: giving a topic (or another name fixed in the code) a different name when the node starts',
    },
    avoid: /名前の付け替え/,
  },
  namespace: {
    id: 'namespace',
    ros: { ja: '名前空間', en: 'namespace' },
    explain: {
      ja: '名前空間 = ノードやトピックの名前の前に付く「フォルダ」のようなもの (例: /robot1)',
      en: 'namespace = a "folder" in front of node and topic names (e.g. /robot1)',
    },
  },
  package: {
    id: 'package',
    ros: { ja: 'パッケージ', en: 'package' },
    explain: {
      ja: 'パッケージ = ノードや launch ファイルをまとめた単位',
      en: 'package = the unit that holds nodes and launch files',
    },
  },
  workspace: {
    id: 'workspace',
    ros: { ja: 'ワークスペース', en: 'workspace' },
    explain: {
      ja: 'ワークスペース = 自分のパッケージのソース (src/) とビルド結果 (install/) が入ったフォルダ',
      en: 'workspace = the folder with your packages\' sources (src/) and build results (install/)',
    },
  },
  executable: {
    id: 'executable',
    ros: { ja: '実行ファイル', en: 'executable' },
    explain: {
      ja: '実行ファイル = ros2 run で起動するノードのプログラム',
      en: 'executable = the program of a node that ros2 run starts',
    },
  },
  lifecycle: {
    id: 'lifecycle',
    ros: { ja: 'ライフサイクルノード', en: 'lifecycle node' },
    explain: {
      ja: 'ライフサイクルノード = 「設定済み」「動作中」のような段階を ROS が管理するノード。決まった順番で段階を進めて使います',
      en: 'lifecycle node = a node whose stages ("configured", "active" ...) ROS manages; it is moved through them in a fixed order',
    },
  },
  rate: {
    id: 'rate',
    ros: { ja: 'Hz', en: 'Hz' },
    explain: {
      ja: 'Hz = 1 秒間に何回送るか (1 Hz = 1 秒に 1 回)',
      en: 'Hz = how many times per second (1 Hz = once a second)',
    },
  },
};

export type Lang = keyof Words;

/** The official ROS term, the one word every UI string uses (`トピック`, `launch ファイル`). */
export function termWord(id: GlossaryId, lang: Lang = 'ja'): string {
  return GLOSSARY[id].ros[lang];
}

/** `term.<id>` tooltips for `<Term>`, built from the glossary (one source). */
export function termMessages(lang: Lang = 'ja'): Record<`term.${GlossaryId}`, string> {
  const out = {} as Record<`term.${GlossaryId}`, string>;
  for (const entry of Object.values(GLOSSARY)) out[`term.${entry.id}`] = entry.explain[lang];
  return out;
}

const CODE_SPAN = /`[^`]*`/g;

/** Old plain words (earlier wording audit) that replaced a ROS term. They may stay in a tooltip (`term.*`) but nowhere else.
 *  Empty = the string follows the glossary. `code spans` are skipped. */
export function glossaryViolations(text: string): GlossaryId[] {
  const rest = text.replace(CODE_SPAN, ' ');
  return Object.values(GLOSSARY).filter((entry) => entry.avoid?.test(rest)).map((entry) => entry.id);
}
