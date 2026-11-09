import { useCallback, useEffect, useRef, useState } from 'react';
import type { ChangeEvent, FormEvent, MouseEvent } from 'react';
import './Workflow.css';

type Point = [number, number];
type Kind = 'wall' | 'slab' | 'room' | 'door' | 'window' | 'roof' | 'furniture';
type Finish = { name: string; color: [number, number, number]; roughness: number };
type Entity = { id: string; kind: Kind; polygon: Point[]; height?: number | null; thickness?: number | null; elevation?: number | null; sill?: number | null; wall_id?: string; name?: string; style?: string | null; finish?: string | null; confirmed: boolean };
type Draft = { conceptual?: boolean; assumptions?: string[]; finishes?: Record<string, Finish>; page: number; title: string; calibration: { points: Point[]; metres: number | null; confirmed: boolean }; floor: { name: string; elevation: number | null; confirmed: boolean }; entities: Entity[]; complete: boolean };
type Issue = { path: string; message: string };
type Candidate = { id: string; polygon: Point[]; label: string };
type Page = { page: number; width: number; height: number; image_url: string; candidates: Candidate[] };
type Project = { ai_interpretation?: Draft; description?: string; id: string; filename: string; status: 'extracting' | 'review' | 'queued' | 'running' | 'succeeded' | 'failed'; stage: string; error?: string; pages?: Page[]; draft?: Draft; revision: number; issues?: Issue[]; manifest_url?: string; result_revision?: number; finishes_error?: string | null };
type ProjectSummary = Pick<Project, 'id' | 'filename' | 'status' | 'stage'>;

const labels: Record<Kind, string> = { wall: 'Muro', slab: 'Suelo / losa', room: 'Estancia', door: 'Puerta', window: 'Ventana', roof: 'Cubierta', furniture: 'Mueble' };
const plural: Record<Kind, string> = { wall: 'muros', slab: 'losas', room: 'estancias', door: 'puertas', window: 'ventanas', roof: 'cubiertas', furniture: 'muebles' };
const kindColors: Record<Kind, string> = { wall: '#2f3a2a', slab: '#c9b48a', room: '#8c72ae', door: '#c0532f', window: '#2f86b8', roof: '#817768', furniture: '#a8754f' };
const finishLabels: Record<string, string> = { walls: 'Paredes', floor: 'Suelo', tile: 'Baños', doors: 'Puertas y armarios', joinery: 'Carpintería exterior', furniture_wood: 'Madera de muebles', upholstery: 'Tapicería', stone: 'Piedra / encimeras', ceramic: 'Sanitarios', metal: 'Metal / grifería' };
const floorLabels: Record<string, string> = { wood: 'madera', tile: 'baldosa', stone: 'piedra' };
const busyStates = new Set(['extracting', 'queued', 'running']);
const stages: Record<string, string> = { extracting: 'Leyendo el PDF', interpreting: 'La IA está interpretando el plano', materials: 'Interpretando la descripción de materiales', validating_geometry: 'Validando geometría', modeling: 'Modelando en Blender', preview_qa: 'Comprobando la escena', rendering: 'Renderizando con Blender', final_qa: 'Comprobando las imágenes', exporting: 'Exportando el modelo 3D', completed: 'Renders listos', queued: 'En cola', review: 'Pendiente de revisión', generation_failed: 'Error de generación', extraction_failed: 'Error al leer el PDF', interrupted: 'Proceso interrumpido' };
const phases: Record<string, string> = { extracting: 'Leyendo', review: 'En revisión', queued: 'En cola', running: 'Procesando', succeeded: 'Renders listos', failed: 'Necesita atención' };
const renderStages = ['queued', 'validating_geometry', 'modeling', 'preview_qa', 'rendering', 'final_qa', 'exporting', 'completed'];
const MAX_DESCRIPTION = 1000;

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

