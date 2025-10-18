// Build a single JS bundle for Markdown preview without CDN
// Uses esbuild to bundle: markdown-it, plugins, highlight.js, katex (core), mermaid
// Output placed under webapp/static/js/md_preview.bundle.js and css under webapp/static/css/md_preview.bundle.css

import { build } from 'esbuild';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import fs from 'node:fs';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const outdirJs = path.resolve(__dirname, '../static/js');
const outdirCss = path.resolve(__dirname, '../static/css');

function ensureDir(p) {
  fs.mkdirSync(p, { recursive: true });
}

ensureDir(outdirJs);
ensureDir(outdirCss);

const banner = `/* Built for md_preview without CDN. Do not edit directly. */`;

// Entry module that exposes globals similar to what the template expects
const entryFile = path.resolve(__dirname, './md-preview-entry.js');
const cssIndex = path.resolve(__dirname, './md-preview-style.css');

// Build JS bundle
await build({
  entryPoints: [entryFile],
  outfile: path.join(outdirJs, 'md_preview.bundle.js'),
  bundle: true,
  format: 'iife',
  platform: 'browser',
  target: ['es2019'],
  banner: { js: banner },
  loader: {
    '.ttf': 'file',
    '.woff': 'file',
    '.woff2': 'file',
    '.eot': 'file',
    '.svg': 'file'
  },
  external: [],
  sourcemap: true,
});

// Build CSS bundle using esbuild with css entry
await build({
  entryPoints: [cssIndex],
  outfile: path.join(outdirCss, 'md_preview.bundle.css'),
  bundle: true,
  loader: {
    '.css': 'css',
    '.ttf': 'file',
    '.woff': 'file',
    '.woff2': 'file',
    '.eot': 'file',
    '.svg': 'file'
  },
  assetNames: 'fonts/[name]-[hash]',
  banner: { css: banner },
  sourcemap: true,
});

console.log('✅ md_preview bundles built');
