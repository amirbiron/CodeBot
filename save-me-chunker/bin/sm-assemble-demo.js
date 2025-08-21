#!/usr/bin/env node
import fs from 'fs';
import path from 'path';
import { ChunkAssembler } from '../src/ChunkAssembler.js';

function printUsageAndExit() {
  console.error(`Usage: node bin/sm-assemble-demo.js --input <messages.txt> --root <output_root_dir> [--chat demo]`);
  process.exit(1);
}

function parseArgs(argv) {
  const args = { chat: 'demo' };
  for (let i = 2; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--input') args.input = argv[++i];
    else if (a === '--root') args.root = argv[++i];
    else if (a === '--chat') args.chat = argv[++i];
    else if (a === '-h' || a === '--help') { printUsageAndExit(); }
    else {
      console.error('Unknown arg:', a);
      printUsageAndExit();
    }
  }
  if (!args.input || !args.root) printUsageAndExit();
  return args;
}

function splitMessages(text) {
  // Split on blank lines before a [FILE ...] header, keeping blocks intact
  const blocks = [];
  let current = [];
  const lines = text.split(/\r?\n/);
  for (const line of lines) {
    if (/^\[FILE (START|CHUNK|END|CANCEL)/.test(line) && current.length) {
      blocks.push(current.join('\n').trim());
      current = [line];
      continue;
    }
    current.push(line);
  }
  if (current.length) blocks.push(current.join('\n').trim());
  return blocks.filter(Boolean);
}

function main() {
  const { input, root, chat } = parseArgs(process.argv);
  const assembler = new ChunkAssembler({ rootDir: path.resolve(root) });
  const text = fs.readFileSync(path.resolve(input), 'utf8');
  const blocks = splitMessages(text);
  for (const block of blocks) {
    const res = assembler.onMessage(block, chat);
    console.log('ACK:', JSON.stringify(res));
  }
}

main();