function PlanOverlay({ page, entities, faint, onSelect, selected }: { page: Page; entities: Entity[]; faint: boolean; onSelect?: (id: string) => void; selected?: string }) {
  const order: Kind[] = ['slab', 'room', 'wall', 'furniture', 'window', 'door', 'roof'];
  const sorted = [...entities].sort((a, b) => order.indexOf(a.kind) - order.indexOf(b.kind));
  return <svg role="img" aria-label="Interpretación de la IA sobre el plano" viewBox={`0 0 ${page.width} ${page.height}`} className="wf-overlay">
    <image href={page.image_url} width={page.width} height={page.height} opacity={faint ? 0.22 : 1} />
    {sorted.map(e => <polygon key={e.id} points={e.polygon.map(p => p.join(',')).join(' ')} fill={kindColors[e.kind]} stroke={kindColors[e.kind]} className={`wf-ai-shape wf-ai-${e.kind} ${selected === e.id ? 'selected' : ''}`} onClick={onSelect ? () => onSelect(e.id) : undefined}><title>{labels[e.kind]}{e.name ? ` · ${e.name.split(' / ').pop()}` : ''}{e.style ? ` · ${e.style}` : ''}</title></polygon>)}
    {/* Furniture footprints are ordered back-left, back-right, front-right, front-left: the arrow shows the front. */}
    {sorted.filter(e => e.kind === 'furniture' && e.polygon.length === 4).map(e => { const [, , fr, fl] = e.polygon; const cx = e.polygon.reduce((a, p) => a + p[0], 0) / 4, cy = e.polygon.reduce((a, p) => a + p[1], 0) / 4; const fx = (fr[0] + fl[0]) / 2, fy = (fr[1] + fl[1]) / 2; return <g key={`${e.id}-front`} className="wf-front"><line x1={cx} y1={cy} x2={fx} y2={fy} /><circle cx={fx} cy={fy} r={2.2} /></g>; })}
  </svg>;
}

