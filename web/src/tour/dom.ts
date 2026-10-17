// The page as the tours see it: only elements that are on screen (hidden tabs and closed
// dialogs yield nothing). Selectors come from the tour definitions, never from user input.

import type { DomEl, DomProbe } from './types';

function isVisible(el: Element): boolean {
  const rect = el.getBoundingClientRect();
  if (rect.width <= 0 && rect.height <= 0) return false;
  return window.getComputedStyle(el).visibility !== 'hidden';
}

function toDomEl(el: Element): DomEl {
  const field = el as Partial<HTMLInputElement>;
  return {
    value: typeof field.value === 'string' ? field.value : '',
    checked: field.checked === true,
    text: el.textContent ?? '',
    attr: (name) => el.getAttribute(name),
  };
}

function visibleElements(selector: string): Element[] {
  try {
    return Array.from(document.querySelectorAll(selector)).filter(isVisible);
  } catch {
    // A malformed selector in a tour definition must not break the app.
    return [];
  }
}

export const DOM_PROBE: DomProbe = { all: (selector) => visibleElements(selector).map(toDomEl) };

/** The first element of a selector that is on screen. */
export const findVisible = (selector: string): Element | null => visibleElements(selector)[0] ?? null;
