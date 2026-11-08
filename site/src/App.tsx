import { Component, lazy, Suspense, useEffect, useState } from 'react';
import type { ErrorInfo, ReactNode } from 'react';
import { assetUrl, parseManifest, projectBase } from './types';
import type { Manifest } from './types';
import Workflow from './Workflow';
const Viewer = lazy(() => import('./Viewer'));

class ViewerBoundary extends Component<{ children: ReactNode; onRetry: () => void }, { error: string | null }> {
  state: { error: string | null } = { error: null };
  static getDerivedStateFromError(error: Error) { return { error: error.message }; }
  componentDidCatch(error: Error, info: ErrorInfo) { console.error('Viewer failed', error, info.componentStack); }
  render() {
    if (this.state.error) return <div className="viewer-error" role="alert"><span className="eyebrow">VISOR NO DISPONIBLE</span><h3>No se ha podido abrir el modelo.</h3><p>Comprueba que el archivo GLB está disponible y que tu navegador admite WebGL.</p><details><summary>Detalle del error</summary><p>{this.state.error}</p></details><button onClick={this.props.onRetry}>Reintentar</button></div>;
    return this.props.children;
  }
}

function Gallery({ manifest }: { manifest: Manifest }) {
  const [selected, setSelected] = useState(0);
  const current = manifest.renders[selected];
  if (!current) return <p className="empty">No hay renders disponibles en este proyecto.</p>;
  return <section className="gallery-section" id="renders" aria-labelledby="gallery-title">
    <div className="section-heading"><div><span className="eyebrow">02 / ATMÓSFERAS</span><h2 id="gallery-title">Una misma arquitectura.<br />Distintas perspectivas.</h2></div><p>Imágenes procedentes de la escena Blender.<br />Geometría compartida con el modelo interactivo.</p></div>
    <figure className="render-main"><img key={current.url} src={assetUrl(current.url)} alt={`${manifest.title} — ${current.label}`} loading="lazy" /><figcaption><span>{String(selected + 1).padStart(2, '0')} / {String(manifest.renders.length).padStart(2, '0')}</span><span>{current.label}</span><a href={assetUrl(current.url)} download>Descargar imagen ↗</a></figcaption></figure>
    <div className="render-thumbnails" aria-label="Seleccionar render">{manifest.renders.map((render, index) => <button key={render.id} className={index === selected ? 'thumbnail selected' : 'thumbnail'} onClick={() => setSelected(index)} aria-pressed={index === selected}><img src={assetUrl(render.url)} alt="" loading="lazy"/><span><small>{String(index + 1).padStart(2, '0')}</small>{render.label}<span aria-hidden="true">↗</span></span></button>)}</div>
  </section>;
}

