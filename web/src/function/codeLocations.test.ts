import { describe, expect, it } from 'vitest';
import type { CodeNotice, CodeProblem, CodeProblemCode, DependencyHint, NoticeCode, RequirementsCheck } from '../api/codeTypes';
import type { ModuleEntry } from '../api/functionTypes';
import { ja } from '../i18n/messages';
import {
  addEntry,
  checkCodePath,
  checkModuleName,
  checkPackageName,
  DEFAULT_SCAFFOLD_NAME,
  hostSrcText,
  groupModules,
  missingModuleOf,
  noticeText,
  placeHereText,
  problemText,
  removeEntry,
  requirementsLines,
  rosdepRoute,
  skippedText,
} from './codeLocations';

const PROBLEM_CODES: CodeProblemCode[] = [
  'no_src', 'no_init', 'namespace_package', 'loose_files', 'not_ros_package', 'syntax_error', 'no_members', 'private_only',
  'submodule_empty', 'outside_symlink', 'reserved_name', 'name_collision', 'code_path_invalid',
  'code_path_empty', 'installed_not_found',
];
const NOTICE_CODES: NoticeCode[] = ['slow_import', 'imports_rclpy', 'extension_module', 'extension_no_reload', 'no_hot_reload_installed'];

describe('scaffold name', () => {
  it('accepts ROS package names and the default', () => {
    for (const name of [DEFAULT_SCAFFOLD_NAME, 'a', 'robot_2_brain']) expect(checkPackageName(name)).toBeNull();
  });
  it('refuses what the server refuses, with the rule', () => {
    expect(checkPackageName('My_logic')?.key).toBe('code.scaffold.invalid');
    expect(checkPackageName('1abc')?.key).toBe('code.scaffold.invalid');
    expect(checkPackageName('a-b')?.key).toBe('code.scaffold.invalid');
    expect(checkPackageName('')?.key).toBe('code.scaffold.invalid');
    expect(checkPackageName('a__b')?.key).toBe('code.scaffold.invalidUnderscore');
    expect(checkPackageName('ends_')?.key).toBe('code.scaffold.invalidUnderscore');
    expect(checkPackageName('class')).toEqual({ key: 'code.scaffold.invalidReserved', params: { name: 'class' } });
    expect(checkPackageName('rclpy')?.key).toBe('code.scaffold.invalidReserved');
    expect(checkPackageName('x'.repeat(65))?.key).toBe('code.scaffold.invalidLong');
  });
});

describe('code paths and installed modules', () => {
  it('validates a code path before sending it', () => {
    expect(checkCodePath('/home/u/work/lib', [])).toBeNull();
    expect(checkCodePath('  ', [])?.key).toBe('code.path.empty');
    expect(checkCodePath('a\nb', [])?.key).toBe('code.path.control');
    expect(checkCodePath('x'.repeat(1025), [])?.key).toBe('code.path.long');
    expect(checkCodePath(' /a ', ['/a'])?.key).toBe('code.path.duplicate');
    expect(checkCodePath('/new', Array.from({ length: 20 }, (_, i) => `/p${i}`))?.key).toBe('code.path.full');
  });
  it('validates a module name', () => {
    expect(checkModuleName('vision_lib.filters', [])).toBeNull();
    expect(checkModuleName('bad-name', [])?.key).toBe('code.module.invalid');
    expect(checkModuleName('a..b', [])?.key).toBe('code.module.invalid');
    expect(checkModuleName('roshanavi.server', [])?.key).toBe('code.module.roshanavi');
    expect(checkModuleName('x', ['x'])?.key).toBe('code.module.duplicate');
  });
  it('adds and removes entries without mutating', () => {
    const list = ['/a'];
    expect(addEntry(list, ' /b ')).toEqual(['/a', '/b']);
    expect(addEntry(list, '/a')).toEqual(['/a']);
    expect(removeEntry(['/a', '/b'], '/a')).toEqual(['/b']);
    expect(list).toEqual(['/a']);
  });
});

