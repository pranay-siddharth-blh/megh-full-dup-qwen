import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { keyLabel } from '../shortcuts.js';
import { createPortal } from 'react-dom';
import { histAgo, histBucket, initialsFor } from '../format.js';
import { ADMIN_ROLES } from '../constants.js';
import { API_BASE } from '../api.js';

/* The left sidebar: brand + rail toggle, navigation, the officer's chat history
   (Pinned, date buckets, collapsible Archived), the collapsed-rail pins and the
   user chip. Same markup and classes as web/ai_query.html. */

const Icon = ({ d, children, ...p }) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...p}>
    {d ? <path d={d} /> : children}
  </svg>
);
const PinGlyph = () => (
  <Icon><line x1="12" y1="17" x2="12" y2="22" /><path d="M9 2h6l-1 6 3 3v2H7v-2l3-3z" /></Icon>
);

// Row menu, anchored to the clicked "⋯", rendered on <body> like the original.
function HistMenu({ menu, conv, onAction, onClose }) {
  const ref = useRef(null);
  const [pos, setPos] = useState({ top: menu.rect.bottom + 4, left: menu.rect.left });
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    setPos({
      top: Math.min(menu.rect.bottom + 4, window.innerHeight - el.offsetHeight - 8),
      left: Math.min(menu.rect.left, window.innerWidth - el.offsetWidth - 8),
    });
  }, [menu]);
  useEffect(() => {
    const away = (e) => { if (ref.current && !ref.current.contains(e.target)) onClose(); };
    const t = setTimeout(() => document.addEventListener('mousedown', away), 0);
    return () => { clearTimeout(t); document.removeEventListener('mousedown', away); };
  }, [onClose]);
  const act = (a) => { onClose(); onAction(a, menu.sid, conv); };
  return createPortal(
    <div className="hist-pop" ref={ref} style={{ top: pos.top + 'px', left: pos.left + 'px' }}>
      <button type="button" onClick={() => act('rename')}>
        <Icon><path d="M12 20h9" /><path d="M16.5 3.5a2.1 2.1 0 013 3L7 19l-4 1 1-4z" /></Icon>Rename
      </button>
      <button type="button" onClick={() => act('pin')}><PinGlyph />{conv.pinned ? 'Unpin chat' : 'Pin chat'}</button>
      <button type="button" onClick={() => act('archive')}>
        <Icon><rect x="3" y="4" width="18" height="4" rx="1" /><path d="M5 8v11a1 1 0 001 1h12a1 1 0 001-1V8" /><line x1="10" y1="12" x2="14" y2="12" /></Icon>
        {conv.archived ? 'Unarchive' : 'Archive'}
      </button>
      <hr />
      <button type="button" className="danger" onClick={() => act('delete')}>
        <Icon><polyline points="3 6 5 6 21 6" /><path d="M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6" /><path d="M10 11v6M14 11v6" /><path d="M9 6V4a1 1 0 011-1h4a1 1 0 011 1v2" /></Icon>
        Delete
      </button>
    </div>,
    document.body,
  );
}

function HistItem({ c, activeSid, menuSid, onOpen, onMenu }) {
  const title = c.title || 'Untitled chat';
  const plural = c.turn_count === 1 ? '' : 's';
  return (
    <div className={'hist-item' + (c.session_id === activeSid ? ' active' : '') + (c.archived ? ' archived' : '')
                    + (menuSid === c.session_id ? ' menu-open' : '')}
         title={`${title} · ${c.turn_count} turn${plural} · ${histAgo(c.last_at)}`}
         onClick={() => onOpen(c.session_id)}>
      {c.pinned && <span className="pin-dot" title="Pinned"><PinGlyph /></span>}
      {title}
      <span className="hist-menu" onClick={(e) => { e.stopPropagation(); onMenu(e, c.session_id); }}>⋯</span>
    </div>
  );
}

