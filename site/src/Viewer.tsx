import { Suspense, useEffect, useMemo, useRef, useState } from 'react';
import { Canvas, useThree } from '@react-three/fiber';
import { OrbitControls, OrthographicCamera, PerspectiveCamera, useGLTF, useProgress } from '@react-three/drei';
import { Box3, Mesh, Vector3, OrthographicCamera as ThreeOrthographicCamera } from 'three';
import type { OrbitControls as OrbitControlsImpl } from 'three-stdlib';
import { assetUrl } from './types';
import type { Manifest, View } from './types';

const labels: Record<View, string> = { exterior: 'Exterior', axonometric: 'Axonométrica', top: 'Planta', interior: 'Interior' };
type Bounds = { center: Vector3; size: Vector3 };

function Model({ url, floor, roof, walls, onReady }: { url: string; floor: string; roof: boolean; walls: boolean; onReady: (b: Bounds) => void }) {
  const { scene } = useGLTF(url);
  const model = useMemo(() => scene.clone(true), [scene]);
  useEffect(() => {
    const box = new Box3().setFromObject(model);
    if (box.isEmpty()) throw new Error('El GLB no contiene geometría visible.');
    onReady({ center: box.getCenter(new Vector3()), size: box.getSize(new Vector3()) });
  }, [model, onReady]);
  useEffect(() => {
    model.traverse(object => {
      const { kind, floor_id } = object.userData;
      object.visible = (floor === 'all' || !floor_id || floor_id === floor) && (roof || kind !== 'roof') && (walls || kind !== 'wall');
      if (object instanceof Mesh) { object.castShadow = true; object.receiveShadow = true; }
    });
  }, [model, floor, roof, walls]);
  return <primitive object={model} />;
}

function CameraRig({ view, reset, bounds, manifest, zoom }: { view: View; reset: number; bounds: Bounds; manifest: Manifest; zoom: number }) {
  const controls = useRef<OrbitControlsImpl>(null);
  const { camera, invalidate, size: viewport } = useThree();
  const span = Math.max(bounds.size.x, bounds.size.y, bounds.size.z, 1);
  useEffect(() => {
    const c = bounds.center;
    const widthFactor = Math.max(1, viewport.height / viewport.width);
    const distance = span * 1.5 * widthFactor;
    camera.up.set(0, 1, 0);
    let target = c.clone();
    if (view === 'interior' && manifest.cameras?.interior) {
      camera.position.fromArray(manifest.cameras.interior.position);
      target.fromArray(manifest.cameras.interior.target);
    } else if (view === 'top') {
      camera.up.set(0, 0, -1);
      if (camera instanceof ThreeOrthographicCamera) {
        camera.left = -viewport.width / 2; camera.right = viewport.width / 2;
        camera.top = viewport.height / 2; camera.bottom = -viewport.height / 2;
      }
      camera.zoom = Math.min(viewport.width, viewport.height) / (span * 1.25);
      camera.position.set(c.x, c.y + distance, c.z + 0.0001);
    } else if (view === 'exterior') {
      camera.position.set(c.x + distance * .8, c.y + distance * .44, c.z + distance);
    } else {
      camera.position.set(c.x + distance * .78, c.y + distance * .9, c.z + distance * .78);
    }
    camera.lookAt(target);
    if (controls.current) { controls.current.target.copy(target); controls.current.update(); }
    camera.updateProjectionMatrix();
    invalidate();
  }, [view, reset, bounds, camera, span, viewport.width, viewport.height, manifest.cameras, invalidate]);
  const lastZoom = useRef(0);
  useEffect(() => {
    if (zoom !== lastZoom.current && controls.current) {
      const target = controls.current.target;
      camera.position.sub(target).multiplyScalar(zoom > lastZoom.current ? .8 : 1.25).add(target);
      if ('isOrthographicCamera' in camera) { camera.zoom *= zoom > lastZoom.current ? 1.25 : .8; camera.updateProjectionMatrix(); }
      lastZoom.current = zoom;
      controls.current.update(); invalidate();
    }
  }, [zoom, camera, invalidate]);
  return <OrbitControls ref={controls} makeDefault enableDamping minDistance={span * .025} maxDistance={span * 8} maxPolarAngle={Math.PI * .49} enableRotate={view !== 'top'} />;
}

function Progress() {
  const { active, progress } = useProgress();
  return active ? <div className="model-progress" role="status"><span>Cargando geometría</span><progress value={progress} max={100}/><small>{Math.round(progress)}%</small></div> : null;
}

