import { createRoot } from 'react-dom/client';
import '../styles/chat.css';
import App from './App.jsx';

// Resolved before first paint: a stored token means a session is about to be
// confirmed, so hold the neutral splash instead of flashing the sign-in screen.
try {
  if (localStorage.getItem('megh_jwt')) document.body.classList.add('auth-pending');
} catch (e) { /* storage blocked — fall through to the gate */ }

createRoot(document.getElementById('root')).render(<App />);