export function Sidebar({
  signedIn, user, history, filter, onFilter, searchOpen, setSearchOpen, archOpen, onToggleArch,
  activeSid, onOpen, onHistAction, onNewChat, onGlossary, onUseCases, onToggleRail, rail, onLogout, onCloseNav,
}) {
  const [menu, setMenu] = useState(null);   // {sid, rect}
  const searchRef = useRef(null);

  useEffect(() => { if (searchOpen && searchRef.current) searchRef.current.focus(); }, [searchOpen]);

  // Esc in the search field puts it away (capture: runs before the drawer's Esc).
  useEffect(() => {
    const onKey = (e) => {
      if (e.key !== 'Escape') return;
      if (searchRef.current && document.activeElement === searchRef.current) {
        e.stopPropagation();
        setSearchOpen(false);
        searchRef.current.blur();
      }
    };
    document.addEventListener('keydown', onKey, true);
    return () => document.removeEventListener('keydown', onKey, true);
  }, [setSearchOpen]);

  const u = user || {};
  const name = u.name || u.username || 'Officer';
  const role = (u.role || '').replace(/_/g, ' ') || 'officer';
  const isAdmin = ADMIN_ROLES.includes(u.role);

  const pinned = history.filter((c) => c.pinned && !c.archived);
  const normal = history.filter((c) => !c.pinned && !c.archived);
  const archived = history.filter((c) => c.archived);

  const itemProps = { activeSid, menuSid: menu && menu.sid, onOpen, onMenu: (e, sid) => setMenu({ sid, rect: e.target.getBoundingClientRect() }) };

  let list;
  if (!signedIn) list = <div className="hist-empty">Sign in to see your chat history.</div>;
  else if (!history.length) {
    list = filter
      ? <div className="hist-empty">No chats match that search.</div>
      : <div className="hist-empty">No conversations yet.<br />Ask something — it will appear here.</div>;
  } else {
    const rows = [];
    if (pinned.length) {
      rows.push(<div key="h-pinned" className="hist-day">Pinned</div>);
      pinned.forEach((c) => rows.push(<HistItem key={c.session_id} c={c} {...itemProps} />));
    }
    let last = '';
    normal.forEach((c) => {
      const b = histBucket(c.last_at);
      if (b !== last) { rows.push(<div key={'h-' + b} className="hist-day">{b}</div>); last = b; }
      rows.push(<HistItem key={c.session_id} c={c} {...itemProps} />);
    });
    list = rows;
  }

  // Any tap on a nav item or the user chip closes the mobile drawer.
  const onSidebarClick = (e) => { if (e.target.closest('.nav-item, .user-chip')) onCloseNav(); };
  const menuConv = menu ? (history.find((c) => c.session_id === menu.sid) || {}) : null;

  return (
    <aside className="sidebar" onClick={onSidebarClick}>
      <div className="brand">
        <button className="rail-btn" onClick={onToggleRail} type="button"
                aria-label={rail ? 'Expand sidebar' : 'Collapse sidebar'} aria-expanded={rail ? 'false' : 'true'}
                title={(rail ? 'Expand' : 'Collapse') + ` sidebar (${keyLabel('sidebar')})`}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <rect x="3" y="4" width="18" height="16" rx="2.5" /><line x1="9.5" y1="4" x2="9.5" y2="20" />
          </svg>
        </button>
        <div className="brand-logo">M</div>
        <div>
          <div className="brand-name">Megh One AI</div>
          <div className="brand-sub">NLP Dashboard</div>
        </div>
      </div>

      <div className="nav-section">Conversations</div>
      <div className="nav-item" onClick={onNewChat} title={`New chat (${keyLabel('newChat')})`}>
        <svg className="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 5v14M5 12h14" /></svg>
        New chat
      </div>

      <div className="nav-section">Resources</div>
      <div className="nav-item" onClick={onGlossary}>
        <svg className="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M4 19.5A2.5 2.5 0 016.5 17H20" /><path d="M6.5 2H20v20H6.5A2.5 2.5 0 014 19.5v-15A2.5 2.5 0 016.5 2z" /></svg>
        Glossary
      </div>
      <div className="nav-item" onClick={onUseCases}>
        <svg className="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" /><polyline points="14 2 14 8 20 8" /></svg>
        Use cases
      </div>
      {/* Admin-only entry point; the /admin/* API enforces the same rule server-side. */}
      {signedIn && isAdmin && (
        <div className="nav-item" title="Open the admin console in a new tab"
             onClick={() => window.open((API_BASE || '') + '/admin-ui', '_blank', 'noopener')}>
          <svg className="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <rect x="3" y="3" width="7.5" height="8.5" rx="1.5" /><rect x="13.5" y="3" width="7.5" height="5" rx="1.5" />
            <rect x="13.5" y="10.5" width="7.5" height="10.5" rx="1.5" /><rect x="3" y="14" width="7.5" height="7" rx="1.5" />
          </svg>
          Admin dashboard
          <svg className="ext" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6" /><polyline points="15 3 21 3 21 9" /><line x1="10" y1="14" x2="21" y2="3" /></svg>
        </div>
      )}

      <div className="nav-section hist-head">
        <span>Chat history</span>
        <button type="button" className="hist-search-btn" onClick={() => setSearchOpen(!searchOpen)}
                aria-label="Search chats" aria-expanded={searchOpen ? 'true' : 'false'} title={`Search chats (${keyLabel('search')})`}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="11" cy="11" r="7" /><line x1="20" y1="20" x2="16.65" y2="16.65" />
          </svg>
        </button>
      </div>
      <div className="hist-wrap">
        <div className={'hist-search-box' + (searchOpen ? ' open' : '') + (filter ? ' has-text' : '')}>
          <input className="hist-search" ref={searchRef} type="text" placeholder="Search chats…" autoComplete="off"
                 value={filter} onChange={(e) => onFilter(e.target.value)} />
          <button type="button" className="hist-clear" aria-label="Clear search" title="Clear"
                  onClick={() => { onFilter(''); if (searchRef.current) searchRef.current.focus(); }}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round"><line x1="6" y1="6" x2="18" y2="18" /><line x1="18" y1="6" x2="6" y2="18" /></svg>
          </button>
        </div>
        <div className="hist-list">{list}</div>
        {/* Collapsed rail: the pinned threads as icon buttons. */}
        <div className="rail-pins">
          {signedIn && pinned.map((c) => (
            <button key={c.session_id} type="button" className={'rail-pin' + (c.session_id === activeSid ? ' active' : '')}
                    title={c.title || 'Untitled chat'} onClick={() => onOpen(c.session_id)}>
              <PinGlyph />
            </button>
          ))}
        </div>
        {/* Archived: its own region with its own scroll, collapsed by default. */}
        <div className="hist-arch">
          {signedIn && archived.length > 0 && (
            <>
              <div className={'hist-day hist-arch-head' + (archOpen ? ' open' : '')} onClick={onToggleArch}
                   role="button" tabIndex={0} title={(archOpen ? 'Hide' : 'Show') + ' archived chats'}>
                <svg className="chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><polyline points="9 18 15 12 9 6" /></svg>
                Archived<span className="count">{archived.length}</span>
              </div>
              {archOpen && (
                <div className="hist-arch-body">
                  {archived.map((c) => <HistItem key={c.session_id} c={c} {...itemProps} />)}
                </div>
              )}
            </>
          )}
        </div>
      </div>

      <div className="sidebar-foot">
        <div className="user-chip" title={u.username ? u.username + (u.tenant_id ? ' · tenant ' + u.tenant_id : '') : undefined}>
          <div className="avatar">{signedIn ? initialsFor(name, u.username) : 'TA'}</div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ color: 'white', fontSize: '12.5px', fontWeight: 600 }}>{signedIn ? name : 'Test Account'}</div>
            <div>{signedIn ? role : 'State Administrator'}</div>
          </div>
          <svg onClick={onLogout} style={{ cursor: 'pointer', opacity: 0.6 }} width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <title>Sign out</title>
            <path d="M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4" /><polyline points="16 17 21 12 16 7" /><line x1="21" y1="12" x2="9" y2="12" />
          </svg>
        </div>
      </div>

      {menu && <HistMenu menu={menu} conv={menuConv} onAction={onHistAction} onClose={() => setMenu(null)} />}
    </aside>
  );
}