describe('not-found reasons', () => {
  it('has a plain-Japanese reason for every code, with the real path in it', () => {
    for (const code of PROBLEM_CODES) {
      expect(ja[`code.problem.${code}` as keyof typeof ja], code).toBeTruthy();
      const p: CodeProblem = { code, path: '/ws/src/x', file: '/ws/src/x/y.py', line: 3, message: 'm', module: 'mod', top: 't', kept: '/k', ignored: '/i', kept_scope: 'workspace', ignored_scope: 'code_path', root: '/ws', target: '/out', files: ['a.py'], names: ['_h'] };
      const text = problemText(p);
      expect(text).not.toContain('{');
      expect(text).toMatch(/\/ws\/src\/x|mod|t」/);
    }
  });
  it('says exactly what the design table says', () => {
    expect(problemText({ code: 'no_init', path: '/ws/src/p/p' })).toBe(
      '/ws/src/p/p: Python パッケージとして認識できません。このフォルダに __init__.py (空のファイルでかまいません) を置いてください。',
    );
    expect(problemText({ code: 'not_ros_package', path: '/ws/src/x' })).toContain('ひな形を作る');
    expect(problemText({ code: 'not_ros_package', path: '/ws/src/x' })).toContain('登録した場所');
    expect(problemText({ code: 'syntax_error', file: '/ws/src/p/p/a.py', line: 7, message: 'invalid syntax' })).toBe(
      '/ws/src/p/p/a.py の 7 行目: 構文エラーです (invalid syntax)。直して保存すると一覧に出ます。',
    );
    expect(problemText({ code: 'no_members', file: 'f.py' })).toContain('if __name__ == ... の中は対象外');
    expect(problemText({ code: 'private_only', file: 'f.py', names: ['_a', '_b'] })).toContain('_a, _b は名前が _ で始まるため、内部用');
    const sub = problemText({ code: 'submodule_empty', path: '/ws/src/vision_lib', root: '/ws', command: 'git submodule update --init --recursive' });
    expect(sub).toContain('/ws/src/vision_lib の中身がありません');
    expect(problemText({ code: 'outside_symlink', path: '/ws/src/l', target: '/home/u/x' })).toContain('ワークスペースの外は読み込みません');
    expect(problemText({ code: 'outside_symlink', path: '/b/l', target: '/x', scope: 'code_path' })).toContain('登録した場所の外');
    expect(problemText({ code: 'name_collision', top: 'v', kept: '/a', ignored: '/b', kept_scope: 'workspace', ignored_scope: 'installed' })).toContain(
      '/a (ワークスペース) を使い、/b (インストール済み) は使いません',
    );
  });
  it('shows where the src is on the PC, as plain text, only when the server gave a hint', () => {
    expect(hostSrcText(undefined)).toBeNull();
    expect(hostSrcText(null)).toBeNull();
    expect(hostSrcText('  ')).toBeNull();
    expect(hostSrcText(' roshanavi を clone したフォルダの workspace/ ')).toBe('ホストでは: roshanavi を clone したフォルダの workspace/');
    // Not interpreted: the text stays as it is (React escapes it; there is no link or HTML here).
    expect(hostSrcText('<b>x</b> http://e.example')).toBe('ホストでは: <b>x</b> http://e.example');
  });
  it('shows where to put code with the real roots', () => {
    expect(placeHereText({ scope: 'workspace', root: '/ws/src' })).toContain('/ws/src/<パッケージ名>/<パッケージ名>/logic.py');
    expect(placeHereText({ scope: 'code_path', root: '/home/u/lib' })).toContain('/home/u/lib/src/<名前>/logic.py');
  });
});

