export type Point3 = [number, number, number];
export interface Manifest {
  project_id: string;
  title: string;
  synthetic: boolean;
  conceptual?: boolean;
  assumptions?: string[];
  finishes?: Record<string, { name: string; color: [number, number, number]; roughness: number }>;
  units: string;
  model_url: string;
  renders: Render[];
  enhancement?: Enhancement;
  floors: { id: string; name: string; elevation: number }[];
  quality: { passed: boolean };
  bounds?: { min: Point3; max: Point3 };
  source_sha256: string;
  source?: { format: 'pdf' | 'dwg' | 'dxf'; sha256: string; converter?: string | null };
  has_roof?: boolean;
  cameras?: { interior?: { position: Point3; target: Point3 } };
}
export interface RenderEnhancement { status: 'accepted' | 'rejected' | 'failed' | 'skipped'; fidelity?: number | null; cost_usd?: number | null; seconds?: number | null; attempts?: number; notice?: string | null }
export interface Render { id: string; label: string; url: string; enhanced_url?: string; enhancement?: RenderEnhancement }
export interface Enhancement {
  status: 'completed' | 'partial' | 'rejected' | 'failed' | 'unavailable' | 'disabled';
  notice: string; label: string; model: string; prompt_version: string; style_sha256?: string | null;
  location?: { used_in_prompt: string; fallback: boolean; source?: { label?: string } | null; confidence?: number | null; status?: string | null };
  images: number; accepted: number; rejected: number; failed: number; cost_usd: number; seconds: number;
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
  const paths = [m.model_url, ...m.renders.flatMap(r => r.enhanced_url === undefined ? [r.url] : [r.url, r.enhanced_url])];
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
  return {...m,model_url:resolve(m.model_url),renders:m.renders.map(r=>({...r,url:resolve(r.url),...(r.enhanced_url ? {enhanced_url:resolve(r.enhanced_url)} : {})}))};
}
