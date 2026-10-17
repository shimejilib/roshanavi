// The visible part of a tour: the highlight + popover (driver.js), the first-launch card,
// the "paused" pill and the error line. driver.js only draws; every decision is the engine's.

import 'driver.js/dist/driver.css';
import { driver, type Driver, type PopoverDOM } from 'driver.js';
import { useEffect, useRef, useState } from 'react';
import { t, type MessageKey } from '../i18n';
import { ja } from '../i18n/messages';
import { findVisible } from './dom';
import { messageKey, stepOf } from './engine';
import { richSegments } from './richText';
import { TOURS } from './tours';
import { useTour } from './TourProvider';
import type { RunState, TourDef } from './types';
import type { StepPlan } from './engine';

const REFRESH_MS = 400;

interface ButtonSpec {
  label: string;
  primary?: boolean;
  onClick: () => void;
}

interface PopoverView {
  title: string;
  paragraphs: { text: string; className?: string }[];
  progress: string;
  buttons: ButtonSpec[];
}

type Actions = ReturnType<typeof useTour>;

/** A step text, or '' when the dictionary has none (hints are optional). */
function textOf(def: TourDef, run: RunState, part: 'title' | 'body' | 'hint'): string {
  const key = messageKey(def, stepOf(def, run), part);
  return key in ja ? t(key as MessageKey) : '';
}

function buttonsFor(api: Actions, def: TourDef, run: RunState, plan: StepPlan): ButtonSpec[] {
  const back: ButtonSpec[] = plan.canBack ? [{ label: t('tour.ui.back'), onClick: api.back }] : [];
  if (plan.last) {
    if (run.fixtures.length === 0) return [...back, { label: t('tour.ui.finish'), primary: true, onClick: () => api.finish(false) }];
    const keep: ButtonSpec[] = def.keepable ? [{ label: t('tour.ui.finishKeep'), onClick: () => api.finish(true) }] : [];
    return [...back, ...keep, { label: t('tour.ui.finishClean'), primary: true, onClick: () => api.finish(false) }];
  }
  if (plan.kind === 'show') return [...back, { label: t('tour.ui.next'), primary: true, onClick: api.next }];
  return [...back, { label: t('tour.ui.skip'), onClick: api.next }];
}

function viewOf(api: Actions): PopoverView | null {
  const { run, def, plan } = api;
  if (!run || !def || !plan) return null;
  if (run.status === 'preparing') {
    return { title: t('tour.ui.preparing'), paragraphs: [], progress: '', buttons: [{ label: t('tour.ui.quit'), onClick: api.quit }] };
  }
  const paragraphs: PopoverView['paragraphs'] = [{ text: textOf(def, run, 'body') }];
  if (plan.missingTarget) paragraphs.push({ text: t('tour.ui.missingTarget'), className: 'rn-tour-warn' });
  else if (plan.showHint && textOf(def, run, 'hint')) paragraphs.push({ text: textOf(def, run, 'hint'), className: 'rn-tour-hint' });
  if (plan.last) paragraphs.push({ text: t('tour.ui.doc', { path: def.docPath }), className: 'rn-tour-hint' });
  return {
    title: textOf(def, run, 'title'),
    paragraphs,
    progress: t('tour.ui.progress', { step: plan.step + 1, total: plan.total }),
    buttons: buttonsFor(api, def, run, plan),
  };
}

function appendRich(parent: HTMLElement, text: string): void {
  for (const segment of richSegments(text)) {
    if (segment.code) {
      const code = document.createElement('code');
      code.textContent = segment.text;
      parent.appendChild(code);
    } else {
      parent.appendChild(document.createTextNode(segment.text));
    }
  }
}

/** Fills driver.js's popover with plain DOM nodes (no innerHTML anywhere). */
function fillPopover(popover: PopoverDOM, view: PopoverView): void {
  popover.title.textContent = view.title;
  popover.title.style.display = view.title ? 'block' : 'none';
  popover.description.replaceChildren(
    ...view.paragraphs.map((p) => {
      const el = document.createElement('p');
      if (p.className) el.className = p.className;
      appendRich(el, p.text);
      return el;
    }),
  );
  popover.description.style.display = view.paragraphs.length ? 'block' : 'none';
  popover.progress.textContent = view.progress;
  popover.footer.style.display = 'flex';
  popover.closeButton.setAttribute('aria-label', t('tour.ui.pause'));
  popover.closeButton.title = t('tour.ui.pause');
  popover.footerButtons.replaceChildren(
    ...view.buttons.map((spec) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = spec.primary ? 'rn-tour-btn primary' : 'rn-tour-btn';
      button.textContent = spec.label;
      button.dataset.tourButton = spec.primary ? 'primary' : 'secondary';
      button.addEventListener('click', spec.onClick);
      return button;
    }),
  );
}

/**
 * driver.js only clears the mark of the element it finished highlighting; when steps follow each
 * other faster than its 250 ms move, an earlier element keeps the outline and stays clickable.
 */
