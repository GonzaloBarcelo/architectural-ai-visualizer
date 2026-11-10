import { useCallback, useEffect, useRef, useState } from 'react';
import type { PointerEvent, ReactNode } from 'react';

/** Zoom and offset relative to the pane width, so linked panes stay aligned at any size. */
export type View = { scale: number; x: number; y: number };

const MIN = 0.2;
const MAX = 40;
const DRAG = 4; // px before a press becomes a pan (shorter presses stay clicks)

function fitView(aspect: number, width: number, height: number): View {
  if (!width || !height) return { scale: 1, x: 0, y: 0 };
  const frame = height / width;
  const scale = Math.min(1, frame * aspect);
  return { scale, x: (1 - scale) / 2, y: (frame - scale / aspect) / 2 };
}

/**
 * Pan/zoom viewport: wheel or trackpad pinch zooms at the pointer, dragging pans, and the
 * buttons zoom, fit and go full screen. `view`/`onView` make it controlled (linked panes).
 */
export default function ZoomPane({ aspect, label, view, onView, children }: {
  aspect: number;
  label: string;
  view?: View | null;
  onView?: (view: View) => void;
  children: ReactNode;
}) {
  const frame = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });
  const [own, setOwn] = useState<View | null>(null);
  const [dragging, setDragging] = useState(false);
  const drag = useRef<{ x: number; y: number; start: View; moved: boolean; id: number } | null>(null);
  const suppressClick = useRef(false);
  const linked = onView !== undefined;
  const shown = (linked ? view : own) ?? fitView(aspect, size.width, size.height);
  const latest = useRef(shown);
  latest.current = shown;
  const set = useCallback((next: View) => (onView ?? setOwn)(next), [onView]);

  useEffect(() => {
    const el = frame.current;
    if (!el) return;
    const observer = new ResizeObserver(([entry]) => {
      setSize({ width: entry.contentRect.width, height: entry.contentRect.height });
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const zoomAt = useCallback((factor: number, px: number, py: number) => {
    const el = frame.current;
    if (!el) return;
    const w = el.clientWidth || 1;
    const v = latest.current;
    const scale = Math.min(MAX, Math.max(MIN, v.scale * factor));
    const k = scale / v.scale;
    const nx = px / w, ny = py / w;
    set({ scale, x: nx - (nx - v.x) * k, y: ny - (ny - v.y) * k });
  }, [set]);

  useEffect(() => {
    const el = frame.current;
    if (!el) return;
    // Native listener: React's wheel handler is passive and cannot stop the page scrolling.
    const wheel = (event: WheelEvent) => {
      event.preventDefault();
      const rect = el.getBoundingClientRect();
      const delta = event.deltaMode === 1 ? event.deltaY * 16 : event.deltaY;
      zoomAt(Math.exp(-delta * (event.ctrlKey ? 0.01 : 0.0015)), event.clientX - rect.left, event.clientY - rect.top);
    };
    el.addEventListener('wheel', wheel, { passive: false });
    return () => el.removeEventListener('wheel', wheel);
  }, [zoomAt]);

  const down = (event: PointerEvent<HTMLDivElement>) => {
    if (event.button !== 0 || (event.target as HTMLElement).closest('.wf-zoom-tools')) return;
    drag.current = { x: event.clientX, y: event.clientY, start: latest.current, moved: false, id: event.pointerId };
  };
  const move = (event: PointerEvent<HTMLDivElement>) => {
    const d = drag.current;
    const el = frame.current;
    if (!d || !el) return;
    const dx = event.clientX - d.x, dy = event.clientY - d.y;
    if (!d.moved && Math.hypot(dx, dy) < DRAG) return;
    if (!d.moved) {
      d.moved = true;
      setDragging(true);
      el.setPointerCapture(d.id);
    }
    const w = el.clientWidth || 1;
    set({ ...d.start, x: d.start.x + dx / w, y: d.start.y + dy / w });
  };
  const up = () => {
    if (drag.current?.moved) suppressClick.current = true;
    drag.current = null;
    setDragging(false);
  };
  const center = (factor: number) => {
    const el = frame.current;
    if (el) zoomAt(factor, el.clientWidth / 2, el.clientHeight / 2);
  };
  const fullscreen = () => {
    const figure = frame.current?.closest('figure');
    if (!figure) return;
    if (document.fullscreenElement) void document.exitFullscreen();
    else void figure.requestFullscreen?.();
  };
  const w = size.width;

  return <div
    ref={frame}
    className={`wf-zoom ${dragging ? 'dragging' : ''}`}
    onPointerDown={down}
    onPointerMove={move}
    onPointerUp={up}
    onPointerCancel={up}
    onClickCapture={event => { if (suppressClick.current) { suppressClick.current = false; event.stopPropagation(); event.preventDefault(); } }}
    onDoubleClick={event => { const rect = event.currentTarget.getBoundingClientRect(); zoomAt(2, event.clientX - rect.left, event.clientY - rect.top); }}
  >
    <div
      className="wf-zoom-content"
      style={{ width: w, height: w / aspect, transform: `translate(${shown.x * w}px, ${shown.y * w}px) scale(${shown.scale})` }}
    >
      {children}
    </div>
    <div className="wf-zoom-tools" role="group" aria-label={`Navegación: ${label}`}>
      <button type="button" onClick={() => center(1.5)} aria-label="Ampliar" title="Ampliar">+</button>
      <button type="button" onClick={() => center(1 / 1.5)} aria-label="Reducir" title="Reducir">−</button>
      <button type="button" onClick={() => set(fitView(aspect, size.width, size.height))} title="Ver el plano completo">Ajustar</button>
      <button type="button" onClick={fullscreen} aria-label="Pantalla completa" title="Pantalla completa">⛶</button>
      <span aria-live="polite">{Math.round(shown.scale * 100)}%</span>
    </div>
  </div>;
}
