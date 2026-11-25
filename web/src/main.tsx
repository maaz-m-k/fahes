import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { App } from './App';
import { pickClient } from './api/client';
import './styles/app.css';
import './styles/extra.css';

createRoot(document.getElementById('root')!).render(<StrictMode><App engine={pickClient()} /></StrictMode>);
