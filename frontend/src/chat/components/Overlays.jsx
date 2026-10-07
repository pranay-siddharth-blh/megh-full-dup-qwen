import { forwardRef, useState } from 'react';

/* The sign-in gate, the generic modal and the undo toast. */

export const LoginScreen = forwardRef(function LoginScreen({ error, invalid, busy, onSubmit, onInput }, userRef) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [shown, setShown] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    const ok = await onSubmit(username.trim(), password);
    if (ok === 'clear-password') setPassword('');
  };

  return (
    <div className="login-screen" id="loginScreen">
      <div className="login-wrap">
        <div className="login-head">
          <div className="login-mark"><span className="fallback">M</span></div>
          <div className="login-title">Megh One AI</div>
          <div className="login-tagline">NLP to SQL Assistant</div>
        </div>

        <div className="login-tabs" role="tablist">
          <button className="login-tab active" role="tab" aria-selected="true" type="button">Sign in</button>
        </div>

        <form className="login-card" onSubmit={submit} noValidate>
          <h2>Welcome back</h2>
          <p className="sub">Sign in with the credentials issued by your administrator.</p>

          <div className={'login-error' + (error ? ' show' : '')} role="alert">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" style={{ flexShrink: 0 }}><circle cx="12" cy="12" r="10" /><line x1="12" y1="8" x2="12" y2="12" /><line x1="12" y1="16" x2="12.01" y2="16" /></svg>
            <span>{error}</span>
          </div>

          <div className="login-field">
            <label htmlFor="loginEmail">Username</label>
            <input ref={userRef} type="text" id="loginEmail" name="username" autoComplete="username"
                   placeholder="e.g. wgh-officer" spellCheck="false"
                   className={invalid.includes('user') ? 'invalid' : ''}
                   value={username} onChange={(e) => { setUsername(e.target.value); onInput(); }} />
          </div>

          <div className="login-field">
            <label htmlFor="loginPassword">Password</label>
            <div className="login-input-wrap">
              <input type={shown ? 'text' : 'password'} id="loginPassword" name="password"
                     className={'has-toggle' + (invalid.includes('pass') ? ' invalid' : '')}
                     autoComplete="current-password" placeholder="••••••••"
                     value={password} onChange={(e) => { setPassword(e.target.value); onInput(); }} />
              <button type="button" className="pw-toggle" onClick={() => setShown(!shown)}
                      aria-label={shown ? 'Hide password' : 'Show password'} title={shown ? 'Hide password' : 'Show password'}>
                <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" /><circle cx="12" cy="12" r="3" /></svg>
              </button>
            </div>
          </div>

          <button type="submit" className="login-submit" disabled={busy}>{busy ? 'Signing in…' : 'Sign in'}</button>
        </form>

        <div className="login-note">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ flexShrink: 0 }}><rect x="3" y="11" width="18" height="11" rx="2" /><path d="M7 11V7a5 5 0 0 1 10 0v4" /></svg>
          Secure sign-in — your session is scoped to what your role and posting allow.
        </div>
      </div>
    </div>
  );
});

export function Modal({ modal, onClose }) {
  return (
    <div className={'modal-backdrop' + (modal ? ' show' : '')} onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="modal-card">
        <div className="modal-head">
          <div>
            <div className="modal-title">{modal ? modal.title : ''}</div>
            <div className="modal-sub">{modal ? modal.sub : ''}</div>
          </div>
          <button className="modal-close" type="button" onClick={onClose} title="Close (Esc)">&times;</button>
        </div>
        <div className="modal-body">{modal ? modal.body : null}</div>
      </div>
    </div>
  );
}

export function UndoToast({ toast, onUndo }) {
  return (
    <div className={'undo-toast' + (toast ? ' show' : '')} role="status" aria-live="polite">
      <span>{toast ? toast.message : ''}</span>
      <button type="button" onClick={onUndo} style={{ display: toast && toast.fn ? '' : 'none' }}>Undo</button>
    </div>
  );
}
