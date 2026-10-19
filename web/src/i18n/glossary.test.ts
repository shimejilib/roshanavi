import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { GLOSSARY, glossaryViolations, termMessages, termWord, type GlossaryId } from './glossary';
import { ja, type MessageKey } from './messages';

const SRC = join(__dirname, '..');

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return sourceFiles(path);
    return /\.(ts|tsx)$/.test(name) && !/\.test\.tsx?$/.test(name) ? [path] : [];
  });
}

describe('glossary', () => {
  it('uses the official ROS term as the one word', () => {
    expect(termWord('topic')).toBe('トピック');
    expect(termWord('qos')).toBe('QoS');
    expect(termWord('parameter')).toBe('パラメータ');
    expect(termWord('paramsFile')).toBe('パラメータファイル');
    expect(termWord('launch')).toBe('launch ファイル');
    expect(termWord('msgType')).toBe('メッセージ型');
    expect(termWord('remap')).toBe('リマップ');
    expect(termWord('node')).toBe('ノード');
    expect(termWord('topic', 'en')).toBe('topic');
  });

  it('explains ノード as a box of processing', () => {
    expect(GLOSSARY.node.explain.ja).toContain('処理の箱');
  });

  it('has the same structure in every language and starts each explanation with the term', () => {
    for (const entry of Object.values(GLOSSARY)) {
      for (const field of ['ros', 'explain'] as const) {
        expect(entry[field].ja, `${entry.id}.${field}.ja`).toBeTruthy();
        expect(entry[field].en, `${entry.id}.${field}.en`).toBeTruthy();
      }
      expect(entry.explain.ja.startsWith(entry.ros.ja), `${entry.id} explain starts with the term`).toBe(true);
      expect(entry.explain.en.startsWith(entry.ros.en), `${entry.id} explain.en starts with the term`).toBe(true);
    }
  });

  it('builds the term tooltips', () => {
    const terms = termMessages();
    for (const id of Object.keys(GLOSSARY) as GlossaryId[]) expect(ja[`term.${id}` as MessageKey]).toBe(terms[`term.${id}`]);
  });

  it('finds the old plain words that replaced a ROS term, outside code spans', () => {
    expect(glossaryViolations('チャンネル名を入力')).toEqual(['topic']);
    expect(glossaryViolations('チャンネル (トピック) 名を入力')).toEqual(['topic']);
    expect(glossaryViolations('設定値を変える')).toEqual(['parameter']);
    expect(glossaryViolations('設定値のファイルを読む')).toEqual(['parameter']);
    expect(glossaryViolations('起動セットに書き出し')).toEqual(['launch']);
    expect(glossaryViolations('届け方の設定が合いません')).toEqual(['qos']);
    expect(glossaryViolations('データの形が違います')).toEqual(['msgType']);
    expect(glossaryViolations('名前の付け替えを忘れた')).toEqual(['remap']);
    expect(glossaryViolations('`チャンネル` はコード')).toEqual([]);
    // not the ROS-term replacements: audio channels and "data format"
    expect(glossaryViolations('サンプルレート・チャンネル数')).toEqual([]);
    expect(glossaryViolations('データの形式が正しくありません')).toEqual([]);
    expect(glossaryViolations('トピック名・QoS・パラメータファイル・launch ファイル・リマップ')).toEqual([]);
  });

  // The explanation of a term lives in its tooltip; no other UI string may use the old plain word.
  it('every UI string except the term tooltips uses the ROS term', () => {
    const bad = Object.entries(ja)
      .filter(([key]) => !key.startsWith('term.'))
      .map(([key, text]) => [key, glossaryViolations(text)] as const)
      .filter(([, ids]) => ids.length > 0)
      .map(([key, ids]) => `${key}: ${ids.join(', ')}`);
    expect(bad).toEqual([]);
  });

  it('no source file outside the glossary hard-codes an old plain word', () => {
    const bad = sourceFiles(SRC)
      .filter((path) => !path.endsWith(join('i18n', 'glossary.ts')))
      .filter((path) => Object.values(GLOSSARY).some((entry) => entry.avoid?.test(readFileSync(path, 'utf8'))))
      .map((path) => path.slice(SRC.length + 1));
    expect(bad).toEqual([]);
  });

  it('keeps the plain explanation in the tooltips', () => {
    expect(ja['term.topic' as MessageKey]).toContain('名前の付いたデータの通り道');
    expect(ja['term.qos' as MessageKey]).toContain('届け方の設定');
    expect(ja['term.launch' as MessageKey]).toContain('起動セット');
  });
});
