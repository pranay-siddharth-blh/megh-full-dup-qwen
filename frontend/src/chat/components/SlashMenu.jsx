/* Slash-command menu (#319): a card above the composer listing the commands
   the typed text could be. Arrow keys move the highlight (App.jsx handles the
   keys so the text box keeps focus); Enter or Tab picks; a click picks. */
export function SlashMenu({ items, active, onPick, onHover }) {
  if (!items.length) return null;
  return (
    <div className="slash-menu" role="listbox" aria-label="Commands" id="slash-menu">
      {items.map((it, i) => (
        <div key={it.key} role="option" aria-selected={i === active} id={'slash-opt-' + i}
             className={'slash-item' + (i === active ? ' active' : '')}
             onMouseDown={(e) => { e.preventDefault(); onPick(it); }}   /* mousedown: the box keeps focus */
             onMouseMove={() => { if (active !== i) onHover(i); }}>
          <span className="sl-cmd mono">{it.label}</span>
          <span className="sl-desc">{it.desc}</span>
          {it.hint && <span className="sl-hint">{it.hint}</span>}
        </div>
      ))}
      <div className="slash-foot" aria-hidden="true">↑↓ choose · Enter pick · Esc close</div>
    </div>
  );
}
