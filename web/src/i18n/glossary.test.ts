import { describe, expect, it } from 'vitest';
import { GLOSSARY, glossaryViolations, termMessages, termPair, type GlossaryId } from './glossary';
import { ja, type MessageKey } from './messages';

describe('glossary', () => {
  it('pairs the plain word with the ROS term, plain first', () => {
    expect(termPair('topic')).toBe('チャンネル (トピック)');
    expect(termPair('qos')).toBe('届け方の設定 (QoS)');
    expect(termPair('parameter')).toBe('設定値 (パラメータ)');
    expect(termPair('launch')).toBe('起動セット (launch ファイル)');
    expect(termPair('node')).toBe('ノード');
    expect(termPair('topic', 'en')).toBe('channel (topic)');
  });

  it('explains ノード as a box of processing', () => {
    expect(GLOSSARY.node.explain.ja).toContain('処理の箱');
  });

  it('has the same structure in every language', () => {
    for (const entry of Object.values(GLOSSARY)) {
      for (const field of ['ros', 'plain', 'explain'] as const) {
        expect(entry[field].ja, `${entry.id}.${field}.ja`).toBeTruthy();
        expect(entry[field].en, `${entry.id}.${field}.en`).toBeTruthy();
      }
    }
  });

  it('builds the term tooltips', () => {
    const terms = termMessages();
    for (const id of Object.keys(GLOSSARY) as GlossaryId[]) expect(ja[`term.${id}` as MessageKey]).toBe(terms[`term.${id}`]);
  });

  it('finds raw ROS terms outside the pair and outside code spans', () => {
    expect(glossaryViolations('トピック名を入力')).toEqual(['topic']);
    expect(glossaryViolations('チャンネル (トピック) 名を入力')).toEqual([]);
    expect(glossaryViolations('`ros2 topic echo /x` で見られます')).toEqual([]);
    expect(glossaryViolations('設定値のファイル (パラメータファイル) を読む')).toEqual([]);
    expect(glossaryViolations('パラメータファイルを読む')).toEqual(['paramsFile']);
    expect(glossaryViolations('launch に書き出し')).toEqual(['launch']);
    expect(glossaryViolations('ros2 launch my_pkg x.launch.py で起動')).toEqual([]);
    expect(glossaryViolations('送信側と QoS が合いません')).toEqual(['qos']);
  });

  // Every UI string goes through the glossary (docs/design/wiring.md, wording audit).
  it('every UI string uses the glossary for ROS terms', () => {
    const bad = Object.entries(ja)
      .map(([key, text]) => [key, glossaryViolations(text)] as const)
      .filter(([, ids]) => ids.length > 0)
      .map(([key, ids]) => `${key}: ${ids.join(', ')}`);
    expect(bad).toEqual([]);
  });
});
