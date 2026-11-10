import { useCallback, useEffect, useRef, useState } from 'react';
import type { ChangeEvent, FormEvent, MouseEvent } from 'react';
import './Workflow.css';
import ZoomPane from './ZoomPane';
import type { View } from './ZoomPane';

type Point = [number, number];
type Kind = 'wall' | 'slab' | 'room' | 'door' | 'window' | 'roof' | 'furniture';
type Finish = { name: string; color: [number, number, number]; roughness: number };
type CadRef = { handles: string[]; layers: string[]; block?: string | null; reading: 'verified' | 'inferred' | 'user'; detail?: string | null };
type Entity = { id: string; kind: Kind; polygon: Point[]; height?: number | null; thickness?: number | null; elevation?: number | null; sill?: number | null; wall_id?: string; name?: string; style?: string | null; finish?: string | null; cad?: CadRef | null; confirmed: boolean };
type Draft = { conceptual?: boolean; assumptions?: string[]; finishes?: Record<string, Finish>; page: number; title: string; calibration: { points: Point[]; metres: number | null; confirmed: boolean }; floor: { name: string; elevation: number | null; confirmed: boolean }; entities: Entity[]; complete: boolean };
type Issue = { path: string; message: string };
type Candidate = { id: string; polygon: Point[]; label: string };
type Page = { page: number; width: number; height: number; image_url: string; candidates: Candidate[] };
type ReadingStatus = 'verified' | 'inferred' | 'user' | 'missing';
type CadItem = { type: string; id: string; label: string; status: ReadingStatus; detail?: string | null; handles: string[]; layers: string[]; block?: string | null };
type Pending = { type: string; id: string; label: string; detail?: string | null; options?: string[] | null; blocking: boolean; polygon?: Point[] | null };
type Usage = { input: number; output: number; reasoning: number; cached_input: number; cost_usd: number };
type Plan = { index: number; name: string; size_m: number[]; wall_area_m2: number };
type LayerRow = { layer: string; role: string | null; match: string | null; status: string; used: string[]; in_plan: Record<string, number>; elsewhere: number };
type Cad = { layers?: LayerRow[]; format: string; filename: string; sha256: string; converter?: string | null; units: { name: string; source: string; inferred: boolean }; plan: Plan; plans: Plan[]; items: CadItem[]; pending: Pending[]; notes: string[]; reading_seconds: number; ai: { model: string; called: boolean; cache_hit: boolean; error?: string | null; image: boolean; usage: Usage; seconds: number; items: number } };
type Project = { source_format?: 'pdf' | 'dwg' | 'dxf'; cad?: Cad; plans?: Plan[]; plan_index?: number; ai_interpretation?: Draft; description?: string; id: string; filename: string; status: 'extracting' | 'review' | 'queued' | 'running' | 'succeeded' | 'failed'; stage: string; error?: string; pages?: Page[]; draft?: Draft; revision: number; issues?: Issue[]; manifest_url?: string; result_revision?: number; finishes_error?: string | null; stage_since?: { stage: string; at: string }; activity?: Activity | null; location?: Place | null; enhance?: boolean; enhance_server?: boolean; enhancement?: EnhanceSummary | null; ai_usage?: { plan?: { calls?: { cache_hit?: boolean; usage?: { total_tokens?: number } | null }[] } | null; enhancement?: EnhanceSummary | null } | null };
type Place = { status: 'verified' | 'inferred' | 'user' | 'missing'; text: string; city?: string | null; region?: string | null; country?: string | null; confidence?: number; method?: string | null; source?: { kind: string; label?: string } | null; derived?: string[] };
type EnhanceSummary = { status: string; notice?: string; model?: string; images?: number; accepted?: number; rejected?: number; failed?: number; cost_usd?: number; cost_usd_new?: number; seconds?: number };
type Activity = { step: number; total: number; label: string; labels?: string[]; started_at: string; attempt?: number; kind?: string; done?: number[]; active?: number[]; seconds?: Record<string, number>; item_started?: Record<string, string> };
type ProjectSummary = Pick<Project, 'id' | 'filename' | 'status' | 'stage'>;

