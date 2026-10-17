import { useEffect, useState } from 'react';
import { DARK, LIGHT, prefersDark, type Palette } from './style';

/** Graph colours that follow the OS light/dark setting. */
export function usePalette(): Palette {
  const [dark, setDark] = useState(prefersDark);
  useEffect(() => {
    const query = window.matchMedia?.('(prefers-color-scheme: dark)');
    if (!query) return undefined;
    const onChange = (e: MediaQueryListEvent) => setDark(e.matches);
    query.addEventListener('change', onChange);
    return () => query.removeEventListener('change', onChange);
  }, []);
  return dark ? DARK : LIGHT;
}
