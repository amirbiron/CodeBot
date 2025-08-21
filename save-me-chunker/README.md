# Save Me Chunker

Utilities and protocol for chunked file transfer over chat messages.

Protocol messages:

```
[FILE START]
id=<uuid>
path=<dst/relative.ext>
total_parts=<N>
encoding=base64
compression=<none|gzip>
sha256=<hash>

[FILE CHUNK i/N id=<uuid>]
<base64 data>

[FILE END id=<uuid>]
```

- encoding is always `base64`.
- compression: `gzip` or `none`.
- sha256 is of the final saved content (after decompression), recommended for integrity.

CLI to split a file into messages:

```
node ./bin/sm-chunk.js --file ./path/to/local.bin --dst data/upload.bin --chunk-size 2000 --no-gzip
```

Assemble demo (feeds messages from a text file):

```
node ./bin/sm-assemble-demo.js --input ./messages.txt --root ./out
```

Library usage (pseudo):

```js
import { ChunkAssembler } from './src/ChunkAssembler.js';
const assembler = new ChunkAssembler({ rootDir: '/safe/root' });
const ack1 = assembler.onMessage(startMessage, chatKey);
const ack2 = assembler.onMessage(chunkMessage, chatKey);
const ack3 = assembler.onMessage(endMessage, chatKey);
```

Integrate `onMessage` in your bot's message handler. Maintain a `chatKey` per conversation/thread/user.