const labels: Record<Kind, string> = { wall: 'Muro', slab: 'Suelo / losa', room: 'Estancia', door: 'Puerta', window: 'Ventana', roof: 'Cubierta', furniture: 'Mueble' };
const plural: Record<Kind, string> = { wall: 'muros', slab: 'losas', room: 'estancias', door: 'puertas', window: 'ventanas', roof: 'cubiertas', furniture: 'muebles' };
const kindColors: Record<Kind, string> = { wall: '#2f3a2a', slab: '#c9b48a', room: '#8c72ae', door: '#c0532f', window: '#2f86b8', roof: '#817768', furniture: '#a8754f' };
const finishLabels: Record<string, string> = { walls: 'Paredes', floor: 'Suelo', tile: 'Baños', doors: 'Puertas y armarios', joinery: 'Carpintería exterior', furniture_wood: 'Madera de muebles', upholstery: 'Tapicería', stone: 'Piedra / encimeras', ceramic: 'Sanitarios', metal: 'Metal / grifería' };
const floorLabels: Record<string, string> = { wood: 'madera', tile: 'baldosa', stone: 'piedra' };
const busyStates = new Set(['extracting', 'queued', 'running']);
const stages: Record<string, string> = { reading_dwg: 'Convirtiendo y leyendo el DWG', reading_check: 'Comprueba la lectura del DWG', choose_plan: 'Elige la planta que quieres modelar', resolving: 'Aplicando tus respuestas', extracting: 'Leyendo el PDF', interpreting: 'La IA está interpretando el plano', materials: 'Interpretando la descripción de materiales', validating_geometry: 'Validando geometría', modeling: 'Modelando en Blender', preview_qa: 'Comprobando la escena', rendering: 'Renderizando con Blender', final_qa: 'Comprobando las imágenes', exporting: 'Exportando el modelo 3D', enhancing: 'Mejorando los renders con IA', completed: 'Renders listos', queued: 'En cola', review: 'Pendiente de revisión', generation_failed: 'Error de generación', extraction_failed: 'Error al leer el PDF', interrupted: 'Proceso interrumpido' };
const phases: Record<string, string> = { extracting: 'Leyendo', review: 'En revisión', queued: 'En cola', running: 'Procesando', succeeded: 'Renders listos', failed: 'Necesita atención' };
const renderStages = ['queued', 'validating_geometry', 'modeling', 'preview_qa', 'rendering', 'final_qa', 'exporting', 'enhancing', 'completed'];
const MAX_DESCRIPTION = 1000;
const aiSteps = ['Muros, puertas y ventanas', 'Mobiliario y orientación', 'Revisión cruzada con el plano original'];
const dwgSteps = ['Lectura del DWG', 'Consulta de dudas a la IA'];
const isCad = (p?: Project | null) => !!p?.source_format && p.source_format !== 'pdf';
const sides: Record<string, string> = { up: 'arriba', down: 'abajo', left: 'izquierda', right: 'derecha', any: 'indiferente' };
const furnitureKinds: Record<string, string> = { bed_double: 'Cama doble', bed_single: 'Cama individual', nightstand: 'Mesita de noche', wardrobe: 'Armario', dresser: 'Cómoda', desk: 'Escritorio', shelving: 'Estantería', sofa: 'Sofá', armchair: 'Butaca', coffee_table: 'Mesa de centro', side_table: 'Mesa auxiliar', rug: 'Alfombra', tv_unit: 'Mueble TV', sideboard: 'Aparador', dining_set: 'Comedor (mesa y sillas)', dining_table: 'Mesa de comedor', chair: 'Silla', stool: 'Taburete', kitchen_counter: 'Encimera / módulo de cocina', kitchen_island: 'Isla de cocina', fridge: 'Frigorífico', toilet: 'Inodoro', bidet: 'Bidé', washbasin: 'Lavabo', shower: 'Ducha', bathtub: 'Bañera', washing_machine: 'Lavadora', plant: 'Planta', floor_lamp: 'Lámpara de pie', not_furniture: 'No es mobiliario (no modelar)' };
const roleLabels: Record<string, string> = { wall: 'Muros', door: 'Puertas', window: 'Ventanas', carpentry: 'Carpintería', furniture: 'Mobiliario', ignored: 'Anotación' };
const readingLabels: Record<ReadingStatus, string> = { verified: 'Leído del DWG', inferred: 'Resuelto por la IA', user: 'Indicado por ti', missing: 'Pendiente' };
const money = (v: number) => '$' + v.toFixed(v < 0.1 ? 3 : 2);
// Typical durations observed with gpt-5.4 at high reasoning effort; shown so a long wait never looks like a hang.
const expected: Record<string, string> = { reading_dwg: 'unos segundos', resolving: 'unos segundos', extracting: 'unos segundos', interpreting: '15–20 minutos (3 llamadas a la IA de 4–8 min cada una)', materials: 'menos de un minuto', queued: 'empieza en cuanto termine el trabajo anterior', rendering: '5–8 minutos', enhancing: '1,5–2,5 minutos (hasta 3 imágenes a la vez; 30 s por imagen, unos 60 s si necesita el reintento estricto)' };
const LOCATION_FALLBACK = 'residencia mediterránea en España';
const since = (iso: string | undefined, now: number) => iso ? Math.max(0, Math.floor((now - Date.parse(iso)) / 1000)) : null;
const clock = (seconds: number | null) => seconds === null ? '—' : `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;

function Progress({ project, now, lastContact, offline }: { project: Project; now: number; lastContact: number; offline: boolean }) {
  const stageSeconds = project.stage_since?.stage === project.stage ? since(project.stage_since.at, now) : null;
  const cad = isCad(project);
  const enhancing = project.stage === 'enhancing' && project.activity?.kind === 'enhance' ? project.activity : null;
  const showSteps = project.stage === 'interpreting' || (cad && project.stage === 'resolving');
  const activity = showSteps ? project.activity : null;
  const steps = activity?.labels ?? (cad ? dwgSteps : aiSteps);
  const contact = lastContact ? Math.floor((now - lastContact) / 1000) : null;
  const stale = offline || contact === null || contact > 15;
  return <div className="wf-progress-panel" role="status" aria-live="polite">
    <div className="wf-progress-head"><span className="status-dot pulse"/><strong>{stages[project.stage] ?? 'Procesando'}…</strong><span className="wf-clock" aria-label="Tiempo transcurrido">{clock(stageSeconds)}</span></div>
    {enhancing ? <><p className="wf-muted">{enhancing.label}. Los renders originales ya están entregados; si la mejora falla, se mantienen.</p><ol className="wf-ai-steps">{(enhancing.labels ?? []).map((label, i) => {
      const done = enhancing.done?.includes(i), active = enhancing.active?.includes(i);
      const seconds = done ? enhancing.seconds?.[String(i)] ?? null : active ? since(enhancing.item_started?.[String(i)], now) : null;
      return <li key={label + i} className={done ? 'done' : active ? 'active' : ''}><span className="wf-ai-mark">{done ? '✓' : i + 1}</span><span>{label}</span>{seconds !== null ? <span className="wf-clock">{clock(Math.round(seconds))}</span> : null}</li>;
    })}</ol></> : null}
    {showSteps ? <ol className="wf-ai-steps">{steps.map((label, i) => {
      const n = i + 1, state = !activity ? (i === 0 ? 'active' : '') : n < activity.step ? 'done' : n === activity.step ? 'active' : '';
      return <li key={label} className={state}><span className="wf-ai-mark">{state === 'done' ? '✓' : n}</span><span>{label}{state === 'active' && activity?.attempt && activity.attempt > 1 ? ` · corrección ${activity.attempt}` : ''}</span>{state === 'active' ? <span className="wf-clock">{activity ? clock(since(activity.started_at, now)) : 'preparando…'}</span> : null}</li>;
    })}</ol> : null}
    <p className="wf-muted">Duración habitual: {cad && project.stage === 'interpreting' ? '1–4 minutos (lectura local y, si hay dudas, una consulta a la IA)' : expected[project.stage] ?? 'unos minutos'}. El proceso continúa en el servidor aunque cierres esta página o empieces otro plano.</p>
    <p className={`wf-heartbeat ${stale ? 'stale' : ''}`}>{stale ? 'Sin respuesta del servidor; reintentando…' : `Servidor activo · comprobado hace ${contact} s`}</p>
  </div>;
}

class ApiError extends Error {
  issues: Issue[];
  constructor(message: string, issues: Issue[] = []) { super(message); this.issues = issues; }
}
async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, { ...init, headers: { ...(init?.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }), ...init?.headers } });
  const value = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = value?.detail ?? value;
    const issues = detail?.issues ?? value?.issues ?? (Array.isArray(detail) ? detail.map((i: {loc?: (string|number)[];msg?:string}) => ({path:i.loc?.join('.') ?? '',message:i.msg ?? 'Dato no válido'})) : []);
    throw new ApiError(typeof detail === 'string' ? detail : detail?.error ?? detail?.message ?? `No se ha podido completar la operación (${response.status}).`, issues);
  }
  return value as T;
}
const toSrgb = (c: number) => Math.round(255 * Math.min(1, Math.max(0, c <= 0.0031308 ? c * 12.92 : 1.055 * c ** (1 / 2.4) - 0.055)));
const swatch = (f: Finish) => `rgb(${f.color.map(toSrgb).join(',')})`;

function NumberField({ label, value, onChange, min }: { label: string; value: number | null | undefined; onChange: (n: number | null) => void; min?: number }) {
  return <label className="wf-field"><span>{label}</span><input type="number" step="any" min={min} value={value ?? ''} onChange={e => onChange(e.target.value === '' || !Number.isFinite(e.target.valueAsNumber) ? null : e.target.valueAsNumber)} placeholder="Sin confirmar" /></label>;
}
function localIssues(draft: Draft): string[] {
  const result: string[] = [];
  if (draft.calibration.points.length !== 2 || !draft.calibration.metres || draft.calibration.metres <= 0 || !draft.calibration.confirmed) result.push('Marca dos puntos de una cota, indica su distancia real y confirma la escala.');
  if (draft.floor.elevation === null || !draft.floor.confirmed) result.push('Completa y confirma la elevación de la planta.');
  for (const kind of ['wall', 'slab'] as Kind[]) if (!draft.entities.some(e => e.kind === kind)) result.push(`Añade al menos un elemento: ${labels[kind].toLowerCase()}.`);
  const pending = draft.entities.filter(e => !e.confirmed);
  if (pending.length) result.push(`${pending.length} elemento${pending.length === 1 ? '' : 's'} pendiente${pending.length === 1 ? '' : 's'} de confirmar.`);
  if (!draft.complete) result.push('Confirma que has revisado todos los elementos de esta planta.');
  return result;
}

function PlanOverlay({ page, entities, faint, onSelect, selected, pending }: { page: Page; entities: Entity[]; faint: boolean; onSelect?: (id: string) => void; selected?: string; pending?: Pending[] }) {
  const order: Kind[] = ['slab', 'room', 'wall', 'furniture', 'window', 'door', 'roof'];
  const sorted = [...entities].sort((a, b) => order.indexOf(a.kind) - order.indexOf(b.kind));
  return <svg role="img" aria-label="Interpretación de la IA sobre el plano" viewBox={`0 0 ${page.width} ${page.height}`} className="wf-overlay">
    <image href={page.image_url} width={page.width} height={page.height} opacity={faint ? 0.22 : 1} />
    {sorted.map(e => <polygon key={e.id} points={e.polygon.map(p => p.join(',')).join(' ')} fill={kindColors[e.kind]} stroke={kindColors[e.kind]} className={`wf-ai-shape wf-ai-${e.kind} ${selected === e.id ? 'selected' : ''}`} onClick={onSelect ? () => onSelect(e.id) : undefined}><title>{labels[e.kind]}{e.name ? ` · ${e.name.split(' / ').pop()}` : ''}{e.style ? ` · ${e.style}` : ''}</title></polygon>)}
    {/* Furniture footprints are ordered back-left, back-right, front-right, front-left: the arrow shows the front. */}
    {sorted.filter(e => e.kind === 'furniture' && e.polygon.length === 4).map(e => { const [, , fr, fl] = e.polygon; const cx = e.polygon.reduce((a, p) => a + p[0], 0) / 4, cy = e.polygon.reduce((a, p) => a + p[1], 0) / 4; const fx = (fr[0] + fl[0]) / 2, fy = (fr[1] + fl[1]) / 2; return <g key={`${e.id}-front`} className="wf-front"><line x1={cx} y1={cy} x2={fx} y2={fy} /><circle cx={fx} cy={fy} r={Math.max(page.width, page.height) / 380} /></g>; })}
    {(pending ?? []).filter(p => p.polygon?.length).map(p => <polygon key={'pending-' + p.id} className="wf-pending-shape" points={(p.polygon ?? []).map(q => q.join(',')).join(' ')}><title>Pendiente · {p.label}</title></polygon>)}
  </svg>;
}

type Answer = Record<string, string>;
const frontOptions = ['up', 'down', 'left', 'right'];

function answerReady(p: Pending, a?: Answer): boolean {
  if (!a) return false;
  switch (p.type) {
    case 'furniture': return !!a.kind && !!a.front;
    case 'front': return !!a.front;
    case 'opening': return !!a.kind && (a.kind === 'none' || !!a.style);
    case 'orphan_opening': return 'gap' in a;
    case 'room': return !!a.name?.trim();
    case 'layer': return a.walls === 'true' || a.walls === 'false';
    case 'hatch': return !!a.finish;
    default: return false;
  }
}

function answerPayload(p: Pending, a: Answer): Record<string, unknown> {
  switch (p.type) {
    case 'furniture': return { kind: a.kind, name: (furnitureKinds[a.kind] ?? a.kind).replace(/ \(.*\)$/, ''), front: a.front };
    case 'front': return { front: a.front };
    case 'opening': return { kind: a.kind, style: a.kind === 'none' ? 'hinged' : a.style };
    case 'orphan_opening': return { gap: a.gap || null };
    case 'room': return { name: a.name.trim() };
    case 'layer': return { walls: a.walls === 'true' };
    default: return { finish: a.finish };
  }
}

function PendingControl({ p, value, set }: { p: Pending; value?: Answer; set: (patch: Answer) => void }) {
  const select = (key: string, options: [string, string][], placeholder: string) => <select aria-label={`${placeholder} · ${p.label}`} value={value?.[key] ?? ''} onChange={e => set({ [key]: e.target.value })}><option value="">{placeholder}</option>{options.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>;
  const fronts = (withAny: boolean) => select('front', [...frontOptions, ...(withAny ? ['any'] : [])].map(k => [k, `Frente hacia ${sides[k]}`]), 'Orientación…');
  switch (p.type) {
    case 'furniture': return <>{select('kind', Object.entries(furnitureKinds), 'Tipo…')}{fronts(true)}</>;
    case 'front': return fronts(false);
    case 'opening': return <>{select('kind', [['door', 'Puerta'], ['window', 'Ventana'], ['none', 'Sin hueco (mampara, panel fijo…)']], 'Tipo…')}{value?.kind && value.kind !== 'none' ? select('style', [['hinged', 'Abatible'], ['sliding', 'Corredera'], ['glazed', 'Acristalada'], ['casement', 'Practicable'], ['fixed', 'Fija']], 'Estilo…') : null}</>;
    case 'orphan_opening': return <select aria-label={`Hueco · ${p.label}`} value={value?.gap ?? '-'} onChange={e => set({ gap: e.target.value === '-' ? '' : e.target.value })}><option value="-" disabled>Hueco…</option><option value="">No modelar</option>{(p.options ?? []).map(o => <option key={o} value={o}>{o}</option>)}</select>;
    case 'room': return <input aria-label={`Nombre · ${p.label}`} placeholder="Nombre de la estancia" maxLength={80} value={value?.name ?? ''} onChange={e => set({ name: e.target.value })} />;
    case 'layer': return select('walls', [['true', 'Sí, son muros'], ['false', 'No son muros']], '¿Muros?');
    default: return select('finish', [['wood', 'Madera'], ['tile', 'Baldosa'], ['stone', 'Piedra'], ['unknown', 'Desconocido']], 'Pavimento…');
  }
}

function CadPanel({ cad, busy, onAnswer, check = false }: { cad: Cad; busy: boolean; onAnswer: (answers: Record<string, Record<string, unknown>>) => Promise<void>; check?: boolean }) {
  const [answers, setAnswers] = useState<Record<string, Answer>>({});
  const ready = cad.pending.filter(p => answerReady(p, answers[p.id]));
  const u = cad.ai.usage;
  const aiTitle = check ? (cad.ai.items ? 'Pendiente de tu confirmación' : 'Sin dudas') : !cad.ai.items ? 'Sin dudas' : cad.ai.error ? 'No consultada' : cad.ai.cache_hit ? '1 consulta (caché)' : '1 consulta';
  const aiDetail = check ? (cad.ai.items ? `${cad.ai.items} dudas irán en una sola consulta a ${cad.ai.model} (≈ $0,10–0,20) cuando confirmes la lectura.` : 'El dibujo se ha leído sin dudas: no hará falta consultar a la IA.') : !cad.ai.items ? 'El dibujo se ha leído sin dudas: no se ha llamado a la IA.' : cad.ai.error ? cad.ai.error : `${cad.ai.items} dudas · ${u.input.toLocaleString('es')} tokens de entrada, ${u.output.toLocaleString('es')} de salida (${u.reasoning.toLocaleString('es')} de razonamiento) · ≈ ${money(u.cost_usd)}${cad.ai.cache_hit ? ' (ya pagado; 0 tokens nuevos)' : ` · ${cad.ai.seconds} s`} · ${cad.ai.model}`;
  const columns = (['verified', 'inferred', 'user'] as ReadingStatus[]).map(status => ({ status, list: cad.items.filter(i => i.status === status) })).filter(c => (c.status !== 'user' && !(check && c.status === 'inferred')) || c.list.length);
  return <section className="wf-cad" aria-label="Lectura del dibujo DWG">
    <div className="wf-cad-meta">
      <div><span>Fuente</span><strong>{cad.format.toUpperCase()}</strong><small>{cad.converter ? `Convertido en este equipo con ${cad.converter}` : 'DXF leído directamente'} · SHA-256 {cad.sha256.slice(0, 12)}…</small></div>
      <div><span>Unidades y escala</span><strong>{cad.units.name}{cad.units.inferred ? ' (inferidas)' : ''}</strong><small>{cad.units.source}</small></div>
      <div><span>Planta</span><strong>{cad.plan.name}</strong><small>{cad.plan.size_m.join(' × ')} m · leída en {cad.reading_seconds} s</small></div>
      <div><span>IA</span><strong>{aiTitle}</strong><small>{aiDetail}</small></div>
    </div>
    <div className="wf-cad-columns">
      {columns.map(({ status, list }) => <div key={status} className={`wf-cad-col ${status}`}><h4>{readingLabels[status]} <span>{list.length}</span></h4>
        {list.length ? <ul>{list.map(i => <li key={i.id} title={[i.block ? `Bloque ${i.block}` : '', i.layers.join(', '), i.handles.length ? `handles ${i.handles.join(' ')}` : ''].filter(Boolean).join(' · ')}>{i.label}{i.detail ? <small>{i.detail}</small> : null}</li>)}</ul> : <p className="wf-muted">Nada.</p>}</div>)}
      {check ? <div className="wf-cad-col missing"><h4>Dudas para la IA <span>{cad.pending.length}</span></h4>
        {cad.pending.length ? <><p className="wf-muted">El dibujo no las resuelve (en rojo sobre el plano). Se enviarán a la IA cuando confirmes la lectura; después podrás corregir lo que quede.</p>
          <ul>{cad.pending.map(p => <li key={p.id}><strong>{p.label}</strong>{p.detail ? <small>{p.detail}</small> : null}</li>)}</ul></>
          : <p className="wf-muted">Ninguna: el dibujo se ha leído por completo.</p>}
      </div> : <div className="wf-cad-col missing"><h4>{readingLabels.missing} <span>{cad.pending.length}</span></h4>
        {cad.pending.length ? <><p className="wf-muted">El dibujo no lo resuelve{cad.ai.error ? ' y la IA no se ha podido consultar' : ''}. Decide cada punto (marcado en rojo sobre el plano); «arriba» es la parte superior del plano.</p>
          <ul>{cad.pending.map(p => <li key={p.id}><strong>{p.label}</strong>{p.detail ? <small>{p.detail}</small> : null}{!p.blocking ? <small>Opcional: no impide aprobar.</small> : null}<div className="wf-cad-answer"><PendingControl p={p} value={answers[p.id]} set={patch => setAnswers(a => ({ ...a, [p.id]: { ...a[p.id], ...patch } }))} /></div></li>)}</ul>
          <button type="button" className="wf-primary" disabled={busy || !ready.length} onClick={() => void onAnswer(Object.fromEntries(ready.map(p => [p.id, answerPayload(p, answers[p.id])])))}>Aplicar {ready.length || ''} respuesta{ready.length === 1 ? '' : 's'}</button></>
          : <p className="wf-muted">Nada pendiente: todas las lecturas están resueltas.</p>}
      </div>}
    </div>
    {cad.layers?.length ? <details className="wf-cad-notes wf-cad-layers"><summary>Capas del dibujo ({cad.layers.length}; {cad.layers.filter(l => l.status === 'usada').length} usadas, {cad.layers.filter(l => l.status === 'sin uso').length} sin uso)</summary>
      <div className="wf-table-scroll"><table><thead><tr><th>Capa</th><th>Función</th><th>Estado</th><th>Usada para</th><th>Elementos en la planta</th></tr></thead><tbody>{cad.layers.map(l => <tr key={l.layer} className={l.status === 'sin uso' ? 'unused' : ''}><td>{l.layer}</td><td>{l.role ? roleLabels[l.role] ?? l.role : '—'}{l.match && l.match !== 'nombre' ? <small> ({l.match})</small> : null}</td><td>{l.status}</td><td>{l.used.join(', ') || '—'}</td><td>{Object.entries(l.in_plan).map(([t, n]) => `${n} ${t}`).join(', ') || '—'}{l.elsewhere ? <small> · {l.elsewhere} fuera de la planta</small> : null}</td></tr>)}</tbody></table></div></details> : null}
    {cad.notes.length ? <details className="wf-cad-notes"><summary>Notas de la lectura ({cad.notes.length})</summary><ul>{cad.notes.map((n, i) => <li key={i}>{n}</li>)}</ul></details> : null}
  </section>;
}

function ReadingCheck({ cad, plans, busy, onConfirm, onPlan, onRestart }: { cad: Cad; plans: Plan[]; busy: boolean; onConfirm: () => void; onPlan: (index: number) => void; onRestart: () => void }) {
  const doubts = cad.ai.items;
  return <div className="wf-review-head"><div><span className="eyebrow">02 / LECTURA DEL DWG</span><h3>Comprueba que el DWG se ha leído bien</h3>
      <p>Muros, huecos, estancias y bloques se han leído directamente del dibujo, sin IA. Compáralos con el plano original. {doubts ? `Si la lectura es correcta, las ${doubts} dudas que el dibujo no resuelve se enviarán a la IA en una única consulta.` : 'El dibujo no deja dudas: no hará falta consultar a la IA.'}</p></div>
    <div className="wf-review-cta">
      <button type="button" className="wf-primary" disabled={busy} onClick={onConfirm}>{doubts ? 'La lectura es correcta · consultar a la IA' : 'La lectura es correcta · continuar'} →</button>
      <small>{doubts ? `1 consulta a ${cad.ai.model} · ≈ $0,10–0,20` : 'Sin coste de IA.'}</small>
      <div className="wf-check-alt">
        {plans.length > 1 ? <label>¿Planta equivocada? <select aria-label="Elegir otra planta" value={cad.plan.index} disabled={busy} onChange={e => onPlan(Number(e.target.value))}>{plans.map(p => <option key={p.index} value={p.index}>{p.index + 1}. {p.name} ({p.size_m.join(' × ')} m)</option>)}</select></label> : null}
        <button type="button" disabled={busy} onClick={onRestart}>Subir otro plano</button>
      </div>
    </div></div>;
}

const pct = (v?: number) => typeof v === 'number' ? `${Math.round(v * 100)} %` : '';

function EnhanceOptions({ project, text, setText, enhance, setEnhance, disabled }: { project: Project; text: string; setText: (v: string) => void; enhance: boolean; setEnhance: (v: boolean) => void; disabled: boolean }) {
  const place = project.location;
  const server = project.enhance_server !== false;
  const origin = !place || place.status === 'missing'
    ? `No se ha encontrado en el plano. Si lo dejas vacío se usará «${LOCATION_FALLBACK}».`
    : place.status === 'user' ? 'Indicada por ti.'
    : `${place.status === 'verified' ? 'Leída del plano' : 'Inferida'} (${place.source?.label ?? place.method ?? ''}) · confianza ${pct(place.confidence)}${place.derived?.length ? ' · región y país deducidos del código postal' : ''}.`;
  return <div className="wf-enhance-options">
    <label className="wf-field"><span>Ubicación del proyecto <em>(luz, clima, vegetación y vistas; nunca cambia el edificio)</em></span>
      <input value={text} maxLength={300} disabled={disabled} placeholder={LOCATION_FALLBACK} onChange={e => setText(e.target.value)} /><small>{origin}</small></label>
    <label className="wf-confirm"><input type="checkbox" checked={enhance && server} disabled={disabled || !server} onChange={e => setEnhance(e.target.checked)} /> Mejorar renders con IA <small>{server ? '(imágenes ilustrativas; se conservan los originales)' : '(desactivado en este servidor)'}</small></label>
  </div>;
}

function AiUsage({ project }: { project: Project }) {
  const calls = project.ai_usage?.plan?.calls ?? [];
  const tokens = calls.filter(c => !c.cache_hit).reduce((sum, c) => sum + (c.usage?.total_tokens ?? 0), 0);
  const e = project.enhancement ?? project.ai_usage?.enhancement;
  if (!calls.length && !e) return null;
  const enhanceText = !e ? null : e.status === 'disabled' ? 'mejora con IA desactivada'
    : e.status === 'unavailable' ? 'mejora con IA sin clave de API'
    : `mejora con IA: ${e.accepted ?? 0}/${e.images ?? 0} imágenes · ≈ ${money(e.cost_usd ?? 0)}${e.cost_usd_new === 0 && (e.cost_usd ?? 0) > 0 ? ' (caché, 0 nuevo)' : ''} · ${clock(Math.round(e.seconds ?? 0))}${e.model ? ` · ${e.model}` : ''}`;
  return <p className="wf-ai-usage">Uso de IA · {calls.length ? `interpretación: ${calls.length} llamada${calls.length === 1 ? '' : 's'}${tokens ? `, ${tokens.toLocaleString('es')} tokens nuevos` : ' (caché)'}` : 'interpretación: —'}{enhanceText ? ` · ${enhanceText}` : ''}{e && e.status !== 'completed' && e.notice ? <span className="wf-warn"> · {e.notice}</span> : null}</p>;
}

export default function Workflow({ onResult, newRequest = 0 }: { onResult: (url: string | null) => void; newRequest?: number }) {
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [project, setProject] = useState<Project | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [dirty, setDirty] = useState(false);
  const [working, setWorking] = useState(false);
  const [offline, setOffline] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [issues, setIssues] = useState<Issue[]>([]);
  const [file, setFile] = useState<File | null>(null);
  const [description, setDescription] = useState('');
  const [materialsText, setMaterialsText] = useState('');
  const [locationText, setLocationText] = useState('');
  const [enhanceChoice, setEnhanceChoice] = useState(true);
  const [showAI, setShowAI] = useState(true);
  const [selected, setSelected] = useState('');
  const [kind, setKind] = useState<Kind>('wall');
  const [mode, setMode] = useState<'select' | 'scale' | 'draw'>('select');
  const [points, setPoints] = useState<Point[]>([]);
  const [candidates, setCandidates] = useState(false);
  const [zoom, setZoom] = useState(1);
  const [linkViews, setLinkViews] = useState(true);
  const [sharedView, setSharedView] = useState<View | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const [lastContact, setLastContact] = useState(0);
  const shownResult = useRef('');
  const resultCallback = useRef(onResult);
  useEffect(() => { resultCallback.current = onResult; }, [onResult]);

  const remember = useCallback((p: Project, replaceDraft = true) => {
    setProject(p); setIssues(p.issues ?? []);
    if (replaceDraft) { setDraft(p.draft ?? null); setDirty(false); setMaterialsText(p.description ?? ''); setLocationText(p.location?.text ?? ''); setEnhanceChoice(p.enhance ?? true); }
    try { localStorage.setItem('gc-active-project', p.id); } catch { /* Storage can be unavailable in private mode. */ }
    if (p.status === 'succeeded' && p.manifest_url && shownResult.current !== p.manifest_url) {
      shownResult.current = p.manifest_url; resultCallback.current(p.manifest_url);
    }
    setProjects(list => [{id:p.id,filename:p.filename,status:p.status,stage:p.stage}, ...list.filter(i=>i.id!==p.id)]);
  }, []);
  const refreshProjects = useCallback(async (signal?: AbortSignal) => {
    try { const data = await request<{projects:ProjectSummary[]}>('/api/projects', { signal }); setProjects(data.projects); setOffline(false); }
    catch (reason) { if (!(reason instanceof DOMException && reason.name === 'AbortError')) setOffline(true); }
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    void refreshProjects(controller.signal);
    // A #project=<id> link opens that project directly; otherwise resume the last one.
    let id: string | null = /#project=([a-f0-9]{32})$/.exec(window.location.hash)?.[1] ?? null;
    try { id = id ?? localStorage.getItem('gc-active-project'); } catch { /* Optional persistence. */ }
    if (id) request<Project>(`/api/projects/${encodeURIComponent(id)}`, {signal:controller.signal}).then(remember).catch(() => {});
    return () => controller.abort();
  }, [refreshProjects, remember]);
  // A #project=<id> link opened in a tab that already shows the app switches project too.
  const openLinkedRef = useRef<(id: string) => void>(() => {});
  useEffect(() => {
    const onHash = () => { const id = /#project=([a-f0-9]{32})$/.exec(window.location.hash)?.[1]; if (id) openLinkedRef.current(id); };
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);
  useEffect(() => {
    if (!project || !busyStates.has(project.status)) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const next = await request<Project>(`/api/projects/${project.id}`, {signal:controller.signal});
        if (!controller.signal.aborted) { remember(next); setError(''); setLastContact(Date.now()); if (busyStates.has(next.status)) timer = setTimeout(poll, 1200); }
      } catch (reason) {
        if (!controller.signal.aborted) { setError(reason instanceof Error ? reason.message : 'No se pudo consultar el progreso.'); timer = setTimeout(poll, 2500); }
      }
    };
    timer = setTimeout(poll, 1000);
    return () => { controller.abort(); clearTimeout(timer); };
  }, [project?.id, project?.status, remember]);

  const busy = working || !!project && busyStates.has(project.status);
  useEffect(() => {
    if (!project || !busyStates.has(project.status)) return;
    setLastContact(Date.now());
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [project?.id, project?.status]);
  const page = project?.pages?.find(p => p.page === draft?.page);
  const pageUrl = page?.image_url;
  useEffect(() => { setSharedView(null); }, [pageUrl]);
  const fileFormat = file ? (/\.(pdf|dwg|dxf)$/i.exec(file.name)?.[1] ?? '').toUpperCase() : '';
  const cad = isCad(project) ? project?.cad : undefined;
  const blockingPending = cad?.pending.filter(p => p.blocking).length ?? 0;
  const entity = draft?.entities.find(e => e.id === selected);
  const warnings = draft ? localIssues(draft) : [];
  const interpreted = !!draft?.conceptual;
  const readingCheck = !!cad && project?.stage === 'reading_check';
  const rendering = !!project && (project.status === 'queued' || (project.status === 'running' && renderStages.includes(project.stage)));
  const step = !project ? 1 : project.status === 'succeeded' || rendering ? 3 : 2;
  const counts = (draft?.entities ?? []).reduce<Partial<Record<Kind, number>>>((acc, e) => ({...acc, [e.kind]: (acc[e.kind] ?? 0) + 1}), {});
  const rooms = (draft?.entities ?? []).filter(e => e.kind === 'room' && e.name).map(e => `${e.name}${e.finish ? ` · ${floorLabels[e.finish] ?? e.finish}` : ''}`);

  const mutate = (change: (d: Draft) => Draft) => {
    setDraft(d => d ? { ...change(d), complete: false } : d); setDirty(true); setNotice(''); setIssues([]);
  };
  const updateEntity = (patch: Partial<Entity>) => mutate(d => ({...d, entities:d.entities.map(e => e.id === selected ? {...e,...patch,confirmed:patch.confirmed ?? false} : e)}));
  const addEntity = (polygon: Point[]) => {
    if (!draft || polygon.length < 3) return;
    const id = `${kind}-${crypto.randomUUID().slice(0,8)}`;
    const added: Entity = { id, kind, polygon, confirmed:false };
    if (kind === 'room') added.name = '';
    mutate(d => ({...d,entities:[...d.entities,added]})); setSelected(id); setPoints([]); setMode('select');
  };
  const showError = (reason: unknown) => { setError(reason instanceof Error ? reason.message : 'No se pudo completar la operación.'); if (reason instanceof ApiError) setIssues(reason.issues); };

  const chooseFile = (event: ChangeEvent<HTMLInputElement>) => {
    const chosen = event.target.files?.[0] ?? null;
    if (chosen && (!/\.(pdf|dwg|dxf)$/i.test(chosen.name) || chosen.size > 50 * 1024 * 1024)) { setError('Selecciona un plano PDF, DWG o DXF de hasta 50 MB.'); event.target.value=''; setFile(null); return; }
    setError(''); setFile(chosen);
  };
  const upload = async (event: FormEvent) => {
    event.preventDefault();
    if (!file || busy) return;
    if (dirty && !window.confirm('Hay cambios sin guardar en el proyecto actual. ¿Descartarlos?')) return;
    setWorking(true); setError(''); setNotice(''); setIssues([]);
    try {
      const body = new FormData(); body.append('file', file); body.append('description', description.trim());
      const p = await request<Project>('/api/projects', {method:'POST', body});
      shownResult.current = ''; onResult(null);
      remember(p); setOffline(false); setSelected(''); setPoints([]); setFile(null); setDescription(''); setShowAI(true);
    } catch (reason) { showError(reason); } finally { setWorking(false); }
  };
  // Starting a new blueprint never waits for the current one: server jobs keep running and
  // the project stays available from the "Proyectos" list.
  const newProject = () => {
    if (working || dirty && !window.confirm('Hay cambios sin guardar. ¿Descartarlos?')) return;
    setProject(null); setDraft(null); setDirty(false); setError(''); setNotice(''); setIssues([]);
    setSelected(''); setPoints([]); setMode('select'); setFile(null); setDescription(''); setShowAI(true);
    shownResult.current = ''; onResult(null);
    try { localStorage.removeItem('gc-active-project'); } catch { /* Optional persistence. */ }
    if (window.location.hash.startsWith('#project=')) window.history.replaceState(null, '', '#new-project');
    void refreshProjects();
    requestAnimationFrame(() => document.getElementById('new-project')?.scrollIntoView({behavior:'smooth'}));
  };
  const newProjectRef = useRef(newProject);
  newProjectRef.current = newProject;
  useEffect(() => { if (newRequest) newProjectRef.current(); }, [newRequest]);
  openLinkedRef.current = id => { if (id !== project?.id) void openProject(id); };
  const openProject = async (id: string) => {
    if (!id || working || dirty && !window.confirm('Hay cambios sin guardar. ¿Quieres descartarlos y abrir otro proyecto?')) return;
    setWorking(true); setError(''); shownResult.current = ''; onResult(null);
    try { remember(await request<Project>(`/api/projects/${id}`)); setSelected(''); setPoints([]); setNotice(''); }
    catch (reason) { showError(reason); } finally { setWorking(false); }
  };
  const save = async (): Promise<Project | null> => {
    if (!project || !draft) return null;
    const saved = await request<Project>(`/api/projects/${project.id}/draft`,{method:'PUT',body:JSON.stringify({draft,revision:project.revision})});
    remember(saved); return saved;
  };
  const action = async (operation: 'save'|'validate'|'generate'|'interpret'|'approve') => {
    if (!project || busy) return;
    setWorking(true); setError(''); setNotice(''); setIssues([]);
    try {
      const saved = dirty ? await save() : project;
      if (!saved) return;
      if (operation === 'save') { setNotice('Revisión guardada.'); return; }
      const result = await request<Project>(`/api/projects/${saved.id}/${operation}`,{method:'POST',body:JSON.stringify({revision:saved.revision})});
      if (operation === 'approve' || operation === 'generate') { shownResult.current = ''; onResult(null); }
      remember(result);
      if (operation === 'validate' && !result.issues?.length) setNotice('Los datos revisados son coherentes. Ya puedes generar.');
    } catch (reason) { showError(reason); } finally { setWorking(false); }
  };
  // Approval carries the «Mejorar renders con IA» choice; an edited location is saved first.
  const approveProject = async () => {
    if (!project || busy) return;
    setWorking(true); setError(''); setNotice(''); setIssues([]);
    try {
      let saved = dirty ? await save() : project;
      if (!saved) return;
      if (locationText.trim() !== (saved.location?.text ?? '')) {
        saved = await request<Project>(`/api/projects/${saved.id}/location`, { method: 'PUT', body: JSON.stringify({ revision: saved.revision, text: locationText.trim() }) });
        remember(saved, false);
      }
      const result = await request<Project>(`/api/projects/${saved.id}/approve`, { method: 'POST', body: JSON.stringify({ revision: saved.revision, enhance: enhanceChoice }) });
      shownResult.current = ''; onResult(null); remember(result);
    } catch (reason) { showError(reason); } finally { setWorking(false); }
  };
  const enhanceAgain = async () => {
    if (!project || busy) return;
    setWorking(true); setError(''); setNotice('');
    try {
      let saved = project;
      if (locationText.trim() !== (saved.location?.text ?? '')) {
        saved = await request<Project>(`/api/projects/${saved.id}/location`, { method: 'PUT', body: JSON.stringify({ revision: saved.revision, text: locationText.trim() }) });
      }
      remember(await request<Project>(`/api/projects/${saved.id}/enhance`, { method: 'POST', body: JSON.stringify({ revision: saved.revision }) }), false);
    } catch (reason) { showError(reason); } finally { setWorking(false); }
  };
  const sendAnswers = async (answers: Record<string, Record<string, unknown>>) => {
    if (!project || busy) return;
    setWorking(true); setError(''); setNotice(''); setIssues([]);
    try {
      const saved = dirty ? await save() : project;
      if (!saved) return;
      remember(await request<Project>(`/api/projects/${saved.id}/answers`, { method: 'PUT', body: JSON.stringify({ revision: saved.revision, answers }) }));
    } catch (reason) { showError(reason); } finally { setWorking(false); }
  };
  const confirmReading = async () => {
    if (!project || busy) return;
    setWorking(true); setError(''); setNotice(''); setIssues([]);
    try { remember(await request<Project>(`/api/projects/${project.id}/confirm-reading`, { method: 'POST', body: JSON.stringify({ revision: project.revision }) })); }
    catch (reason) { showError(reason); } finally { setWorking(false); }
  };
  const choosePlan = async (plan: number) => {
    if (!project || busy) return;
    setWorking(true); setError('');
    try { remember(await request<Project>(`/api/projects/${project.id}/plan`, { method: 'POST', body: JSON.stringify({ revision: project.revision, plan }) })); }
    catch (reason) { showError(reason); } finally { setWorking(false); }
  };
  const updateMaterials = async () => {
    if (!project || busy) return;
    setWorking(true); setError(''); setNotice('');
    try {
      const saved = dirty ? await save() : project;
      if (!saved) return;
      remember(await request<Project>(`/api/projects/${saved.id}/description`,{method:'PUT',body:JSON.stringify({revision:saved.revision,description:materialsText.trim()})}), false);
    } catch (reason) { showError(reason); } finally { setWorking(false); }
  };
  const clickPlan = (event: MouseEvent<SVGSVGElement>) => {
    if (!page || busy || mode === 'select') return;
    const rect = event.currentTarget.getBoundingClientRect();
    const point: Point = [Math.max(0,Math.min(page.width,Math.round((event.clientX-rect.left)/rect.width*page.width*1000)/1000)),Math.max(0,Math.min(page.height,Math.round((event.clientY-rect.top)/rect.height*page.height*1000)/1000))];
    if (mode === 'scale') mutate(d => ({...d, calibration:{...d.calibration,points:d.calibration.points.length >= 2 ? [point] : [...d.calibration.points,point],confirmed:false},entities:d.entities.map(e=>({...e,confirmed:false}))}));
    else setPoints(p => [...p,point]);
  };

  return <section className="workflow" id="new-project" aria-labelledby="workflow-title">
    <div className="wf-heading"><div><span className="eyebrow">ESTUDIO DE VISUALIZACIÓN</span><h2 id="workflow-title">Del plano a los renders, en tres pasos.</h2><p>Sube el plano en PDF y, si quieres, describe los materiales. La IA interpreta el plano, lo revisas junto al original y Blender genera los renders y el modelo 3D.</p></div>
      {projects.length ? <label className="wf-project-picker">Proyectos<select aria-label="Abrir proyecto" value={project?.id ?? ''} disabled={working} onChange={e=>void openProject(e.target.value)}><option value="">Selecciona un proyecto</option>{projects.map(p=><option key={p.id} value={p.id}>{p.filename} · {phases[p.status]}</option>)}</select></label> : null}
    </div>
    <ol className="wf-steps" aria-label="Pasos del proyecto">
      {['Subir plano', 'Revisar interpretación', 'Renders con Blender'].map((label, i) => <li key={label} className={step === i + 1 ? 'active' : step > i + 1 ? 'done' : ''} aria-current={step === i + 1 ? 'step' : undefined}>{String(i + 1).padStart(2, '0')} <span>{label}</span></li>)}
    </ol>
    {offline ? <div className="wf-message wf-error" role="status">No hay conexión con el servidor del estudio. Inícialo con <code>uv run python -m pipelines.web.server</code>.<button onClick={()=>void refreshProjects()}>Reintentar</button></div> : null}
    {error ? <div className="wf-message wf-error" role="alert"><strong>No se ha completado la operación.</strong><p>{error}</p>{error.toLowerCase().includes('otra pestaña') ? <button onClick={()=>project&&void openProject(project.id)}>Recargar</button> : null}</div> : null}
    {notice ? <p className="wf-message" role="status">{notice}</p> : null}

    {!project ? <form className="wf-upload-card" onSubmit={e=>void upload(e)}>
      <label className={`wf-drop ${file ? 'has-file' : ''}`}>
        <input type="file" accept="application/pdf,.pdf,.dwg,.dxf" onChange={chooseFile} disabled={busy} aria-label="Plano en PDF, DWG o DXF" />
        <span className="wf-drop-title">{file ? file.name : 'Selecciona el plano en PDF, DWG o DXF'}</span>
        <span className="wf-drop-hint">{file ? <><span className="wf-format">{fileFormat}</span> {(file.size / 1024 / 1024).toFixed(1)} MB · listo para interpretar</> : 'PDF: una planta con escala impresa (p. ej. 1:50). DWG/DXF: el dibujo en espacio modelo. Máx. 50 MB.'}</span>
      </label>
      <label className="wf-field wf-description"><span>Materiales y acabados <em>(opcional)</em></span>
        <textarea rows={5} maxLength={MAX_DESCRIPTION} value={description} onChange={e=>setDescription(e.target.value)} placeholder="Ej.: suelo de roble natural, paredes blanco roto, muebles de nogal, sofá de lino gris y baños con cerámica blanca." />
        <small>{description.length}/{MAX_DESCRIPTION} · Se aplica a paredes, suelo, puertas, madera, tapicería y cerámica.</small>
      </label>
      <div className="wf-upload-actions"><button type="submit" className="wf-primary" disabled={!file || busy}>{working ? 'Subiendo…' : 'Interpretar plano →'}</button><small>{fileFormat && fileFormat !== 'PDF' ? `El ${fileFormat} se lee en este equipo; solo las dudas (texto breve) se envían a OpenAI.` : 'El PDF se envía a la API de OpenAI para interpretarlo.'}</small></div>
    </form> : <>
      <div className="wf-job" role="status"><span className={`status-dot ${busy?'pulse':''}`}/><strong>{project.filename}</strong><span>{stages[project.stage] ?? project.stage}</span>
        {project.status==='succeeded'&&project.manifest_url?<button onClick={()=>document.getElementById('explore')?.scrollIntoView({behavior:'smooth'})}>Ver renders ↓</button>:null}
        {project.status==='succeeded'&&project.result_revision===project.revision&&project.enhance_server!==false?<button type="button" disabled={working} onClick={()=>void enhanceAgain()} title="Repite solo la mejora con IA sobre los renders ya generados (sin Blender); hace llamadas nuevas a OpenAI">Mejorar de nuevo</button>:null}
        <button type="button" onClick={newProject} disabled={working}>Nuevo plano</button></div>
      <AiUsage project={project} />
      {rendering ? <div className="wf-progress" aria-label="Progreso de Blender"><div style={{width:`${Math.max(6, renderStages.indexOf(project.stage) / (renderStages.length - 1) * 100)}%`}}/></div> : null}
      {project.error ? <div className="wf-message wf-error" role="alert"><strong>{project.stage === 'generation_failed' ? 'La generación se ha detenido.' : 'Atención'}</strong><p>{project.error}</p>{!busy && project.pages?.length ? <button type="button" onClick={()=>void action('interpret')}>Reintentar interpretación</button> : null}</div> : null}
      {busyStates.has(project.status) ? <Progress project={project} now={now} lastContact={lastContact} offline={offline} /> : null}
      {project.stage === 'choose_plan' && project.plans?.length ? <div className="wf-plan-choice"><h3>El dibujo contiene {project.plans.length} plantas. ¿Cuál quieres modelar?</h3><img src={`/api/projects/${project.id}/files/overview.png`} alt="Plantas encontradas en el dibujo, numeradas" /><div className="wf-plan-buttons">{project.plans.map(pl => <button key={pl.index} type="button" disabled={working} onClick={() => void choosePlan(pl.index)}><strong>{pl.index + 1}</strong> {pl.name} · {pl.size_m.join(' × ')} m</button>)}</div></div> : null}
    </>}

    {project && draft && page ? <div className={`wf-review ${readingCheck ? 'reading-check' : ''}`}>
      {interpreted ? <>
        {readingCheck && cad ? <ReadingCheck cad={cad} plans={project.plans ?? cad.plans ?? []} busy={busy} onConfirm={() => void confirmReading()} onPlan={plan => void choosePlan(plan)} onRestart={newProject} /> : <><div className="wf-review-head"><div><span className="eyebrow">02 / REVISIÓN</span><h3>Comprueba la interpretación junto al plano original</h3><p>{cad ? 'Muros, huecos, bloques y textos se han leído directamente del DWG; la IA solo ha resuelto las dudas. Revisa abajo qué es verificado, qué inferido y qué queda pendiente.' : 'La IA ha seleccionado muros y huecos sobre los vectores del PDF y propone mobiliario. Si algo no encaja, vuelve a interpretar o usa la edición avanzada.'}</p></div>
          <div className="wf-review-cta"><EnhanceOptions project={project} text={locationText} setText={setLocationText} enhance={enhanceChoice} setEnhance={setEnhanceChoice} disabled={busy} /><button type="button" className="wf-primary" disabled={busy || blockingPending > 0} onClick={()=>void approveProject()}>{project.status==='succeeded'&&project.result_revision===project.revision?'Regenerar renders':'Aprobar y generar renders'} →</button><small>{blockingPending ? `Resuelve ${blockingPending} lectura${blockingPending === 1 ? '' : 's'} pendiente${blockingPending === 1 ? '' : 's'} para aprobar.` : cad ? 'Medidas leídas del DWG; alturas supuestas.' : 'Las medidas son inferidas a partir del PDF y su escala.'}</small></div></div></>}
        <div className="wf-compare-bar"><label className="wf-toggle"><input type="checkbox" checked={linkViews} onChange={e=>{setLinkViews(e.target.checked);setSharedView(null);}}/> Sincronizar vistas</label><span className="wf-muted">Rueda o pellizco para ampliar · arrastra para moverte · doble clic acerca</span></div>
        <div className="wf-compare">
          <figure><figcaption>{cad ? `Dibujo ${cad.format.toUpperCase()} (vista local del archivo)` : 'Plano original'}</figcaption><ZoomPane key={`orig-${page.image_url}-${linkViews}`} aspect={page.width / page.height} label="plano original" {...(linkViews ? { view: sharedView, onView: setSharedView } : {})}><img src={page.image_url} alt={cad ? 'Dibujo DWG original' : `Plano original, página ${page.page}`} draggable={false} /></ZoomPane></figure>
          <figure><figcaption>{readingCheck ? 'Lectura del programa (sin IA)' : 'Interpretación de la IA'} <label className="wf-toggle"><input type="checkbox" checked={showAI} onChange={e=>setShowAI(e.target.checked)}/> Superponer</label></figcaption><ZoomPane key={`ai-${page.image_url}-${linkViews}`} aspect={page.width / page.height} label="interpretación de la IA" {...(linkViews ? { view: sharedView, onView: setSharedView } : {})}><PlanOverlay page={page} entities={showAI ? draft.entities : []} faint={showAI} pending={cad?.pending} /></ZoomPane></figure>
        </div>
        <p className="wf-muted wf-legend-note">Las flechas de los muebles indican su frente (orientación).</p><ul className="wf-legend" aria-label="Elementos interpretados">{(['wall','door','window','room','furniture'] as Kind[]).map(k=><li key={k}><span style={{background:kindColors[k]}}/>{counts[k] ?? 0} {plural[k]}</li>)}</ul>
        {cad ? <CadPanel key={`${project.id}-${project.revision}`} cad={cad} busy={busy} onAnswer={sendAnswers} check={readingCheck} /> : null}
        <div className="wf-review-grid">
          <section><h4>Estancias</h4>{rooms.length ? <ul className="wf-chips">{rooms.map((r, i)=><li key={`${r}-${i}`}>{r}</li>)}</ul> : <p className="wf-muted">No se delimitaron estancias cerradas.</p>}</section>
          <section><h4>Materiales <small className="wf-muted">· estilo lujo minimalista</small></h4>
            {draft.finishes && Object.keys(draft.finishes).length ? <ul className="wf-swatches">{Object.entries(draft.finishes).map(([k, f])=><li key={k}><span style={{background:swatch(f)}}/><div><strong>{finishLabels[k] ?? k}</strong>{f.name}</div></li>)}</ul> : <p className="wf-muted">Paleta del estudio: roble natural, mármol Calacatta, latón cepillado, bouclé marfil.</p>}
            {project.finishes_error ? <p className="wf-muted wf-warn">{project.finishes_error}</p> : null}
            <label className="wf-field"><span>Descripción de materiales</span><textarea rows={3} maxLength={MAX_DESCRIPTION} value={materialsText} disabled={busy} onChange={e=>setMaterialsText(e.target.value)} placeholder="Opcional: describe suelos, paredes, madera, tapicería…"/></label>
            <button type="button" disabled={busy || materialsText.trim() === (project.description ?? '')} onClick={()=>void updateMaterials()}>Actualizar materiales</button>
          </section>
          <section><h4>Supuestos y dudas ({draft.assumptions?.length ?? 0})</h4><details><summary>Ver lo que la IA ha supuesto</summary><ul className="wf-assumptions">{(draft.assumptions ?? []).map((a, i)=><li key={i}>{a}</li>)}</ul></details>
            <button type="button" disabled={busy} onClick={()=>void action('interpret')}>Volver a interpretar</button></section>
        </div>
      </> : <div className="wf-message"><strong>Sin interpretación automática.</strong><p>Puedes reintentar la interpretación o delimitar el plano manualmente en la edición avanzada.</p></div>}

      <details className="wf-advanced" open={!interpreted}>
        <summary>Edición avanzada (manual)</summary>
        <fieldset className="wf-editor" disabled={busy}><legend className="sr-only">Edición manual del plano</legend>
          <div className="wf-review-layout"><div className="wf-plan-column">
            <div className="wf-drawing-tools" role="group" aria-label="Herramientas del plano"><button type="button" aria-pressed={mode==='select'} onClick={()=>{setMode('select');setPoints([]);}}>Seleccionar</button><button type="button" aria-pressed={mode==='scale'} onClick={()=>{setMode('scale');setPoints([]);}}>Marcar cota</button><select aria-label="Tipo de elemento a dibujar" value={kind} onChange={e=>setKind(e.target.value as Kind)}>{Object.entries(labels).map(([key,label])=><option key={key} value={key}>{label}</option>)}</select><button type="button" aria-pressed={mode==='draw'} onClick={()=>{setMode('draw');setPoints([]);}}>Dibujar contorno</button></div>
            <p className="wf-plan-help" role="status">{mode==='scale'?'Pulsa los dos extremos de una cota conocida.':mode==='draw'?`Marca los vértices del contorno (${labels[kind].toLowerCase()}) y pulsa Cerrar contorno.`:'Selecciona un elemento para editar sus propiedades.'}</p>
            <div className="wf-plan-options"><label><input type="checkbox" checked={candidates} onChange={e=>setCandidates(e.target.checked)}/> Mostrar rectángulos detectados</label><label>Ampliación <select aria-label="Ampliación del plano" value={zoom} onChange={e=>setZoom(Number(e.target.value))}><option value={1}>100%</option><option value={1.5}>150%</option><option value={2}>200%</option><option value={3}>300%</option></select></label></div>
            <div className={`wf-plan-frame ${mode!=='select'?'crosshair':''}`}><svg role="img" aria-label={`Plano, página ${page.page}. Edición manual.`} viewBox={`0 0 ${page.width} ${page.height}`} style={{width:`${zoom*100}%`,aspectRatio:`${page.width} / ${page.height}`}} onClick={clickPlan}><image href={page.image_url} width={page.width} height={page.height} opacity={0.5}/>{candidates ? page.candidates.map(c=><polygon key={c.id} points={c.polygon.map(p=>p.join(',')).join(' ')} className="wf-candidate" onClick={e=>{if(mode==='select'&&!busy){e.stopPropagation();addEntity(c.polygon);}}}><title>{c.label} · Añadir como {labels[kind]}</title></polygon>):null}{draft.entities.map(e=><polygon key={e.id} points={e.polygon.map(p=>p.join(',')).join(' ')} fill={kindColors[e.kind]} stroke={selected===e.id?'#161f13':kindColors[e.kind]} className={`wf-polygon ${e.confirmed?'confirmed':''} ${selected===e.id?'selected':''}`} onClick={event=>{if(mode==='select'){event.stopPropagation();setSelected(e.id);}}}><title>{e.id} · {labels[e.kind]}</title></polygon>)}{draft.calibration.points.length===2?<line x1={draft.calibration.points[0][0]} y1={draft.calibration.points[0][1]} x2={draft.calibration.points[1][0]} y2={draft.calibration.points[1][1]} className="wf-scale-line"/>:null}{draft.calibration.points.map((p,i)=><circle key={i} cx={p[0]} cy={p[1]} r={3} className="wf-scale-point"/>)}{points.length?<polyline points={points.map(p=>p.join(',')).join(' ')} className="wf-in-progress"/>:null}{points.map((p,i)=><circle key={i} cx={p[0]} cy={p[1]} r={2.5} fill="#c25331"/>)}</svg></div>
            {mode==='draw'?<div className="wf-draw-finish"><span>{points.length} vértices</span><button type="button" disabled={points.length<3} onClick={()=>addEntity(points)}>Cerrar contorno</button><button type="button" disabled={!points.length} onClick={()=>setPoints(p=>p.slice(0,-1))}>Deshacer punto</button></div>:null}
          </div><aside className="wf-inspector">
            <section className="wf-inspector-section"><h3>Escala y planta</h3><NumberField label="Distancia real de la cota (m)" value={draft.calibration.metres} min={0} onChange={metres=>mutate(d=>({...d,calibration:{...d.calibration,metres,confirmed:false},entities:d.entities.map(e=>({...e,confirmed:false}))}))}/><label className="wf-confirm"><input type="checkbox" checked={draft.calibration.confirmed} disabled={draft.calibration.points.length!==2||!draft.calibration.metres} onChange={e=>mutate(d=>({...d,calibration:{...d.calibration,confirmed:e.target.checked}}))}/> Escala comprobada</label><NumberField label="Elevación de planta (m)" value={draft.floor.elevation} onChange={elevation=>mutate(d=>({...d,floor:{...d.floor,elevation,confirmed:false}}))}/><label className="wf-confirm"><input type="checkbox" checked={draft.floor.confirmed} disabled={draft.floor.elevation===null} onChange={e=>mutate(d=>({...d,floor:{...d.floor,confirmed:e.target.checked}}))}/> Elevación verificada</label></section>
            <section className="wf-inspector-section"><h3>Elementos <span>{draft.entities.length}</span></h3><label className="wf-field"><span>Seleccionar elemento</span><select value={selected} onChange={e=>setSelected(e.target.value)}><option value="">Elige un elemento</option>{draft.entities.map(e=><option key={e.id} value={e.id}>{e.confirmed?'✓':'○'} {e.id} · {labels[e.kind]}{e.name?` · ${e.name}`:''}</option>)}</select></label>{entity?<div className="wf-entity-fields"><div className="wf-entity-kind"><span style={{background:kindColors[entity.kind]}}/>{labels[entity.kind]}<small>{entity.id}</small></div>{entity.kind==='room'||entity.kind==='furniture'?<label className="wf-field"><span>Nombre</span><input value={entity.name??''} onChange={e=>updateEntity({name:e.target.value})}/></label>:null}{['wall','door','window','furniture'].includes(entity.kind)?<NumberField label="Altura (m)" value={entity.height} min={0} onChange={height=>updateEntity({height})}/>:null}{['wall','slab','roof'].includes(entity.kind)?<NumberField label="Espesor (m)" value={entity.thickness} min={0} onChange={thickness=>updateEntity({thickness})}/>:null}{['slab','roof'].includes(entity.kind)?<NumberField label="Cota inferior (m)" value={entity.elevation} onChange={elevation=>updateEntity({elevation})}/>:null}{entity.kind==='door'||entity.kind==='window'?<><label className="wf-field"><span>Muro que contiene el hueco</span><select value={entity.wall_id??''} onChange={e=>updateEntity({wall_id:e.target.value})}><option value="">Selecciona el muro</option>{draft.entities.filter(e=>e.kind==='wall').map(e=><option key={e.id} value={e.id}>{e.id}</option>)}</select></label><NumberField label="Altura del borde inferior (m)" value={entity.sill} min={0} onChange={sill=>updateEntity({sill})}/></>:null}<label className="wf-confirm"><input type="checkbox" checked={entity.confirmed} onChange={e=>updateEntity({confirmed:e.target.checked})}/> Verificado</label><button type="button" className="wf-delete" onClick={()=>{mutate(d=>({...d,entities:d.entities.filter(e=>e.id!==selected).map(e=>e.wall_id===selected?{...e,wall_id:'',confirmed:false}:e)}));setSelected('');}}>Eliminar este elemento</button></div>:<p className="wf-muted">Dibuja un contorno, elige un rectángulo detectado o selecciona un elemento.</p>}</section>
          </aside></div>
          <div className="wf-final-review"><div><h3>Generar desde la edición manual</h3><label className="wf-confirm"><input type="checkbox" checked={draft.complete} onChange={e=>{setDraft(d=>d?{...d,complete:e.target.checked}:d);setDirty(true);setNotice('');}}/> He revisado todos los elementos y autorizo generar este modelo.</label>{warnings.length?<ul className="wf-pending">{warnings.map(w=><li key={w}>{w}</li>)}</ul>:<p className="wf-ready">La revisión manual está completa.</p>}</div><div className="wf-review-actions"><button type="button" onClick={()=>void action('save')} disabled={!dirty}>Guardar{dirty?' *':''}</button><button type="button" onClick={()=>void action('validate')}>Comprobar datos</button><button type="button" className="wf-primary" disabled={warnings.length>0} onClick={()=>void action('generate')}>Generar renders →</button></div></div>
        </fieldset>
      </details>
    </div> : null}
    {issues.length?<div className="wf-message wf-error" role="alert"><strong>Hay datos que revisar:</strong><ul>{issues.slice(0, 20).map((issue,i)=><li key={`${issue.path}-${i}`}><strong>{issue.path}</strong>: {issue.message}</li>)}</ul></div>:null}
  </section>;
}
