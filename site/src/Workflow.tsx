import { useCallback, useEffect, useRef, useState } from 'react';
import type { ChangeEvent, MouseEvent } from 'react';
import './Workflow.css';

type Point = [number, number];
type Kind = 'wall' | 'slab' | 'room' | 'door' | 'window' | 'roof';
type Entity = { id: string; kind: Kind; polygon: Point[]; height?: number | null; thickness?: number | null; elevation?: number | null; sill?: number | null; wall_id?: string; name?: string; confirmed: boolean };
type Draft = { conceptual?: boolean; assumptions?: string[]; page: number; title: string; calibration: { points: Point[]; metres: number | null; confirmed: boolean }; floor: { name: string; elevation: number | null; confirmed: boolean }; entities: Entity[]; complete: boolean };
type Issue = { path: string; message: string };
type Candidate = { id: string; polygon: Point[]; label: string };
type Page = { page: number; width: number; height: number; image_url: string; candidates: Candidate[] };
type Project = { ai_interpretation?: Draft; id: string; filename: string; status: 'extracting' | 'review' | 'queued' | 'running' | 'succeeded' | 'failed'; stage: string; error?: string; pages?: Page[]; draft?: Draft; revision: number; issues?: Issue[]; manifest_url?: string };
type ProjectSummary = Pick<Project, 'id' | 'filename' | 'status' | 'stage'>;
const labels: Record<Kind, string> = { wall: 'Muro', slab: 'Suelo / losa', room: 'Habitación', door: 'Puerta', window: 'Ventana', roof: 'Cubierta' };
const kindColors: Record<Kind, string> = { wall: '#61704e', slab: '#b28a4d', room: '#8c72ae', door: '#bb6848', window: '#3b8598', roof: '#817768' };
const busyStates = new Set(['extracting', 'queued', 'running']);
const stages: Record<string, string> = { interpreting:'Interpretando con OpenAI', extracting:'Extrayendo el plano', validating_geometry:'Validando geometría', modeling:'Modelando y preparando vistas', preview_qa:'Comprobando la escena', rendering:'Renderizando imágenes finales', final_qa:'Comprobando las imágenes', exporting:'Optimizando y validando el 3D', completed:'Entrega validada', queued:'Esperando turno', review:'Completa los datos pendientes', generation_failed:'Error de generación', extraction_failed:'Error al leer el PDF', interrupted:'Proceso interrumpido' };
const phases: Record<string, string> = { extracting: 'Leyendo el PDF', review: 'Revisión pendiente', queued: 'En cola', running: 'Generando', succeeded: 'Resultados listos', failed: 'Necesita atención' };

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

