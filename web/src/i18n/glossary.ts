// The one glossary of ROS terms (docs/design/wiring.md, wording audit). Every UI string says the
// plain word first; where the ROS term helps (so the user can search for it or recognise it in
// other tools), it follows in parentheses, always in the same form: `チャンネル (トピック)`.
// glossary.test.ts checks every UI string: a ROS term may only appear inside that pair (or in a
// `code span`, e.g. a command). The term tooltips (`<Term>`, `term.*`) come from here too.
// Each entry has the same structure in every language (only `ja` is shown today).

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
  /** The ROS term (what the ROS docs and `ros2` commands call it). */
  ros: Words;
  /** The plain word used in sentences. Same as `ros` when the ROS word is plain enough. */
  plain: Words;
  /** One-line explanation (tooltip of `<Term>`, the guide's glossary). */
  explain: Words;
  /** Raw uses of the ROS term in a Japanese UI string; they must be written as the pair. */
  raw?: RegExp;
}

export const GLOSSARY: Readonly<Record<GlossaryId, GlossaryEntry>> = {
  node: {
    id: 'node',
    ros: { ja: 'ノード', en: 'node' },
    plain: { ja: 'ノード', en: 'node' },
    explain: {
      ja: 'ノード = 処理の箱。データを受け取り、処理して、送り出す 1 つのプログラムです。地図の角丸の四角',
      en: 'node = a box of processing: one program that receives data, works on it and sends it on. The rounded boxes on the map',
    },
  },
  topic: {
    id: 'topic',
    ros: { ja: 'トピック', en: 'topic' },
    plain: { ja: 'チャンネル', en: 'channel' },
    explain: {
      ja: 'チャンネル (トピック) = 名前の付いたデータの通り道。ノードはチャンネルに送り、チャンネルを購読して受け取ります。地図の楕円',
      en: 'channel (topic) = a named path for data. Nodes send to a channel and subscribe to a channel to receive. The ovals on the map',
    },
    raw: /トピック/,
  },
  publisher: {
    id: 'publisher',
    ros: { ja: 'パブリッシャー', en: 'publisher' },
    plain: { ja: '送信側', en: 'sender' },
    explain: {
      ja: '送信側 (パブリッシャー) = チャンネルにデータを送るノード (の口)',
      en: 'sender (publisher) = a node (or its port) that sends data to a channel',
    },
    raw: /パブリッシャ|publisher/i,
  },
  subscriber: {
    id: 'subscriber',
    ros: { ja: 'サブスクライバー', en: 'subscriber' },
    plain: { ja: '受信側', en: 'receiver' },
    explain: {
      ja: '受信側 (サブスクライバー) = チャンネルを購読してデータを受け取るノード (の口)',
      en: 'receiver (subscriber) = a node (or its port) that subscribes to a channel and receives its data',
    },
    raw: /サブスクライバ|subscriber/i,
  },
  qos: {
    id: 'qos',
    ros: { ja: 'QoS', en: 'QoS' },
    plain: { ja: '届け方の設定', en: 'delivery settings' },
    explain: {
      ja: '届け方の設定 (QoS) = 確実に届けるか、後から来た受信側にも渡すか、などの約束。送信側と受信側で合わないと届きません',
      en: 'delivery settings (QoS) = promises such as "always deliver" or "also give it to late joiners". Sender and receiver must agree or nothing arrives',
    },
    raw: /QoS/,
  },
  parameter: {
    id: 'parameter',
    ros: { ja: 'パラメータ', en: 'parameter' },
    plain: { ja: '設定値', en: 'setting' },
    explain: {
      ja: '設定値 (パラメータ) = ノードの設定 (周期、しきい値など)。起動時に渡したり、動いている間に変えたりできます',
      en: 'setting (parameter) = a value that configures a node (a period, a threshold ...). Given at start or changed while it runs',
    },
    raw: /パラメータ(?!ファイル)/,
  },
  paramsFile: {
    id: 'paramsFile',
    ros: { ja: 'パラメータファイル', en: 'parameter file' },
    plain: { ja: '設定値のファイル', en: 'settings file' },
    explain: {
      ja: '設定値のファイル (パラメータファイル) = 設定値をまとめて書いた YAML ファイル',
      en: 'settings file (parameter file) = a YAML file with many settings at once',
    },
    raw: /パラメータファイル/,
  },
  launch: {
    id: 'launch',
    ros: { ja: 'launch ファイル', en: 'launch file' },
    plain: { ja: '起動セット', en: 'start set' },
    explain: {
      ja: '起動セット (launch ファイル) = 複数のノードを、設定ごとまとめて起動するファイル',
      en: 'start set (launch file) = a file that starts several nodes with their settings at once',
    },
    // `ros2 launch`, `--launch`, `*.launch.py` and identifiers are not the term itself.
    raw: /(?<!ros2 )(?<![-\w./])launch(?![\w./])/,
  },
  msgType: {
    id: 'msgType',
    ros: { ja: 'メッセージ型', en: 'message type' },
    plain: { ja: 'データの形', en: 'data shape' },
    explain: {
      ja: 'データの形 (メッセージ型) = チャンネルに流すデータの形。roshanavi では「データの種類」(文字列・画像 …) を選べば決まります (例: 文字列なら std_msgs/msg/String)',
      en: 'data shape (message type) = the shape of the data on a channel. In roshanavi, choosing a data kind (text, image ...) decides it (text is std_msgs/msg/String)',
    },
    raw: /メッセージ型/,
  },
  remap: {
    id: 'remap',
    ros: { ja: 'リマップ', en: 'remap' },
    plain: { ja: '名前の付け替え', en: 'renaming' },
    explain: {
      ja: '名前の付け替え (リマップ) = ノードの中で決まっているチャンネル名などを、起動時に別の名前にすること',
      en: 'renaming (remap) = giving a channel (or another name fixed in the code) a different name when the node starts',
    },
    raw: /リマップ/,
  },
  namespace: {
    id: 'namespace',
    ros: { ja: '名前空間', en: 'namespace' },
    plain: { ja: '名前空間', en: 'namespace' },
    explain: {
      ja: '名前空間 = ノードやチャンネルの名前の前に付く「フォルダ」のようなもの (例: /robot1)',
      en: 'namespace = a "folder" in front of node and channel names (e.g. /robot1)',
    },
  },
  package: {
    id: 'package',
    ros: { ja: 'パッケージ', en: 'package' },
    plain: { ja: 'パッケージ', en: 'package' },
    explain: {
      ja: 'パッケージ = ノードや起動セット (launch ファイル) をまとめた単位',
      en: 'package = the unit that holds nodes and start sets (launch files)',
    },
  },
  workspace: {
    id: 'workspace',
    ros: { ja: 'ワークスペース', en: 'workspace' },
    plain: { ja: 'ワークスペース', en: 'workspace' },
    explain: {
      ja: 'ワークスペース = 自分のパッケージのソース (src/) とビルド結果 (install/) が入ったフォルダ',
      en: 'workspace = the folder with your packages\' sources (src/) and build results (install/)',
    },
  },
  executable: {
    id: 'executable',
    ros: { ja: '実行ファイル', en: 'executable' },
    plain: { ja: '実行ファイル', en: 'executable' },
    explain: {
      ja: '実行ファイル = ros2 run で起動するノードのプログラム',
      en: 'executable = the program of a node that ros2 run starts',
    },
  },
  lifecycle: {
    id: 'lifecycle',
    ros: { ja: 'ライフサイクルノード', en: 'lifecycle node' },
    plain: { ja: 'ライフサイクルノード', en: 'lifecycle node' },
    explain: {
      ja: 'ライフサイクルノード = 「設定済み」「動作中」のような段階を ROS が管理するノード。決まった順番で段階を進めて使います',
      en: 'lifecycle node = a node whose stages ("configured", "active" ...) ROS manages; it is moved through them in a fixed order',
    },
  },
  rate: {
    id: 'rate',
    ros: { ja: 'Hz', en: 'Hz' },
    plain: { ja: '1 秒あたりの回数', en: 'times per second' },
    explain: {
      ja: '1 秒間に何回送るか (1 Hz = 1 秒に 1 回)',
      en: 'how many times per second (1 Hz = once a second)',
    },
  },
};

