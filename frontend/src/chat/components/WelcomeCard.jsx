import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { CARD_QUESTIONS, SCHEME_CARDS, UNIFIED_SAMPLES } from '../constants.js';
import { fetchSchemeStats } from '../api.js';

/* The welcome card: hero, the scheme overview carousel and "Try a question".
   The carousel pages the cards --page-cols x --page-rows at a time (read from
   the CSS, so 2x2 on desktop, 1 on phones); arrows move a page. The prompt grid
   follows the page on screen: one scheme -> its own questions, several -> a mix. */

function chunk(list, n) {
  const out = [];
  for (let i = 0; i < list.length; i += n) out.push(list.slice(i, i + n));
  return out;
}

export function promptsForKeys(keys) {
  if (keys.length === 1 && CARD_QUESTIONS[keys[0]]) {
    const conf = CARD_QUESTIONS[keys[0]];
    return { title: conf.title, items: conf.items };
  }
  const per = keys.length > 3 ? 2 : 3;
  const items = keys.flatMap((k) => ((CARD_QUESTIONS[k] && CARD_QUESTIONS[k].items) || []).slice(0, per));
  if (!items.length) return { title: 'Try a question', items: UNIFIED_SAMPLES };
  return { title: 'Try a question', items };
}

export function WelcomeCard({ strings, prompts, setPrompts, onAsk }) {
  const trackRef = useRef(null);
  const [perPage, setPerPage] = useState(4);
  const [arrows, setArrows] = useState({ show: true, prevDisabled: true, nextDisabled: false });
  // Live card figures from megh_db; the built-in numbers in SCHEME_CARDS only until
  // (or unless) /api/scheme-stats answers.
  const [liveStats, setLiveStats] = useState(null);
  useEffect(() => {
    let alive = true;
    fetchSchemeStats().then((cards) => { if (alive && cards) setLiveStats(cards); });
    return () => { alive = false; };
  }, []);
  const cards = SCHEME_CARDS.map((c) => (liveStats && Array.isArray(liveStats[c.key]) && liveStats[c.key].length
    ? { ...c, stats: liveStats[c.key] } : c));
  const pages = chunk(cards, perPage);
  const promptTimer = useRef(0);

  const readPageSize = useCallback(() => {
    const track = trackRef.current;
    if (!track) return 4;
    const cs = getComputedStyle(track);
    const cols = parseInt(cs.getPropertyValue('--page-cols'), 10) || 2;
    const rows = parseInt(cs.getPropertyValue('--page-rows'), 10) || 2;
    return Math.max(1, cols * rows);
  }, []);

  // Arrow visibility comes from the page count; the disabled state from position.
  const syncArrows = useCallback(() => {
    const track = trackRef.current;
    if (!track) return;
    const show = track.children.length > 1;
    if (!show) { setArrows({ show: false, prevDisabled: true, nextDisabled: true }); return; }
    const pageW = track.clientWidth;
    if (pageW > 0) {
      const max = track.scrollWidth - track.clientWidth;
      setArrows({ show: true, prevDisabled: track.scrollLeft <= 1, nextDisabled: track.scrollLeft >= max - 1 });
    } else {
      setArrows({ show: true, prevDisabled: true, nextDisabled: false });
    }
  }, []);

  const syncPrompts = useCallback(() => {
    const track = trackRef.current;
    if (!track || !track.clientWidth) return;
    const idx = Math.round(track.scrollLeft / track.clientWidth);
    const page = track.children[Math.min(Math.max(idx, 0), track.children.length - 1)];
    if (!page) return;
    const keys = Array.from(page.querySelectorAll('.scheme-card')).map((c) => c.dataset.scheme).filter(Boolean);
    setPrompts(promptsForKeys(keys));
  }, [setPrompts]);

  useLayoutEffect(() => { setPerPage(readPageSize()); }, [readPageSize]);

  // A new page size re-groups the cards and returns to page 1.
  useEffect(() => {
    if (trackRef.current) trackRef.current.scrollLeft = 0;
    syncArrows();
  }, [perPage, syncArrows]);

  useEffect(() => {
    const onResize = () => {
      const per = readPageSize();
      setPerPage((p) => (p === per ? p : per));
      syncArrows();
      syncPrompts();
    };
    window.addEventListener('resize', onResize);
    const raf = requestAnimationFrame(syncArrows);
    return () => { window.removeEventListener('resize', onResize); cancelAnimationFrame(raf); };
  }, [readPageSize, syncArrows, syncPrompts]);

  const onScroll = () => {
    syncArrows();
    // Debounced: the prompt grid swaps once, after the page settles.
    clearTimeout(promptTimer.current);
    promptTimer.current = setTimeout(syncPrompts, 140);
  };

  const scrollSchemes = (dir) => {
    const track = trackRef.current;
    if (!track) return;
    const page = track.clientWidth;
    const idx = Math.round(track.scrollLeft / page) + dir;
    const last = Math.max(0, track.children.length - 1);
    track.scrollTo({ left: Math.min(Math.max(idx, 0), last) * page, behavior: 'smooth' });
  };

  const arrowStyle = { visibility: arrows.show ? '' : 'hidden' };

  return (
    <div className="welcome-card">
      <div className="hero">
        <h1>{strings.heroTitle}</h1>
        <p>{strings.heroSub}</p>
      </div>

      <div className="scheme-carousel">
        <button className="carousel-arrow prev" type="button" aria-label="Previous schemes"
                style={arrowStyle} disabled={arrows.prevDisabled} onClick={() => scrollSchemes(-1)}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.25" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M15 18l-6-6 6-6" /></svg>
        </button>
        <div className="scheme-cards" ref={trackRef} onScroll={onScroll}>
          {pages.map((page, i) => (
            <div className="scheme-page" key={perPage + '-' + i}>
              {page.map((s) => (
                <div key={s.key} data-scheme={s.key} className={'scheme-card ' + s.cls}>
                  <div className="scheme-card-head">
                    <div className="ico">{s.ico}</div>
                    <div>
                      <h3>{s.name}</h3>
                      <div className="meta">{s.meta}</div>
                    </div>
                  </div>
                  <div className="stats">
                    {s.stats.map(([v, l]) => (
                      <div key={l}><div className="stat-val">{v}</div><div className="stat-lbl">{l}</div></div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          ))}
        </div>
        <button className="carousel-arrow next" type="button" aria-label="Next schemes"
                style={arrowStyle} disabled={arrows.nextDisabled} onClick={() => scrollSchemes(1)}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.25" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M9 18l6-6-6-6" /></svg>
        </button>
      </div>

      <div className="prompts-section">
        <div className="prompts-title">{prompts.title}</div>
        <div className="prompt-grid">
          {prompts.items.map((s) => (
            <div key={s.text} className="prompt" style={{ cursor: 'pointer' }}
                 onClick={(e) => { e.preventDefault(); e.stopPropagation(); onAsk(s.text); }}>
              <span className="ic">{s.ico}</span><span className="prompt-text">{s.text}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
