// The module dropdown grouped by where the code is (A workspace / B registered / C installed), and
// what to know about the chosen module: names that are not offered and why, notices (rclpy inside,
// extension module, no hot reload for installed modules). docs/design/user-code.md

import type { ModuleEntry, ModuleInfo } from '../api/functionTypes';
import { t } from '../i18n';
import { groupModules, noticeText, skippedText } from './codeLocations';

interface SelectProps {
  value: string;
  modules: ModuleEntry[];
  onChange: (module: string) => void;
  disabled?: boolean;
  testId: string;
  'data-tour'?: string;
}

export function ModuleSelect({ value, modules, onChange, disabled, testId, 'data-tour': tour }: SelectProps) {
  const groups = groupModules(modules);
  const known = modules.some((m) => m.module === value);
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)} disabled={disabled} data-testid={testId} data-tour={tour}>
      <option value="">{t('function.moduleChoose')}</option>
      {value && !known && <option value={value}>{value}</option>}
      {groups.map((group) => (
        <optgroup key={group.scope} label={group.label}>
          {group.modules.map((m) => <option key={m.module} value={m.module}>{m.module}</option>)}
        </optgroup>
      ))}
    </select>
  );
}

export function ModuleNotes({ info }: { info: ModuleInfo | null }) {
  if (!info) return null;
  const skipped = info.skipped ?? [];
  const notices = info.notices ?? [];
  if (skipped.length === 0 && notices.length === 0) return null;
  return (
    <div className="module-notes" data-testid="module-notes">
      {skipped.length > 0 && <p className="muted small" data-testid="module-skipped">{skippedText(skipped)}</p>}
      {notices.map((notice) => (
        <p key={notice.code} className="notice-box small" data-testid="module-notice" data-code={notice.code}>{noticeText(notice)}</p>
      ))}
    </div>
  );
}
