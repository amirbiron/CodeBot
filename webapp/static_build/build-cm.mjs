import { build } from 'esbuild';
import { mkdirSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const entry = resolve(__dirname, 'codemirror.bundle.entry.mjs');
const outfile = resolve(__dirname, '../static/js/codemirror.local.js');

mkdirSync(dirname(outfile), { recursive: true });

(async () => {
  try {
    await build({
      entryPoints: [entry],
      bundle: true,
      format: 'esm',
      platform: 'browser',
      target: ['es2018'],
      outfile,
      sourcemap: false,
      logLevel: 'info',
      treeShaking: true,
      legalComments: 'none',
      define: {
        'process.env.NODE_ENV': JSON.stringify(process.env.NODE_ENV || 'production'),
      },
    });
    console.log('[build-cm] Built:', outfile);
  } catch (err) {
    console.error('[build-cm] Failed:', err);
    process.exit(1);
  }
})();
