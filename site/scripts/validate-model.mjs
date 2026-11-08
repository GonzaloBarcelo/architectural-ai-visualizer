#!/usr/bin/env node
import { readFile, writeFile } from 'node:fs/promises';
import { pathToFileURL } from 'node:url';
import { validateBytes } from 'gltf-validator';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { Box3, Vector3 } from 'three';

export async function validateModel(path) {
  const bytes = await readFile(path);
  const validation = await validateBytes(new Uint8Array(bytes), { uri: path, maxIssues: 100 });
  if (validation.issues.numErrors) throw new Error(`glTF validation failed: ${JSON.stringify(validation.issues)}`);
  // Blender's procedural materials are texture-free. Node rejects image-bearing models here;
  // those require the browser smoke test for image decode, never a false positive.
  const gltf = await new GLTFLoader().parseAsync(bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength), '');
  let meshCount = 0;
  let vertexCount = 0;
  const identifiers = [];
  gltf.scene.traverse(object => {
    if (object.isMesh) {
      meshCount++;
      vertexCount += object.geometry.getAttribute('position')?.count ?? 0;
      const id = object.userData.id ?? object.userData.source_id ?? object.name;
      identifiers.push(id);
      if (!id) throw new Error('Mesh lacks a stable identifier.');
      const positions = object.geometry.getAttribute('position');
      for (let i = 0; i < positions.count; i++) {
        if (![positions.getX(i), positions.getY(i), positions.getZ(i)].every(Number.isFinite)) throw new Error('Non-finite mesh position.');
      }
    }
  });
  const box = new Box3().setFromObject(gltf.scene);
  if (!meshCount || !vertexCount || box.isEmpty()) throw new Error('Export contains no usable mesh.');
  return { passed: true, validator_errors: validation.issues.numErrors, validator_warnings: validation.issues.numWarnings, three_loaded: true, mesh_count: meshCount, vertex_count: vertexCount, identifiers, bounds: { min: box.min.toArray(), max: box.max.toArray(), size: box.getSize(new Vector3()).toArray() } };
}
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const path = process.argv[2];
  if (!path) { console.error('Usage: npm run validate-model -- path/to/model.glb [report.json]'); process.exit(2); }
  const report = await validateModel(path);
  if (process.argv[3]) await writeFile(process.argv[3], JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 2));
}