export default function Workflow({ onResult }: { onResult: (url: string) => void }) {
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [project, setProject] = useState<Project | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [dirty, setDirty] = useState(false);
  const [working, setWorking] = useState(false);
  const [offline, setOffline] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [issues, setIssues] = useState<Issue[]>([]);
  const [selected, setSelected] = useState('');
  const [kind, setKind] = useState<Kind>('wall');
  const [mode, setMode] = useState<'select' | 'scale' | 'draw'>('select');
  const [points, setPoints] = useState<Point[]>([]);
  const [candidates, setCandidates] = useState(false);
  const [zoom, setZoom] = useState(1);
  const [showOriginalAI, setShowOriginalAI] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const shownResult = useRef('');
  const resultCallback = useRef(onResult);
  useEffect(() => { resultCallback.current = onResult; }, [onResult]);
  const remember = useCallback((p: Project, replaceDraft = true) => {
    setProject(p); setIssues(p.issues ?? []);
    if (replaceDraft) { setDraft(p.draft ?? null); setDirty(false); }
    try { localStorage.setItem('aav-active-project', p.id); } catch { /* Storage can be unavailable in private mode. */ }
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
    let id: string | null = null;
    try { id = localStorage.getItem('aav-active-project'); } catch { /* Optional persistence. */ }
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
  const upload = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]; if (!file) return;
    if (!file.name.toLowerCase().endsWith('.pdf') || file.size > 50 * 1024 * 1024) { setError('Selecciona un PDF de hasta 50 MB.'); event.target.value=''; return; }
    if (dirty && !window.confirm('Hay cambios sin guardar. ¿Quieres abrir otro PDF y descartarlos?')) { event.target.value=''; return; }
    setWorking(true); setError(''); setNotice(''); setIssues([]);
    try { const body = new FormData(); body.append('file',file); const p = await request<Project>('/api/projects',{method:'POST',body}); remember(p); setOffline(false); setSelected(''); setPoints([]); }
    catch (reason) { showError(reason); } finally { setWorking(false); event.target.value=''; }
  };
  const openProject = async (id: string) => {
    if (!id || busy || dirty && !window.confirm('Hay cambios sin guardar. ¿Quieres descartarlos y abrir otro proyecto?')) return;
    setWorking(true); setError('');
    try { remember(await request<Project>(`/api/projects/${id}`)); setSelected(''); setPoints([]); setNotice(''); }
    catch (reason) { showError(reason); } finally { setWorking(false); }
  };
  const save = async (): Promise<Project | null> => {
    if (!project || !draft) return null;
    const saved = await request<Project>(`/api/projects/${project.id}/draft`,{method:'PUT',body:JSON.stringify({draft,revision:project.revision})});
    remember(saved); return saved;
  };
  const action = async (operation: 'save'|'validate'|'generate'|'interpret') => {
    if (!project || !draft || busy) return;
    setWorking(true); setError(''); setNotice(''); setIssues([]);
    try {
      const saved = dirty ? await save() : project;
      if (!saved) return;
      if (operation === 'save') { setNotice('Revisión guardada en este equipo.'); return; }
      const result = await request<Project>(`/api/projects/${saved.id}/${operation}`,{method:'POST',body:JSON.stringify({revision:saved.revision})});
      remember(result);
      if (operation === 'validate' && !result.issues?.length) setNotice('Los datos revisados son coherentes. Ya puedes generar.');
    } catch (reason) { showError(reason); } finally { setWorking(false); }
  };
  const clickPlan = (event: MouseEvent<SVGSVGElement>) => {
    if (!page || busy || mode === 'select') return;
    const rect = event.currentTarget.getBoundingClientRect();
    const point: Point = [Math.max(0,Math.min(page.width,Math.round((event.clientX-rect.left)/rect.width*page.width*1000)/1000)),Math.max(0,Math.min(page.height,Math.round((event.clientY-rect.top)/rect.height*page.height*1000)/1000))];
    if (mode === 'scale') mutate(d => ({...d, calibration:{...d.calibration,points:d.calibration.points.length >= 2 ? [point] : [...d.calibration.points,point],confirmed:false},entities:d.entities.map(e=>({...e,confirmed:false}))}));
    else setPoints(p => [...p,point]);
  };
  const switchPage = (value: number) => {
    if (!draft || value === draft.page) return;
    if (!window.confirm('Cambiar de página reinicia la escala y los elementos del borrador. Esta versión trabaja una página y una planta por proyecto. ¿Continuar?')) return;
    mutate(d => ({...d,page:value,calibration:{points:[],metres:null,confirmed:false},entities:[]})); setSelected(''); setPoints([]); setMode('select');
  };

  return <section className="workflow" id="new-project" aria-labelledby="workflow-title">
    <div className="wf-heading"><div><span className="eyebrow">TU PLANO / TU PROYECTO</span><h2 id="workflow-title">Del PDF a un modelo revisado.</h2><p>Sube un plano para interpretarlo con OpenAI, compara la propuesta con el original y genera el 3D y los renders.</p></div><div className="wf-upload"><input ref={fileInput} aria-label="Subir plano PDF" type="file" accept="application/pdf,.pdf" onChange={upload} disabled={busy} /><small>PDF · OpenAI interpreta el plano · Uso de tokens</small></div></div>
    <ol className="wf-steps" aria-label="Pasos del proyecto"><li className={project?'done':'active'}>01 <span>Subir plano</span></li><li className={draft&&!busy?'active':''}>02 <span>Revisar datos</span></li><li className={project?.status==='running'||project?.status==='queued'?'active':''}>03 <span>Generar</span></li><li className={project?.status==='succeeded'?'done':''}>04 <span>Explorar</span></li></ol>
    {offline ? <div className="wf-message" role="status">La carga de PDFs necesita el servidor local. Inícialo con <code>uv run python -m pipelines.web.server</code> y abre la dirección que indique. La demo sigue disponible.<button onClick={()=>void refreshProjects()}>Comprobar conexión</button></div> : null}
    {projects.length ? <label className="wf-project-picker">Proyecto local<select aria-label="Abrir proyecto local" value={project?.id ?? ''} disabled={busy} onChange={e=>void openProject(e.target.value)}><option value="">Selecciona un proyecto</option>{projects.map(p=><option key={p.id} value={p.id}>{p.filename} · {phases[p.status]}</option>)}</select></label> : null}
    {error ? <div className="wf-message wf-error" role="alert"><strong>No se ha completado la operación.</strong><p>{error}</p>{error.includes('409')||error.toLowerCase().includes('otra pestaña') ? <button onClick={()=>project&&void openProject(project.id)}>Recargar revisión</button> : null}</div> : null}
    {notice ? <p className="wf-message" role="status">{notice}</p> : null}
    {project ? <div className="wf-job" role="status"><span className={`status-dot ${busy?'pulse':''}`}/><strong>{phases[project.status]}</strong><span>{stages[project.stage] ?? project.stage}</span>{project.status==='succeeded'&&project.manifest_url?<button onClick={()=>{onResult(project.manifest_url!);document.getElementById("explore")?.scrollIntoView({behavior:"smooth"});}}>Ver renders y 3D ↓</button>:null}</div> : null}
    {project?.error ? <div className="wf-message wf-error" role="alert"><strong>La generación se ha detenido.</strong><p>{project.error}</p><p>Corrige la revisión y vuelve a generar. El PDF original se conserva.</p></div> : null}
    {draft && page ? <fieldset className="wf-editor" disabled={busy}><legend className="sr-only">Revisión del plano</legend>
      <div className="wf-message"><strong>Interpretación automática con OpenAI</strong><p>Envía este PDF a OpenAI para proponer contornos y medidas. Consume tokens de tu cuenta API. La propuesta conceptual puede contener errores; podrás editarla antes de generar.</p><button type="button" onClick={()=>void action('interpret')}>Interpretar PDF con OpenAI</button></div>
      {draft.conceptual ? <div className="wf-message"><strong>Propuesta conceptual · No es una reconstrucción certificada</strong><p>Las medidas y contornos propuestos siguen siendo inferidos aunque aceptes utilizarlos. Edita las alturas en cada elemento; esta lista documenta los supuestos y no modifica las medidas.</p><label className="wf-field">Supuestos y limitaciones<textarea rows={6} value={(draft.assumptions??[]).join('\n')} onChange={e=>mutate(d=>({...d,assumptions:e.target.value.split('\n')}))}/></label><button type="button" onClick={()=>{setDraft(d=>d?{...d,calibration:{...d.calibration,confirmed:true},floor:{...d.floor,confirmed:true},entities:d.entities.map(e=>({...e,confirmed:true})),complete:true}:d);setDirty(true);}}>Aceptar propuesta y supuestos para generar</button></div> : null}
      <div className="wf-review-meta"><label className="wf-field"><span>Nombre del proyecto</span><input value={draft.title} onChange={e=>mutate(d=>({...d,title:e.target.value}))}/></label><label className="wf-field"><span>Página del PDF</span><select value={draft.page} onChange={e=>switchPage(Number(e.target.value))}>{project?.pages?.map(p=><option key={p.page} value={p.page}>Página {p.page}</option>)}</select></label><p>Una página y una planta por proyecto. Los trazos detectados son candidatos, no elementos confirmados.</p></div>
      <div className="wf-review-layout"><div className="wf-plan-column">
        <div className="wf-drawing-tools" role="group" aria-label="Herramientas del plano"><button type="button" aria-pressed={mode==='select'} onClick={()=>{setMode('select');setPoints([]);}}>Seleccionar</button><button type="button" aria-pressed={mode==='scale'} onClick={()=>{setMode('scale');setPoints([]);}}>Marcar cota</button><select aria-label="Tipo de elemento a dibujar" value={kind} onChange={e=>setKind(e.target.value as Kind)}>{Object.entries(labels).map(([key,label])=><option key={key} value={key}>{label}</option>)}</select><button type="button" aria-pressed={mode==='draw'} onClick={()=>{setMode('draw');setPoints([]);}}>Dibujar contorno</button></div>
        <p className="wf-plan-help" role="status">{mode==='scale'?'Pulsa los dos extremos de una cota conocida. Un tercer clic inicia una nueva cota.':mode==='draw'?`Marca los vértices del contorno de ${labels[kind].toLowerCase()} y pulsa Cerrar contorno.`:'Selecciona un elemento para revisar sus propiedades. También puedes elegir un rectángulo detectado.'}</p>
        <div className="wf-plan-options"><label><input type="checkbox" checked={candidates} onChange={e=>setCandidates(e.target.checked)}/> Mostrar rectángulos detectados</label><label>Ampliación <select aria-label="Ampliación del plano" value={zoom} onChange={e=>setZoom(Number(e.target.value))}><option value={1}>100%</option><option value={1.5}>150%</option><option value={2}>200%</option><option value={3}>300%</option></select></label></div>
        <div className="wf-plan-comparison"><section><h3>PDF original</h3><div className="wf-original-frame"><img src={page.image_url} alt={`PDF original, página ${page.page}`} /></div></section><section><h3>{showOriginalAI ? "Respuesta original de OpenAI · sin corregir" : draft.conceptual ? "Propuesta conceptual · editable" : "Geometría en revisión"}</h3>{project?.ai_interpretation ? <button type="button" onClick={()=>setShowOriginalAI(v=>!v)}>{showOriginalAI ? "Mostrar revisión actual" : "Comparar respuesta original de OpenAI"}</button> : null}<div className={`wf-plan-frame ${mode!=='select'?'crosshair':''}`}><svg role="img" aria-label={`Plano original, página ${page.page}. Usa las herramientas para marcar referencias y contornos.`} viewBox={`0 0 ${page.width} ${page.height}`} style={{width:`${zoom*100}%`,aspectRatio:`${page.width} / ${page.height}`}} onClick={clickPlan}><image href={page.image_url} width={page.width} height={page.height} opacity={draft.conceptual ? 0.15 : 1}/>{candidates ? page.candidates.map(c=><polygon key={c.id} points={c.polygon.map(p=>p.join(',')).join(' ')} className="wf-candidate" onClick={e=>{if(mode==='select'&&!busy){e.stopPropagation();addEntity(c.polygon);}}}><title>{c.label} · Añadir como {labels[kind]}</title></polygon>):null}{(showOriginalAI ? project?.ai_interpretation?.entities ?? [] : draft.entities).map(e=><polygon key={e.id} points={e.polygon.map(p=>p.join(',')).join(' ')} fill={kindColors[e.kind]} stroke={selected===e.id?'#161f13':kindColors[e.kind]} className={`wf-polygon ${e.confirmed?'confirmed':''} ${selected===e.id?'selected':''}`} onClick={event=>{if(mode==='select'&&!showOriginalAI){event.stopPropagation();setSelected(e.id);}}}><title>{e.id} · {labels[e.kind]} · {e.confirmed?'Confirmado':'Pendiente'}</title></polygon>)}{draft.calibration.points.length===2?<line x1={draft.calibration.points[0][0]} y1={draft.calibration.points[0][1]} x2={draft.calibration.points[1][0]} y2={draft.calibration.points[1][1]} className="wf-scale-line"/>:null}{draft.calibration.points.map((p,i)=><circle key={i} cx={p[0]} cy={p[1]} r={3} className="wf-scale-point"/>)}{points.length?<polyline points={points.map(p=>p.join(',')).join(' ')} className="wf-in-progress"/>:null}{points.map((p,i)=><circle key={i} cx={p[0]} cy={p[1]} r={2.5} fill="#c25331"/>)}</svg></div></section></div>
        {mode==='draw'?<div className="wf-draw-finish"><span>{points.length} vértices</span><button type="button" disabled={points.length<3} onClick={()=>addEntity(points)}>Cerrar contorno</button><button type="button" disabled={!points.length} onClick={()=>setPoints(p=>p.slice(0,-1))}>Deshacer punto</button></div>:null}
        <details className="wf-coordinate-entry"><summary>Introducir puntos con el teclado</summary><p>Coordenadas del PDF: X desde la izquierda, Y desde arriba. Puedes consultarlas en el contorno y usar estas entradas para ajustar los vértices.</p>{mode==='scale'?<>{[0,1].map(i=><div className="wf-coordinate-row" key={i}><span>Extremo {i+1}</span>{[0,1].map(axis=><NumberField key={axis} label={axis===0?'X (pt)':'Y (pt)'} value={draft.calibration.points[i]?.[axis]} min={0} onChange={v=>{if(v===null)return;mutate(d=>{const p=[...d.calibration.points] as Point[];while(p.length<=i)p.push([0,0]);p[i]=[...p[i]];p[i][axis]=v;return {...d,calibration:{...d.calibration,points:p,confirmed:false},entities:d.entities.map(e=>({...e,confirmed:false}))};});}}/>)}</div>)}</>:<div className="wf-coordinate-row"><NumberField label="Nuevo punto X (pt)" value={points.at(-1)?.[0]} min={0} onChange={v=>{if(v===null)return;setPoints(p=>p.length?[...p.slice(0,-1),[v,p[p.length-1][1]]]:[[v,0]]);}}/><NumberField label="Nuevo punto Y (pt)" value={points.at(-1)?.[1]} min={0} onChange={v=>{if(v===null)return;setPoints(p=>p.length?[...p.slice(0,-1),[p[p.length-1][0],v]]:[[0,v]]);}}/><button type="button" onClick={()=>{setMode('draw');setPoints(p=>[...p,[0,0]]);}}>Añadir vértice</button></div>}</details>
      </div><aside className="wf-inspector">
        <section className="wf-inspector-section"><h3>1. Escala y planta</h3><NumberField label="Distancia real de la cota (m)" value={draft.calibration.metres} min={0} onChange={metres=>mutate(d=>({...d,calibration:{...d.calibration,metres,confirmed:false},entities:d.entities.map(e=>({...e,confirmed:false}))}))}/><label className="wf-confirm"><input type="checkbox" checked={draft.calibration.confirmed} disabled={draft.calibration.points.length!==2||!draft.calibration.metres} onChange={e=>mutate(d=>({...d,calibration:{...d.calibration,confirmed:e.target.checked}}))}/> He comprobado los extremos y la distancia</label><label className="wf-field"><span>Nombre de la planta</span><input value={draft.floor.name} onChange={e=>mutate(d=>({...d,floor:{...d.floor,name:e.target.value,confirmed:false}}))}/></label><NumberField label="Elevación de planta (m)" value={draft.floor.elevation} onChange={elevation=>mutate(d=>({...d,floor:{...d.floor,elevation,confirmed:false}}))}/><label className="wf-confirm"><input type="checkbox" checked={draft.floor.confirmed} disabled={draft.floor.elevation===null} onChange={e=>mutate(d=>({...d,floor:{...d.floor,confirmed:e.target.checked}}))}/> Elevación verificada</label></section>
        <section className="wf-inspector-section"><h3>2. Elementos <span>{draft.entities.length}</span></h3><label className="wf-field"><span>Seleccionar elemento</span><select value={selected} onChange={e=>setSelected(e.target.value)}><option value="">Elige un elemento del plano</option>{draft.entities.map(e=><option key={e.id} value={e.id}>{e.confirmed?'✓':'○'} {e.id} · {labels[e.kind]}</option>)}</select></label>{entity?<div className="wf-entity-fields"><div className="wf-entity-kind"><span style={{background:kindColors[entity.kind]}}/>{labels[entity.kind]}<small>{entity.id}</small></div>{entity.kind==='room'?<label className="wf-field"><span>Nombre de la habitación</span><input value={entity.name??''} onChange={e=>updateEntity({name:e.target.value})}/></label>:null}{['wall','door','window'].includes(entity.kind)?<NumberField label="Altura (m)" value={entity.height} min={0} onChange={height=>updateEntity({height})}/>:null}{['wall','slab','roof'].includes(entity.kind)?<NumberField label="Espesor (m)" value={entity.thickness} min={0} onChange={thickness=>updateEntity({thickness})}/>:null}{['slab','roof'].includes(entity.kind)?<NumberField label="Cota inferior (m)" value={entity.elevation} onChange={elevation=>updateEntity({elevation})}/>:null}{entity.kind==='door'||entity.kind==='window'?<><label className="wf-field"><span>Muro que contiene el hueco</span><select value={entity.wall_id??''} onChange={e=>updateEntity({wall_id:e.target.value})}><option value="">Selecciona el muro</option>{draft.entities.filter(e=>e.kind==='wall').map(e=><option key={e.id} value={e.id}>{e.id}</option>)}</select></label><NumberField label="Altura del borde inferior sobre planta (m)" value={entity.sill} min={0} onChange={sill=>updateEntity({sill})}/></>:null}<details><summary>Vértices del contorno (PDF)</summary>{entity.polygon.map((p,i)=><div className="wf-coordinate-row" key={i}>{[0,1].map(axis=><NumberField key={axis} label={`${i+1} · ${axis===0?'X':'Y'} (pt)`} value={p[axis]} min={0} onChange={v=>{if(v===null)return;updateEntity({polygon:entity.polygon.map((pt,j)=>j===i?axis===0?[v,pt[1]]:[pt[0],v]:pt)});}}/>)}</div>)}</details><label className="wf-confirm"><input type="checkbox" checked={entity.confirmed} onChange={e=>updateEntity({confirmed:e.target.checked})}/> Contorno y medidas verificados en el plano</label><button type="button" className="wf-delete" onClick={()=>{mutate(d=>({...d,entities:d.entities.filter(e=>e.id!==selected).map(e=>e.wall_id===selected?{...e,wall_id:'',confirmed:false}:e)}));setSelected('');}}>Eliminar este elemento</button></div>:<p className="wf-muted">Dibuja un contorno, elige un rectángulo detectado o selecciona un elemento existente. No se rellenan medidas desconocidas.</p>}</section>
      </aside></div>
      <div className="wf-final-review"><div><h3>3. Revisar antes de generar</h3><p>Confirma cada elemento y sus medidas. Si una cubierta no aparece en esta planta, no la añadas. Las puertas y ventanas necesitan su muro, altura y cota inferior.</p><label className="wf-confirm"><input type="checkbox" checked={draft.complete} onChange={e=>{setDraft(d=>d?{...d,complete:e.target.checked}:d);setDirty(true);setNotice('');}}/> He revisado todos los elementos de esta planta y completado las medidas necesarias. Autorizo generar este modelo.</label>{warnings.length?<ul className="wf-pending">{warnings.map(w=><li key={w}>{w}</li>)}</ul>:<p className="wf-ready">La revisión está completa. Se comprobará la coherencia geométrica antes de comenzar.</p>}</div><div className="wf-review-actions"><button type="button" onClick={()=>void action('save')} disabled={!dirty}>Guardar revisión{dirty?' *':''}</button><button type="button" onClick={()=>void action('validate')}>Comprobar datos</button><button type="button" className="wf-primary" disabled={warnings.length>0} onClick={()=>void action('generate')}>{project?.status==='succeeded'?'Regenerar renders y 3D':'Generar renders y 3D'} →</button></div></div>
    </fieldset>:null}
    {issues.length?<div className="wf-message wf-error" role="alert"><strong>Hay datos que revisar antes de continuar:</strong><ul>{issues.map((issue,i)=><li key={`${issue.path}-${i}`}><strong>{issue.path}</strong>: {issue.message}</li>)}</ul></div>:null}
  </section>;
}
