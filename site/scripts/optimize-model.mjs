#!/usr/bin/env node
// Lossless resource deduplication; node identities, hierarchy and positions remain authoritative.
import { NodeIO } from '@gltf-transform/core';
import { ALL_EXTENSIONS } from '@gltf-transform/extensions';
import { dedup } from '@gltf-transform/functions';
import { stat, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { validateModel } from './validate-model.mjs';

const [input, output] = process.argv.slice(2);
if (!input || !output || resolve(input) === resolve(output)) {
  console.error('Usage: npm run optimize-model -- input.glb output.glb (distinct paths required)');
  process.exit(2);
}
const io = new NodeIO().registerExtensions(ALL_EXTENSIONS);
const doc = await io.read(input);
const identity = () => doc.getRoot().listNodes().map(node => ({ name: node.getName(), extras: node.getExtras(), matrix: node.getMatrix() }));
const before = JSON.stringify(identity());
await doc.transform(dedup({ propertyTypes: ['Accessor', 'Material', 'Texture'] }));
if (JSON.stringify(identity()) !== before) throw new Error('Optimization changed node identities or transforms.');
await io.write(output, doc);
const validation = await validateModel(output);
const report = { input_bytes: (await stat(input)).size, output_bytes: (await stat(output)).size, transforms: ['dedup accessors/materials/textures'], lossy: false, validation };
await writeFile(`${output}.optimization.json`, JSON.stringify(report, null, 2));
console.log(JSON.stringify(report, null, 2));
