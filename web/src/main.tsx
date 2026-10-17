import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { App } from './App';
import { ErrorBoundary } from './lib/ErrorBoundary';
import './styles.css';
import './styles-ux.css';
import './styles-nodes.css';
import './styles-transform.css';
import './styles-tracing.css';
import './styles-function.css';
import './styles-scenario.css';

const root = document.getElementById('root');
if (!root) throw new Error('#root element missing from index.html');
createRoot(root).render(
  <StrictMode>
    <ErrorBoundary scope="app">
      <App />
    </ErrorBoundary>
  </StrictMode>,
);