export type Lang = keyof Words;

/** `チャンネル (トピック)`; the plain word alone when it is the ROS word itself (ノード). */
export function termPair(id: GlossaryId, lang: Lang = 'ja'): string {
  const entry = GLOSSARY[id];
  return entry.plain[lang] === entry.ros[lang] ? entry.plain[lang] : `${entry.plain[lang]} (${entry.ros[lang]})`;
}

/** The plain word (`チャンネル`). */
export function plainWord(id: GlossaryId, lang: Lang = 'ja'): string {
  return GLOSSARY[id].plain[lang];
}

/** `term.<id>` tooltips for `<Term>`, built from the glossary (one source). */
export function termMessages(lang: Lang = 'ja'): Record<`term.${GlossaryId}`, string> {
  const out = {} as Record<`term.${GlossaryId}`, string>;
  for (const entry of Object.values(GLOSSARY)) out[`term.${entry.id}`] = entry.explain[lang];
  return out;
}

const CODE_SPAN = /`[^`]*`/g;
const PLACEHOLDER = /\{\w+\}/g;

/** The parts of a UI string that break the glossary: raw ROS terms outside `plain (ros)` and
 *  outside `code spans` (`{placeholders}` are values, not words). Empty = the string follows the glossary. */
export function glossaryViolations(text: string): GlossaryId[] {
  let rest = text.replace(CODE_SPAN, ' ').replace(PLACEHOLDER, ' ');
  // Longest pairs first: 設定値のファイル (パラメータファイル) before 設定値 (パラメータ).
  const entries = Object.values(GLOSSARY).sort((a, b) => b.ros.ja.length - a.ros.ja.length);
  for (const entry of entries) {
    if (entry.plain.ja !== entry.ros.ja) rest = rest.split(`${entry.plain.ja} (${entry.ros.ja})`).join(' ');
  }
  return entries.filter((entry) => entry.raw?.test(rest)).map((entry) => entry.id);
}
