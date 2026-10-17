"""``ros2 run roshanavi scenario run <file|dir> [--junit out.xml] [--json out.json]``.

Exit codes: 0 every scenario passed, 1 any failed (including invalid files),
2 bad arguments (path not found, no scenario files in the directory).
"""

import argparse
import json
import logging
import os
import sys
from typing import List, Optional, Sequence

from .junit import to_junit
from .result import CANCELLED, ERROR, FAILED, PASSED, SKIPPED, Result

MARKS = {PASSED: '✔', FAILED: '✘', ERROR: '✘', SKIPPED: '-', CANCELLED: '■'}
SCENARIO_EXTS = ('.yaml', '.yml')


def scenario_files(path: str) -> List[str]:
    if os.path.isdir(path):
        return sorted(os.path.join(path, n) for n in os.listdir(path)
                      if n.endswith(SCENARIO_EXTS) and not n.startswith('.')
                      and os.path.isfile(os.path.join(path, n)))
    return [path]


def report(result: Result, out=sys.stdout) -> None:
    print(f'\n== {result.name} ({result.file})', file=out)
    for err in result.schema_errors:
        where = f' ({err["line"]} 行目)' if err.get('line') else ''
        print(f'  ✘ {err["path"] or "(全体)"}{where}: {err["message"]}', file=out)
    for s in result.setup:
        print(f'  {MARKS.get(s.status, "?")} セットアップ {s.index + 1}: {s.summary}'
              + (f'\n      {s.message}' if s.status != PASSED else ''), file=out)
        for line in s.log_tail if s.status == FAILED else []:
            print(f'      | {line}', file=out)
    for s in result.steps:
        mark = MARKS.get(s.status, '?')
        print(f'  {mark} {s.index + 1}. {s.summary}', file=out)
        if s.status in (FAILED, ERROR) or (s.status == PASSED and s.kind in (
                'rate', 'throughput', 'latency')):
            print(f'      {s.message}', file=out)
        for hint in s.hints:
            print(f'      原因の候補: {hint["message"]}', file=out)
    for g in result.guards:
        print(f'  {MARKS.get(g.status, "?")} ガード {g.index + 1}: {g.summary}'
              + (f'\n      {g.message}' if g.status == FAILED else ''), file=out)
    verdict = {PASSED: '成功', FAILED: '失敗', ERROR: '失敗 (エラー)',
               CANCELLED: '中止'}.get(result.status, result.status)
    print(f'  → {verdict} ({result.duration_sec:.1f} 秒) {result.message}', file=out)


def _write(path: Optional[str], text: str) -> None:
    if not path:
        return
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write(text)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='ros2 run roshanavi scenario',
                                     description='roshanavi のシナリオを実行する')
    sub = parser.add_subparsers(dest='command', required=True)
    run = sub.add_parser('run', help='シナリオ (ファイルかディレクトリ) を実行する')
    run.add_argument('path', help='シナリオの YAML、またはそれが入ったディレクトリ')
    run.add_argument('--junit', help='JUnit XML の出力先')
    run.add_argument('--json', help='結果の JSON の出力先')
    run.add_argument('--data-dir', help='stream / bag / メディアのファイルの場所 '
                     '(既定: $ROSHANAVI_DATA_DIR かカレントディレクトリ)')
    run.add_argument('--workspace', help='colcon のワークスペース (既定: $ROSHANAVI_WORKSPACE か '
                     'カレントディレクトリ)')
    run.add_argument('--project', help='target: で使う roshanavi.yaml')
    run.add_argument('-v', '--verbose', action='store_true')
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format='%(levelname)s %(name)s: %(message)s')
    if not os.path.exists(args.path):
        print(f'見つかりません: {args.path}', file=sys.stderr)
        return 2
    files = scenario_files(args.path)
    if not files:
        print(f'{args.path} にシナリオ (*.yaml) がありません', file=sys.stderr)
        return 2
    from ..ros_runtime import RosRuntime
    from .api import RUNTIME_NODE, run_scenario
    runtime = RosRuntime(RUNTIME_NODE)
    runtime.start()
    results: List[Result] = []
    try:
        for path in files:
            result = run_scenario(path, data_dir=args.data_dir, workspace=args.workspace,
                                  project=args.project, runtime=runtime)
            results.append(result)
            report(result)
    except KeyboardInterrupt:
        print('中止しました', file=sys.stderr)
    finally:
        runtime.stop()
    _write(args.junit, to_junit(results))
    _write(args.json, json.dumps({'results': [r.to_dict() for r in results]}, ensure_ascii=False,
                                 indent=2))
    passed = sum(1 for r in results if r.passed)
    print(f'\n{passed}/{len(files)} シナリオが成功しました')
    return 0 if passed == len(files) and len(results) == len(files) else 1


if __name__ == '__main__':
    sys.exit(main())
