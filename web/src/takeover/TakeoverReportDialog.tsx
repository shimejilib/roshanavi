// What per-node takeover keeps and loses of the launch file (and how to run it as a whole).

import type { TakeoverReport, TakeoverStatus } from '../api/takeoverTypes';
import { t } from '../i18n';
import { Modal } from '../lib/Modal';
import { itemText, launchLabel, noteText, restText } from './model';

export function ReportBody({ status, report }: { status: Pick<TakeoverStatus, 'package' | 'launch_file'>; report: TakeoverReport }) {
  return (
    <div className="takeover-report" data-testid="takeover-report">
      {report.notes.map((code) => <p key={code} className="notice-box small">{noteText(code)}</p>)}
      {report.separate > 0 && report.lost.length > 0 && (
        <p>{t('takeover.reportIntro', { file: launchLabel(status), n: report.separate })}</p>
      )}
      {report.lost.length > 0 && (
        <>
          <h4>{t('takeover.lostTitle')}</h4>
          <ul data-testid="takeover-lost">{report.lost.map((item) => <li key={item.code}>{itemText('lost', item)}</li>)}</ul>
        </>
      )}
      {report.carried.length > 0 && (
        <>
          <h4>{t('takeover.carriedTitle')}</h4>
          <ul data-testid="takeover-carried">{report.carried.map((item) => <li key={item.code}>{itemText('carried', item)}</li>)}</ul>
        </>
      )}
      {report.rest.length > 0 && (
        <>
          <h4>{t('takeover.restTitle')}</h4>
          <ul className="small">{report.rest.map((item, i) => <li key={`${item.code}-${i}`}>{restText(item)}</li>)}</ul>
        </>
      )}
      {report.suggest_whole && <p className="notice-box small" data-testid="takeover-whole-hint">{t('takeover.wholeHint')}</p>}
    </div>
  );
}

export function TakeoverReportDialog({ status, report, onClose }: { status: TakeoverStatus; report: TakeoverReport; onClose: () => void }) {
  return (
    <Modal title={t('takeover.reportTitle')} onClose={onClose} wide testId="takeover-report-dialog">
      <ReportBody status={status} report={report} />
      <div className="row end">
        <button type="button" onClick={onClose}>{t('common.close')}</button>
      </div>
    </Modal>
  );
}
