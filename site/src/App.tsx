import { Component, lazy, Suspense, useEffect, useState } from 'react';
import type { ErrorInfo, ReactNode } from 'react';
import { assetUrl, parseManifest } from './types';
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
    <div className="section-heading"><div><span className="eyebrow">RESULTADO / RENDERS</span><h2 id="gallery-title">{manifest.title}</h2></div><p>Renders de Blender (Cycles).<br />Misma geometría que el modelo 3D interactivo.</p></div>
    <figure className="render-main"><img key={current.url} src={assetUrl(current.url)} alt={`${manifest.title} — ${current.label}`} loading="lazy" /><figcaption><span>{String(selected + 1).padStart(2, '0')} / {String(manifest.renders.length).padStart(2, '0')}</span><span>{current.label}</span><a href={assetUrl(current.url)} download>Descargar imagen ↗</a></figcaption></figure>
    <div className="render-thumbnails" aria-label="Seleccionar render">{manifest.renders.map((render, index) => <button key={render.id} className={index === selected ? 'thumbnail selected' : 'thumbnail'} onClick={() => setSelected(index)} aria-pressed={index === selected}><img src={assetUrl(render.url)} alt="" loading="lazy"/><span><small>{String(index + 1).padStart(2, '0')}</small>{render.label}<span aria-hidden="true">↗</span></span></button>)}</div>
  </section>;
}

export default function App() {
  const [manifestUrl, setManifestUrl] = useState<string | null>(null);
  const [manifest, setManifest] = useState<Manifest | null>(null);
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);
  const [viewerAttempt, setViewerAttempt] = useState(0);
  useEffect(() => {
    if (!manifestUrl) { setManifest(null); setError(''); return; }
    const controller = new AbortController();
    fetch(manifestUrl, { signal: controller.signal, cache: 'no-cache' })
      .then(response => { if (!response.ok) throw new Error(`Proyecto no disponible (HTTP ${response.status}).`); return response.json(); })
      .then(value => { setManifest(parseManifest(value, manifestUrl)); setError(''); })
      .catch((reason: Error) => { if (reason.name !== 'AbortError') setError(reason.message); });
    return () => controller.abort();
  }, [attempt, manifestUrl]);
  return <>
    <a className="skip-link" href="#main">Ir al contenido</a>
    <header className="site-header"><a href="#" className="wordmark" aria-label="González Cardona Arquitectura, inicio">GC<span className="wordmark-dot">.</span><span className="wordmark-sub">GONZÁLEZ CARDONA<br />ARQUITECTURA</span></a><nav aria-label="Navegación principal"><a href="#new-project">Nuevo proyecto</a>{manifest ? <><a href="#explore">Modelo 3D</a><a href="#renders">Renders</a></> : null}</nav><span className="edition">ESTUDIO DE VISUALIZACIÓN</span></header>
    <main id="main">
      <section className="intro"><div className="intro-copy"><span className="eyebrow"><span className="status-dot" /> GONZÁLEZ CARDONA ARQUITECTURA</span><h1>Del plano,<br /><em>al espacio.</em></h1><p>Sube un plano en PDF, revisa la interpretación de la IA junto al original<br />y obtén renders y un modelo 3D generados con Blender.</p></div><div className="project-summary"><span className="eyebrow">CÓMO FUNCIONA</span><ol className="how-steps"><li><strong>01</strong> Plano PDF y, opcionalmente, materiales</li><li><strong>02</strong> Revisión lado a lado con el original</li><li><strong>03</strong> Renders y modelo 3D con Blender</li></ol><a href="#new-project" className="text-link">Empezar un proyecto <span aria-hidden="true">↓</span></a></div></section>
      <Workflow onResult={url=>{setManifestUrl(url);setAttempt(n=>n+1);setError('');}} />
      {error ? <section className="load-error" role="alert"><h2>Los renders aún no están disponibles.</h2><p>{error}</p><button onClick={() => setAttempt(n => n + 1)}>Volver a cargar</button></section> : !manifest || !manifestUrl ? null : <>
        <Gallery key={manifestUrl} manifest={manifest}/>
        <section id="explore" aria-labelledby="viewer-title" className="explore-section"><div className="section-topline"><span className="eyebrow" id="viewer-title">RESULTADO / MODELO 3D</span><span className={`qa-status ${manifest.quality.passed ? 'passed' : 'pending'}`}><span className="status-dot" />{manifest.conceptual ? 'Modelo conceptual · QA de la escena' : manifest.quality.passed ? 'Comprobación geométrica superada' : 'Pendiente de validación geométrica'}</span></div>
          <ViewerBoundary key={`${manifestUrl}-${viewerAttempt}`} onRetry={() => setViewerAttempt(n => n + 1)}><Suspense fallback={<div className="viewer-placeholder" role="status">Preparando visor 3D…</div>}><Viewer manifest={manifest} attempt={viewerAttempt} /></Suspense></ViewerBoundary>
          <div className="viewer-footer"><span>Arrastra para orbitar · Rueda para acercar · Botón derecho para desplazar</span><a href={assetUrl(manifest.model_url)} download>Descargar modelo GLB <span aria-hidden="true">↗</span></a></div>
        </section>
        <section className="source-section" id="source"><div><span className="eyebrow">03 / TRAZABILIDAD</span><h2>Del documento<br />al modelo.</h2></div><div className="source-description"><p>Muros y huecos proceden de los vectores del PDF y de su escala impresa; la IA los selecciona y clasifica. Renders y visor comparten la misma escena de Blender.</p><dl><div><dt>Control de calidad</dt><dd>{manifest.quality.passed ? 'Comprobación geométrica superada' : 'Revisión requerida'}</dd></div><div><dt>Origen</dt><dd>{manifest.conceptual ? 'Interpretación de IA aprobada en revisión' : manifest.synthetic ? 'Datos sintéticos de prueba' : 'Geometría revisada manualmente'}</dd></div><div><dt>Acabados</dt><dd>{manifest.finishes && Object.keys(manifest.finishes).length ? Object.values(manifest.finishes).map(f => f.name).join(' · ') : 'Por defecto del estudio'}</dd></div><div><dt>Huella del PDF</dt><dd className="hash" title={manifest.source_sha256}>{manifest.source_sha256 ? `${manifest.source_sha256.slice(0, 16)}…` : 'No disponible'}</dd></div></dl><p className="source-note">Visualización conceptual: las medidas se infieren del PDF y su escala; mobiliario y acabados son ilustrativos. No sustituye la documentación técnica del proyecto.</p></div></section>
      </>}
    </main><footer className="site-footer"><span className="footer-brand">GC<span>.</span></span><p>González Cardona Arquitectura · Estudio de visualización</p><a href="#">Volver al inicio ↑</a></footer>
  </>;
}
