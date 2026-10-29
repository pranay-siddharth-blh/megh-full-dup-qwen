import { createRoot } from 'react-dom/client';
// X-11 (audit 2026-10-29): fonts are bundled, so an office network without internet keeps them
import '@fontsource/inter/latin-400.css';
import '@fontsource/inter/latin-500.css';
import '@fontsource/inter/latin-600.css';
import '@fontsource/inter/latin-700.css';
import '../styles/admin.css';
import AdminApp from './AdminApp.jsx';

createRoot(document.getElementById('root')).render(<AdminApp />);
