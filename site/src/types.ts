export type Point3 = [number, number, number];
export interface Manifest {
  project_id: string;
  title: string;
  synthetic: boolean;
  conceptual?: boolean;
  assumptions?: string[];
  units: string;
  model_url: string;
  renders: { id: string; label: string; url: string }[];
  floors: { id: string; name: string; elevation: number }[];
  quality: { passed: boolean };
  bounds?: { min: Point3; max: Point3 };
  source_sha256: string;
  has_roof?: boolean;
  cameras?: { interior?: { position: Point3; target: Point3 } };
}
export type View = 'exterior' | 'axonometric' | 'top' | 'interior';
export const projectBase = `${import.meta.env.BASE_URL}project/`;
export const assetUrl = (relative: string) => relative.startsWith('/api/projects/') ? relative : `${projectBase}${relative}`;
export function parseManifest(value: unknown, manifestPath = `${projectBase}manifest.json`): Manifest {
  if (!value || typeof value !== 'object') throw new Error('El manifiesto del proyecto no es válido.');
  const m = value as Manifest;
  if (typeof m.project_id !== 'string' || typeof m.title !== 'string' || typeof m.model_url !== 'string' ||
    !Array.isArray(m.renders) || !Array.isArray(m.floors) || typeof m.quality?.passed !== 'boolean') {
    throw new Error('El proyecto no incluye los datos necesarios para su revisión.');
  }
  // Only project-local assets are accepted; this presentation never fetches client files remotely.
  const paths = [m.model_url, ...m.renders.map(r => r.url)];
  if (paths.some(p => typeof p !== 'string' || p.includes('..') || p.startsWith('/') || /^[a-z]+:/i.test(p))) {
    throw new Error('Las rutas de los recursos deben pertenecer a este proyecto.');
  }
  const base = new URL(manifestPath, window.location.href);
  if (base.origin !== window.location.origin) throw new Error('El proyecto debe pertenecer a este servidor local.');
  const resolve = (path: string) => {
    const url = new URL(path, base);
    if (url.origin !== base.origin) throw new Error('Recurso externo no permitido.');
    if (base.pathname.startsWith('/api/projects/')) {
      url.search = base.search;
      return url.pathname + url.search;
    }
    return path;
  };
  return {...m,model_url:resolve(m.model_url),renders:m.renders.map(r=>({...r,url:resolve(r.url)}))};
}
