import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { ErrorBoundary, errorText } from './ErrorBoundary';

function panelFor(error: unknown, scope: 'app' | 'detail'): string {
  const boundary = new ErrorBoundary({ scope, children: null });
  boundary.state = ErrorBoundary.getDerivedStateFromError(error);
  return renderToStaticMarkup(boundary.render() as never);
}

describe('ErrorBoundary', () => {
  it('turns anything thrown into a readable message', () => {
    expect(errorText(new TypeError("Cannot read properties of undefined (reading 'replace')"))).toContain('reading');
    expect(errorText(new Error(''))).toBe('Error');
    expect(errorText('boom')).toBe('boom');
  });

  it('renders the Japanese error panel with the message, a reload button and a report hint', () => {
    const html = panelFor(new Error('detail.role.transform is undefined'), 'detail');
    expect(html).toContain('この部分の表示中にエラーが起きました');
    expect(html).toContain('detail.role.transform is undefined');
    expect(html).toContain('再読み込み');
    expect(html).toContain('この部分をやり直す');
    expect(html).toContain('開発者に知らせて');
    expect(html).toContain('role="alert"');
  });

  it('the app-level panel has no retry (only a reload)', () => {
    const html = panelFor('plain string', 'app');
    expect(html).toContain('画面の表示中にエラーが起きました');
    expect(html).toContain('plain string');
    expect(html).not.toContain('この部分をやり直す');
  });

  it('renders its children while nothing failed', () => {
    const boundary = new ErrorBoundary({ scope: 'tab', children: createElement('p', null, 'ok') });
    expect(renderToStaticMarkup(boundary.render() as never)).toBe('<p>ok</p>');
  });
});