describe('module list and notes', () => {
  it('groups modules A, B, C in that order and keeps the server order inside', () => {
    const m = (module: string, scope?: ModuleEntry['scope']): ModuleEntry => ({ module, ros_package: null, file: null, scope });
    const groups = groupModules([m('c.x', 'installed'), m('b.y', 'code_path'), m('a.z'), m('a.w', 'workspace')]);
    expect(groups.map((g) => [g.scope, g.modules.map((x) => x.module)])).toEqual([
      ['workspace', ['a.z', 'a.w']],
      ['code_path', ['b.y']],
      ['installed', ['c.x']],
    ]);
    expect(groups[0]?.label).toBe('ワークスペース (A)');
    expect(groupModules([])).toEqual([]);
  });
  it('explains skipped names and every notice', () => {
    expect(skippedText([{ name: '_h', line: 1, reason: 'private' }, { name: 'demo', line: 4, reason: 'main_guard' }])).toBe(
      '候補にならなかった名前: _h (_ で始まる内部用の名前)、demo (if __name__ == ... の中)',
    );
    for (const code of NOTICE_CODES) {
      const notice: CodeNotice = { code, seconds: 2.5, files: ['fast.so'] };
      expect(noticeText(notice)).not.toContain('{');
    }
    expect(noticeText({ code: 'slow_import', seconds: 2.5 })).toContain('2.5 秒');
    expect(noticeText({ code: 'imports_rclpy' })).toContain('rclpy');
    expect(noticeText({ code: 'extension_module' })).toContain('ホットリロードは効きません');
  });
});

describe('dependencies', () => {
  it('summarizes requirements.txt', () => {
    const req: RequirementsCheck = { file: 'src/p/requirements.txt', ok: 2, exact: true, skipped: [{ line: 4, text: '-r x', reason: 'option' }],
      missing: [{ name: 'torch', spec: '>=2', line: 1 }], mismatched: [{ name: 'numpy', spec: '<1', installed: '1.26.4', line: 2 }] };
    const lines = requirementsLines(req);
    expect(lines.filter((l) => l.bad).map((l) => l.text)).toEqual(['足りないもの: torch>=2', '版が合わないもの: numpy<1 (1.26.4)']);
    expect(lines.map((l) => l.text)).toContain('確かめなかった行: 1 行 (-r、URL、この環境向けでない行など)');
    expect(requirementsLines({ ...req, exact: false }).at(-1)?.text).toContain('packaging');
  });
  it('finds the missing module of the import error first', () => {
    expect(missingModuleOf({ missing_module: 'cv2' }, { missing_module: 'x' })).toBe('cv2');
    expect(missingModuleOf(null, { missing_module: 'x' })).toBe('x');
    expect(missingModuleOf(undefined, null)).toBeNull();
  });
  const base: DependencyHint = {
    missing: 'cv2', top: 'cv2', scope: 'workspace', route: 'rosdep',
    rosdep: { status: 'found', key: 'python3-opencv', installer: 'apt', packages: ['python3-opencv'] },
    python: { executable: '/usr/bin/python3', version: '3.12', venv: false },
    exec_depend: '<exec_depend>python3-opencv</exec_depend>', apt_command: 'sudo apt install python3-opencv',
    package_xml: '/ws/src/p/package.xml', already_declared: false, rosdep_command: 'rosdep install --from-paths /ws/src/p --ignore-src -y',
    venv: { pip_name: 'opencv-python', pip_name_differs: true, requirements: null, commands: ['pip install opencv-python'], active: false },
  };
  it('route ①: the exact line for package.xml and the rosdep command', () => {
    expect(rosdepRoute(base)).toEqual([
      { text: '/ws/src/p/package.xml の <package> の中に、次の 1 行を足します:', code: '<exec_depend>python3-opencv</exec_depend>' },
      { text: 'ワークスペースで、次のコマンドを実行します:', code: 'rosdep install --from-paths /ws/src/p --ignore-src -y' },
    ]);
    expect(rosdepRoute({ ...base, already_declared: true })?.[0]?.text).toContain('もう書いてあります');
  });
  it('route ① for code that is not a ROS package, offline rosdep, and no key', () => {
    const notRos = { ...base, scope: 'code_path' as const, package_xml: undefined, rosdep_command: undefined };
    expect(rosdepRoute(notRos)).toEqual([{ text: expect.stringContaining('package.xml がありません') as unknown as string, code: 'sudo apt install python3-opencv' }]);
    const offline: DependencyHint = { ...base, route: 'venv', rosdep: { status: 'unavailable', reason: 'no_database', candidate: 'python3-opencv' } };
    expect(rosdepRoute(offline)?.[0]?.text).toContain('rosdep update をまだ実行していません');
    expect(rosdepRoute({ ...base, route: 'venv', rosdep: { status: 'not_found', tried: ['python3-x'] }, exec_depend: undefined })).toBeNull();
  });
});