export default function App() {
  const [manifestUrl, setManifestUrl] = useState(`${projectBase}manifest.json`);
  const [manifest, setManifest] = useState<Manifest | null>(null);
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);
  const [viewerAttempt, setViewerAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    fetch(manifestUrl, { signal: controller.signal, cache: 'no-cache' })
      .then(response => { if (!response.ok) throw new Error(`Proyecto no disponible (HTTP ${response.status}).`); return response.json(); })
      .then(value => { setManifest(parseManifest(value, manifestUrl)); setError(''); })
      .catch((reason: Error) => { if (reason.name !== 'AbortError') setError(reason.message); });
    return () => controller.abort();
  }, [attempt, manifestUrl]);
  return <>
    <a className="skip-link" href="#main">Ir al contenido</a>
    <header className="site-header"><a href="#" className="wordmark" aria-label="MG Estudio, inicio">MG<span className="wordmark-dot">.</span><span className="wordmark-sub">ARQUITECTURA<br />EN PERSPECTIVA</span></a><nav aria-label="Navegación principal"><a href="#new-project">Subir PDF</a><a href="#explore">Explorar modelo</a><a href="#renders">Galería</a><a href="#source">Trazabilidad <span aria-hidden="true">↗</span></a></nav><span className="edition">ESTUDIO DIGITAL / 01</span></header>
    <main id="main">
      <section className="intro"><div className="intro-copy"><span className="eyebrow"><span className="status-dot" /> ARCHITECTURAL AI VISUALIZER</span><h1>Del plano,<br /><em>al espacio.</em></h1><p>Explora la arquitectura desde dentro.<br />Un modelo preciso. Una nueva perspectiva.</p></div><div className="project-summary"><span className="eyebrow">PROYECTO EN ESTUDIO</span><h2>{manifest?.title ?? 'Cargando proyecto'}</h2><p>{manifest?.synthetic ? 'Demostración sintética · No es un proyecto construido' : 'Visualización del documento original'}</p><div className="summary-meta"><span>{manifest?.project_id ?? '—'}</span><span>{manifest?.units === 'm' ? 'ESCALA MÉTRICA' : manifest?.units ?? '—'}</span></div><a href="#explore" className="text-link">Entrar al modelo <span aria-hidden="true">↓</span></a></div></section>
      <Workflow onResult={url=>{setManifestUrl(url);setAttempt(n=>n+1);setError('');}} />
      {error ? <section className="load-error" role="alert"><h2>El proyecto aún no está disponible.</h2><p>{error}</p><p>Genera y prepara los recursos del proyecto para abrir el visor.</p><button onClick={() => setAttempt(n => n + 1)}>Volver a cargar</button></section> : !manifest ? <div className="loading-project" role="status">Preparando el estudio…</div> : <>
        <section id="explore" aria-labelledby="viewer-title" className="explore-section"><div className="section-topline"><span className="eyebrow" id="viewer-title">01 / EXPLORACIÓN ESPACIAL</span><span className={`qa-status ${manifest.quality.passed ? 'passed' : 'pending'}`}><span className="status-dot" />{manifest.quality.passed ? 'Comprobación geométrica superada' : 'Pendiente de validación geométrica'}</span></div>
          <ViewerBoundary key={`${manifestUrl}-${viewerAttempt}`} onRetry={() => setViewerAttempt(n => n + 1)}><Suspense fallback={<div className="viewer-placeholder" role="status">Preparando visor 3D…</div>}><Viewer manifest={manifest} attempt={viewerAttempt} /></Suspense></ViewerBoundary>
          <div className="viewer-footer"><span>Arrastra para orbitar · Rueda para acercar · Botón derecho para desplazar</span><a href={assetUrl(manifest.model_url)} download>Descargar modelo GLB <span aria-hidden="true">↗</span></a></div>
        </section>
        <Gallery key={manifestUrl} manifest={manifest}/>
        <section className="source-section" id="source"><div><span className="eyebrow">03 / DOCUMENTO Y MODELO</span><h2>La precisión<br />es el punto de partida.</h2></div><div className="source-description"><p>El plano original define la geometría. Los renders y el visor proceden de la misma escena, con identificadores que permiten seguir cada elemento hasta su fuente.</p><dl><div><dt>Estado</dt><dd>{manifest.quality.passed ? 'Validación geométrica superada' : 'Revisión requerida'}</dd></div><div><dt>Origen</dt><dd>{manifest.synthetic ? 'Datos sintéticos de prueba' : 'Documento de proyecto'}</dd></div><div><dt>Plantas</dt><dd>{manifest.floors.length}</dd></div><div><dt>Huella del documento</dt><dd className="hash" title={manifest.source_sha256}>{manifest.source_sha256 ? `${manifest.source_sha256.slice(0, 16)}…` : 'No disponible'}</dd></div></dl><p className="source-note">La demo valida un caso controlado. La interpretación de otros planos requiere revisar las dimensiones y los elementos ambiguos.</p></div></section>
      </>}
    </main><footer className="site-footer"><span className="footer-brand">MG<span>.</span></span><p>Arquitectura con origen. Espacios con perspectiva.</p><a href="#">Volver al inicio ↑</a></footer>
  </>;
}
