#!/usr/bin/env node
import fs from 'fs';
import path from 'path';
import { computeSha256, gzipBuffer, toBase64, genId } from '../src/utils.js';
import { formatStart, formatChunk, formatEnd } from '../src/ChunkProtocol.js';

function printUsageAndExit() {
  console.error(`Usage: node bin/sm-chunk.js --file <path> --dst <dst/relative.ext> [--chunk-size 2000] [--no-gzip] [--id <uuid>]`);
  process.exit(1);
}

function parseArgs(argv) {
  const args = { chunkSize: 2000, gzip: true };
  for (let i = 2; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--file') args.file = argv[++i];
    else if (a === '--dst') args.dst = argv[++i];
    else if (a === '--chunk-size') args.chunkSize = parseInt(argv[++i], 10);
    else if (a === '--no-gzip') args.gzip = false;
    else if (a === '--id') args.id = argv[++i];
    else if (a === '-h' || a === '--help') { printUsageAndExit(); }
    else {
      console.error('Unknown arg:', a);
      printUsageAndExit();
    }
  }
  if (!args.file || !args.dst || !args.chunkSize || args.chunkSize <= 0) printUsageAndExit();
  return args;
}

function main() {
  const { file, dst, chunkSize, gzip, id: passedId } = parseArgs(process.argv);
  const fileBuf = fs.readFileSync(path.resolve(file));
  const sha256 = computeSha256(fileBuf); // hash of final saved content
  const payload = gzip ? gzipBuffer(fileBuf) : fileBuf;
  const base64 = toBase64(payload);
  const total = Math.ceil(base64.length / chunkSize);
  const id = passedId || genId();

  const start = formatStart({ id, path: dst, total_parts: total, encoding: 'base64', compression: gzip ? 'gzip' : 'none', sha256 });
  console.log(start + '\n');

  for (let i = 0; i < total; i++) {
    const slice = base64.slice(i * chunkSize, (i + 1) * chunkSize);
    const chunkMsg = formatChunk({ id, index: i + 1, total, dataB64: slice });
    console.log(chunkMsg + '\n');
  }

  console.log(formatEnd({ id }));
}

main();