export default function Viewer({ manifest, attempt }: { manifest: Manifest; attempt: number }) {
  const [view, setView] = useState<View>('axonometric');
  const [floor, setFloor] = useState('all');
  const [roof, setRoof] = useState(true);
  const [walls, setWalls] = useState(true);
  const [reset, setReset] = useState(0);
  const [zoom, setZoom] = useState(0);
  const [bounds, setBounds] = useState<Bounds | null>(null);
  const [lostContext, setLostContext] = useState(false);
  const [selection, setSelection] = useState('');
  const modelUrl = `${assetUrl(manifest.model_url)}${attempt ? `?retry=${attempt}` : ''}`;
  const views: View[] = manifest.cameras?.interior ? ['exterior', 'axonometric', 'top', 'interior'] : ['exterior', 'axonometric', 'top'];
  const span = bounds ? Math.max(bounds.size.x, bounds.size.z, bounds.size.y, 1) : 10;
  return <div className="viewer-shell">
    <div className="viewer-toolbar"><div className="view-tabs" role="group" aria-label="Punto de vista">{views.map(v => <button key={v} aria-pressed={view === v} onClick={() => { setView(v); setReset(n => n + 1); }}>{labels[v]}</button>)}</div><label className="floor-select"><span>Planta</span><select value={floor} onChange={event => setFloor(event.target.value)}><option value="all">Todas las plantas</option>{manifest.floors.map(f => <option key={f.id} value={f.id}>{f.name}</option>)}</select></label></div>
    <div className="canvas-wrap" aria-label="Modelo arquitectónico interactivo" data-model-loaded={bounds ? 'true' : 'false'}>
      <Canvas shadows dpr={[1, 1.5]} frameloop="demand" gl={{ antialias: true, preserveDrawingBuffer: true }} onCreated={({ gl }) => { gl.domElement.addEventListener('webglcontextlost', event => { event.preventDefault(); setLostContext(true); }); }} onPointerMissed={() => setSelection('')}>
        <color attach="background" args={['#e8e6df']} />
        {view === 'top' ? <OrthographicCamera makeDefault position={[0, 20, 0]} zoom={40} near={.01} far={span * 30} /> : <PerspectiveCamera makeDefault fov={42} near={.01} far={span * 30} position={[12, 12, 12]} />}
        <ambientLight intensity={1.1} /><hemisphereLight args={['#f6f7ff', '#b4a58d', 1.5]} /><directionalLight position={[span, span * 2, span]} intensity={2.5} castShadow shadow-mapSize={[2048, 2048]} shadow-camera-left={-span} shadow-camera-right={span} shadow-camera-top={span} shadow-camera-bottom={-span} shadow-camera-far={span * 6} shadow-bias={-.0003} />
        <Suspense fallback={null}><group onClick={event => { event.stopPropagation(); const data = event.object.userData; setSelection(`${data.id ?? event.object.name}${data.kind ? ` · ${data.kind}` : ''}`); }}><Model url={modelUrl} floor={floor} roof={roof} walls={walls} onReady={setBounds}/></group></Suspense>
        {bounds ? <><CameraRig view={view} reset={reset} bounds={bounds} manifest={manifest} zoom={zoom}/><mesh rotation={[-Math.PI / 2, 0, 0]} position={[bounds.center.x, bounds.center.y - bounds.size.y / 2 - .015, bounds.center.z]} receiveShadow><planeGeometry args={[span * 8, span * 8]}/><shadowMaterial transparent opacity={.13}/></mesh></> : null}
      </Canvas>
      <Progress/>
      <div className="canvas-caption"><span className="eyebrow">{manifest.project_id}</span><span>{labels[view]} / {manifest.units}</span></div>
      <div className="view-options"><label><input type="checkbox" disabled={!manifest.has_roof} checked={roof && !!manifest.has_roof} onChange={e => setRoof(e.target.checked)}/> {manifest.has_roof ? "Cubierta" : "Sin cubierta definida"}</label><label><input type="checkbox" checked={walls} onChange={e => setWalls(e.target.checked)}/> Muros</label></div>
      <div className="camera-actions" role="group" aria-label="Controles de cámara"><button onClick={() => setZoom(n => n + 1)} aria-label="Acercar">+</button><button onClick={() => setZoom(n => n - 1)} aria-label="Alejar">−</button><button onClick={() => { setView('axonometric'); setReset(n => n + 1); setFloor('all'); setRoof(true); setWalls(true); }} aria-label="Restablecer cámara y visibilidad">↺</button></div>
      {selection ? <div className="object-selection" role="status">{selection}</div> : null}
      {lostContext ? <div className="viewer-error" role="alert"><h3>Se ha interrumpido el contexto WebGL.</h3><p>Recarga la página para restaurar el visor.</p><button onClick={() => window.location.reload()}>Recargar visor</button></div> : null}
    </div>
  </div>;
}
