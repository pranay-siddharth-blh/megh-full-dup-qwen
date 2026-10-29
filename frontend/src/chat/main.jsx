import { createRoot } from 'react-dom/client';
// X-11 (audit 2026-10-29): fonts are bundled, so an office network without internet keeps them
import '@fontsource/inter/latin-400.css';
import '@fontsource/inter/latin-500.css';
import '@fontsource/inter/latin-600.css';
import '@fontsource/inter/latin-700.css';
import '@fontsource/jetbrains-mono/latin-400.css';
import '@fontsource/jetbrains-mono/latin-600.css';
import '@fontsource/jetbrains-mono/latin-700.css';
import '../styles/chat.css';
import App from './App.jsx';

// Resolved before first paint: a stored token means a session is about to be
// confirmed, so hold the neutral splash instead of flashing the sign-in screen.
try {
  if (localStorage.getItem('megh_jwt')) document.body.classList.add('auth-pending');
} catch (e) { /* storage blocked — fall through to the gate */ }

createRoot(document.getElementById('root')).render(<App />);