export default function Workflow({ onResult }: { onResult: (url: string | null) => void }) {
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
  const [showAI, setShowAI] = useState(true);
  const [selected, setSelected] = useState('');
  const [kind, setKind] = useState<Kind>('wall');
  const [mode, setMode] = useState<'select' | 'scale' | 'draw'>('select');
  const [points, setPoints] = useState<Point[]>([]);
  const [candidates, setCandidates] = useState(false);
  const [zoom, setZoom] = useState(1);
  const shownResult = useRef('');
  const resultCallback = useRef(onResult);
  useEffect(() => { resultCallback.current = onResult; }, [onResult]);

  const remember = useCallback((p: Project, replaceDraft = true) => {
    setProject(p); setIssues(p.issues ?? []);
    if (replaceDraft) { setDraft(p.draft ?? null); setDirty(false); setMaterialsText(p.description ?? ''); }
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
  useEffect(() => {
    if (!project || !busyStates.has(project.status)) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const next = await request<Project>(`/api/projects/${project.id}`, {signal:controller.signal});
        if (!controller.signal.aborted) { remember(next); setError(''); if (busyStates.has(next.status)) timer = setTimeout(poll, 1200); }
      } catch (reason) {
        if (!controller.signal.aborted) { setError(reason instanceof Error ? reason.message : 'No se pudo consultar el progreso.'); timer = setTimeout(poll, 2500); }
      }
    };
    timer = setTimeout(poll, 1000);
    return () => { controller.abort(); clearTimeout(timer); };
  }, [project?.id, project?.status, remember]);

  const busy = working || !!project && busyStates.has(project.status);
  const page = project?.pages?.find(p => p.page === draft?.page);
  const entity = draft?.entities.find(e => e.id === selected);
  const warnings = draft ? localIssues(draft) : [];
  const interpreted = !!draft?.conceptual;
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
    if (chosen && (!chosen.name.toLowerCase().endsWith('.pdf') || chosen.size > 50 * 1024 * 1024)) { setError('Selecciona un PDF de hasta 50 MB.'); event.target.value=''; setFile(null); return; }
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
  const newProject = () => {
    if (busy || dirty && !window.confirm('Hay cambios sin guardar. ¿Descartarlos?')) return;
    setProject(null); setDraft(null); setDirty(false); setError(''); setNotice(''); setIssues([]); shownResult.current = ''; onResult(null);
    try { localStorage.removeItem('gc-active-project'); } catch { /* Optional persistence. */ }
  };
  const openProject = async (id: string) => {
    if (!id || busy || dirty && !window.confirm('Hay cambios sin guardar. ¿Quieres descartarlos y abrir otro proyecto?')) return;
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
      {projects.length ? <label className="wf-project-picker">Proyectos<select aria-label="Abrir proyecto" value={project?.id ?? ''} disabled={busy} onChange={e=>void openProject(e.target.value)}><option value="">Selecciona un proyecto</option>{projects.map(p=><option key={p.id} value={p.id}>{p.filename} · {phases[p.status]}</option>)}</select></label> : null}
    </div>
    <ol className="wf-steps" aria-label="Pasos del proyecto">
      {['Subir plano', 'Revisar interpretación', 'Renders con Blender'].map((label, i) => <li key={label} className={step === i + 1 ? 'active' : step > i + 1 ? 'done' : ''} aria-current={step === i + 1 ? 'step' : undefined}>{String(i + 1).padStart(2, '0')} <span>{label}</span></li>)}
    </ol>
    {offline ? <div className="wf-message wf-error" role="status">No hay conexión con el servidor del estudio. Inícialo con <code>uv run python -m pipelines.web.server</code>.<button onClick={()=>void refreshProjects()}>Reintentar</button></div> : null}
    {error ? <div className="wf-message wf-error" role="alert"><strong>No se ha completado la operación.</strong><p>{error}</p>{error.toLowerCase().includes('otra pestaña') ? <button onClick={()=>project&&void openProject(project.id)}>Recargar</button> : null}</div> : null}
    {notice ? <p className="wf-message" role="status">{notice}</p> : null}

    {!project ? <form className="wf-upload-card" onSubmit={e=>void upload(e)}>
      <label className={`wf-drop ${file ? 'has-file' : ''}`}>
        <input type="file" accept="application/pdf,.pdf" onChange={chooseFile} disabled={busy} aria-label="Plano en PDF" />
        <span className="wf-drop-title">{file ? file.name : 'Selecciona el plano en PDF'}</span>
        <span className="wf-drop-hint">{file ? `${(file.size / 1024 / 1024).toFixed(1)} MB · listo para interpretar` : 'Una planta por PDF, con escala impresa (p. ej. 1:50). Máx. 50 MB.'}</span>
      </label>
      <label className="wf-field wf-description"><span>Materiales y acabados <em>(opcional)</em></span>
        <textarea rows={5} maxLength={MAX_DESCRIPTION} value={description} onChange={e=>setDescription(e.target.value)} placeholder="Ej.: suelo de roble natural, paredes blanco roto, muebles de nogal, sofá de lino gris y baños con cerámica blanca." />
        <small>{description.length}/{MAX_DESCRIPTION} · Se aplica a paredes, suelo, puertas, madera, tapicería y cerámica.</small>
      </label>
      <div className="wf-upload-actions"><button type="submit" className="wf-primary" disabled={!file || busy}>{working ? 'Subiendo…' : 'Interpretar plano →'}</button><small>El PDF se envía a la API de OpenAI para interpretarlo.</small></div>
    </form> : <>
      <div className="wf-job" role="status"><span className={`status-dot ${busy?'pulse':''}`}/><strong>{project.filename}</strong><span>{stages[project.stage] ?? project.stage}</span>
        {project.status==='succeeded'&&project.manifest_url?<button onClick={()=>document.getElementById('explore')?.scrollIntoView({behavior:'smooth'})}>Ver renders ↓</button>:null}
        <button onClick={newProject} disabled={busy}>Nuevo plano</button></div>
      {rendering ? <div className="wf-progress" aria-label="Progreso de Blender"><div style={{width:`${Math.max(6, renderStages.indexOf(project.stage) / (renderStages.length - 1) * 100)}%`}}/></div> : null}
      {project.error ? <div className="wf-message wf-error" role="alert"><strong>{project.stage === 'generation_failed' ? 'La generación se ha detenido.' : 'Atención'}</strong><p>{project.error}</p>{!busy && project.pages?.length ? <button type="button" onClick={()=>void action('interpret')}>Reintentar interpretación</button> : null}</div> : null}
      {busy && !draft ? <div className="wf-wait"><span className="status-dot pulse"/>{stages[project.stage] ?? 'Procesando'}… Puede tardar uno o dos minutos.</div> : null}
    </>}

    {project && draft && page ? <div className="wf-review">
      {interpreted ? <>
        <div className="wf-review-head"><div><span className="eyebrow">02 / REVISIÓN</span><h3>Comprueba la interpretación junto al plano original</h3><p>La IA ha seleccionado muros y huecos sobre los vectores del PDF y propone mobiliario. Si algo no encaja, vuelve a interpretar o usa la edición avanzada.</p></div>
          <div className="wf-review-cta"><button type="button" className="wf-primary" disabled={busy} onClick={()=>void action('approve')}>{project.status==='succeeded'&&project.result_revision===project.revision?'Regenerar renders':'Aprobar y generar renders'} →</button><small>Las medidas son inferidas a partir del PDF y su escala.</small></div></div>
        <div className="wf-compare">
          <figure><figcaption>Plano original</figcaption><div className="wf-compare-frame"><img src={page.image_url} alt={`Plano original, página ${page.page}`} /></div></figure>
          <figure><figcaption>Interpretación de la IA <label className="wf-toggle"><input type="checkbox" checked={showAI} onChange={e=>setShowAI(e.target.checked)}/> Superponer</label></figcaption><div className="wf-compare-frame"><PlanOverlay page={page} entities={showAI ? draft.entities : []} faint={showAI} /></div></figure>
        </div>
        <p className="wf-muted wf-legend-note">Las flechas de los muebles indican su frente (orientación).</p><ul className="wf-legend" aria-label="Elementos interpretados">{(['wall','door','window','room','furniture'] as Kind[]).map(k=><li key={k}><span style={{background:kindColors[k]}}/>{counts[k] ?? 0} {plural[k]}</li>)}</ul>
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
