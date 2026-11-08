export type Point3 = [number, number, number];
export interface Manifest {
  project_id: string;
  title: string;
  synthetic: boolean;
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
export const assetUrl = (relative: string) => `${projectBase}${relative}`;
export function parseManifest(value: unknown): Manifest {
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
  return m;
}
