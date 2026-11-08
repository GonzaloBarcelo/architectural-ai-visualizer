import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { Document, NodeIO } from '@gltf-transform/core';
import { validateModel } from './validate-model.mjs';
const exec = promisify(execFile);

test('Three.js loads metric GLB and optimizer preserves bounds and source identifiers', async () => {
  const folder = await mkdtemp(join(tmpdir(), 'architectural-glb-'));
  try {
    const doc = new Document();
    const buffer = doc.createBuffer();
    const positions = doc.createAccessor().setBuffer(buffer).setType('VEC3').setArray(new Float32Array([0,0,0, 6,0,0, 6,0,4, 0,0,4]));
    const indices = doc.createAccessor().setBuffer(buffer).setType('SCALAR').setArray(new Uint16Array([0,2,1,0,3,2]));
    const mesh = doc.createMesh().addPrimitive(doc.createPrimitive().setAttribute('POSITION', positions).setIndices(indices));
    const node = doc.createNode('slab-001').setMesh(mesh).setExtras({ id: 'slab-001', floor_id: 'ground', kind: 'slab' });
    doc.createScene().addChild(node);
    const input = join(folder, 'input.glb');
    const output = join(folder, 'output.glb');
    await new NodeIO().write(input, doc);
    const before = await validateModel(input);
    assert.deepEqual(before.bounds.size, [6, 0, 4]);
    assert.deepEqual(before.identifiers, ['slab-001']);
    await exec(process.execPath, ['scripts/optimize-model.mjs', input, output], { cwd: new URL('..', import.meta.url) });
    const after = await validateModel(output);
    assert.deepEqual(after.bounds, before.bounds);
    assert.deepEqual(after.identifiers, before.identifiers);
    const optimized = await new NodeIO().read(output);
    assert.equal(optimized.getRoot().listNodes()[0].getExtras().floor_id, 'ground');
    assert.equal(JSON.parse(await readFile(`${output}.optimization.json`, 'utf8')).lossy, false);
  } finally { await rm(folder, { recursive: true, force: true }); }
});

test('corrupt GLB fails validation', async () => {
  const folder = await mkdtemp(join(tmpdir(), 'architectural-corrupt-'));
  try {
    const path = join(folder, 'corrupt.glb');
    await writeFile(path, 'not glTF');
    await assert.rejects(validateModel(path));
  } finally { await rm(folder, { recursive: true, force: true }); }
});