function pruneStaleHighlights(keep: Element | null): void {
  document.querySelectorAll('.driver-active-element').forEach((el) => {
    if (el === keep || el.id === 'driver-dummy-element') return;
    el.classList.remove('driver-active-element', 'driver-no-interaction');
    el.removeAttribute('aria-haspopup');
    el.removeAttribute('aria-expanded');
    el.removeAttribute('aria-controls');
  });
}

const FOCUSABLE = new Set(['INPUT', 'SELECT', 'TEXTAREA', 'BUTTON']);

/** Show steps: Enter goes on. Do steps: the thing to operate has the focus. */
function focusFor(plan: StepPlan, element: Element | null): void {
  if (plan.kind === 'do' && !plan.centered && element && FOCUSABLE.has(element.tagName)) {
    (element as HTMLElement).focus();
    return;
  }
  document.querySelector<HTMLElement>('.rn-tour [data-tour-button="primary"]')?.focus();
}

function createDriver(): Driver {
  const reduced = typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  return driver({
    animate: !reduced, smoothScroll: !reduced, duration: 250, allowClose: false, allowKeyboardControl: false,
    overlayOpacity: 0.55, stagePadding: 6, stageRadius: 6, popoverClass: 'rn-tour', popoverOffset: 12,
  });
}

function TourPopover() {
  const api = useTour();
  const apiRef = useRef(api);
  apiRef.current = api;
  const driverRef = useRef<Driver | null>(null);
  const [rev, setRev] = useState(0);
  const { run, plan } = api;
  const active = run !== null && (run.status === 'running' || run.status === 'preparing');

  const destroy = () => {
    driverRef.current?.destroy();
    driverRef.current = null;
  };
  useEffect(() => destroy, []);
  useEffect(() => {
    if (!active) destroy();
  }, [active]);

  useEffect(() => {
    const current = apiRef.current;
    const view = viewOf(current);
    if (!active || !view || !current.plan || !current.run || !current.def) return;
    const { plan: stepPlan } = current;
    const side = stepOf(current.def, current.run).side;
    const element = stepPlan.selector && !stepPlan.centered ? findVisible(stepPlan.selector) : null;
    try {
      driverRef.current ??= createDriver();
      driverRef.current.highlight({
        ...(element ? { element } : {}),
        onHighlighted: () => {
          pruneStaleHighlights(element);
          focusFor(stepPlan, element);
        },
        popover: {
          title: ' ', description: ' ', align: 'center', showButtons: ['close'], showProgress: true,
          ...(side ? { side } : {}),
          onCloseClick: () => apiRef.current.pause(),
          onPopoverRender: (popover) => fillPopover(popover, view),
        },
      });
    } catch (err) {
      console.error('[tour] could not draw the step', err);
      current.pause();
    }
    // The step's text only changes with these.
  }, [active, run?.tourId, run?.step, run?.status, run?.fixtures.length, plan?.selector, plan?.centered, rev]);

  // Keeps the highlight on its element while the page moves (layouts, dialogs opening).
  useEffect(() => {
    if (!active) return undefined;
    const timer = window.setInterval(() => {
      const d = driverRef.current;
      const selector = apiRef.current.plan?.selector;
      if (!d || !d.isActive()) return;
      const element = selector && !apiRef.current.plan?.centered ? findVisible(selector) : null;
      if (element && d.getActiveElement() !== element) setRev((n) => n + 1);
      else d.refresh();
    }, REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [active]);
  return null;
}

function TourWelcome() {
  const api = useTour();
  if (!api.showWelcome) return null;
  const first = TOURS[0];
  return (
    <aside className="tour-card" role="dialog" aria-label={t('tour.ui.welcomeTitle')} data-tour="welcome">
      <h3>{t('tour.ui.welcomeTitle')}</h3>
      <p>{t('tour.ui.welcomeBody')}</p>
      <div className="row end">
        <button type="button" onClick={api.dismissWelcome} data-testid="tour-welcome-later">{t('tour.ui.welcomeLater')}</button>
        <button type="button" className="primary" onClick={() => first && api.start(first.id)} data-testid="tour-welcome-start">
          {t('tour.ui.welcomeStart')}
        </button>
      </div>
    </aside>
  );
}

function TourPausedPill() {
  const { run, def, resume, quit } = useTour();
  if (!run || !def || run.status !== 'paused') return null;
  return (
    <aside className="tour-card tour-paused" role="status" data-tour="paused">
      <span>{t('tour.ui.pausedPill', { name: t(`tour.name.${def.id}` as MessageKey) })}</span>
      <button type="button" className="primary" onClick={resume} data-testid="tour-resume">{t('tour.ui.resume')}</button>
      <button type="button" onClick={quit} data-testid="tour-quit">{t('tour.ui.quit')}</button>
    </aside>
  );
}

function TourMessage() {
  const { message, clearMessage } = useTour();
  if (!message) return null;
  return (
    <aside className="tour-card tour-message" role="alert" data-testid="tour-message">
      <span>{message}</span>
      <button type="button" onClick={clearMessage}>{t('common.close')}</button>
    </aside>
  );
}

export function TourOverlay() {
  return (
    <>
      <TourPopover />
      <TourWelcome />
      <TourPausedPill />
      <TourMessage />
    </>
  );
}
