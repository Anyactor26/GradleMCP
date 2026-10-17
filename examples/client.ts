// Node 22.18+ built-in TypeScript stripping; no npm dependencies.
// node examples/client.ts project.zip
import { createWriteStream } from 'node:fs';
import { mkdir, readFile, unlink } from 'node:fs/promises';
import { createHash, randomUUID } from 'node:crypto';
import { basename } from 'node:path';
import { Readable, Transform } from 'node:stream';
import { pipeline } from 'node:stream/promises';

const base = (process.env.GRADLEMCP_URL ?? 'http://127.0.0.1:8000').replace(/\/$/, '');
const token = process.env.GRADLEMCP_TOKEN;
if (!token || !process.argv[2]) throw new Error('Set GRADLEMCP_TOKEN and supply a ZIP path');
const headers = { Authorization: `Bearer ${token}` };
async function api(path: string, body?: object | Uint8Array): Promise<any> {
    const binary = body instanceof Uint8Array;
    const response = await fetch(base + path, {
        headers: { ...headers, 'Content-Type': binary ? 'application/zip' : 'application/json' },
        method: body === undefined ? 'GET' : 'POST',
        body: body === undefined ? undefined : binary ? body as Uint8Array : JSON.stringify(body),
        signal: AbortSignal.timeout(30000),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}: ${(await response.text()).slice(0, 65536)}`);
    return response.json();
}
const capability = await api('/api/v1/capabilities');
const source = await readFile(process.argv[2]);
if (source.length > capability.limits.upload_mb * 1024 ** 2) throw new Error('ZIP exceeds upload limit');
const project = await api('/api/v1/projects', source);
const spec = { project_id: project.project_id, tasks: ['build'], idempotency_key: randomUUID() };
console.log(await api('/api/v1/projects/compatibility', spec));
let job = await api('/api/v1/builds', spec);
console.log('Job:', job.id);
const terminal = new Set(['succeeded', 'failed', 'cancelled', 'timed_out', 'resource_limit_exceeded']);
const deadline = Date.now() + 3600000;
while (!terminal.has(job.state)) {
    if (Date.now() > deadline) throw new Error(`Client wait expired; save job ID ${job.id}`);
    await new Promise(resolve => setTimeout(resolve, 3000));
    job = await api(`/api/v1/builds/${job.id}`);
    console.log(job.state);
}
let offset = 0;
for (;;) {
    const log = await api(`/api/v1/builds/${job.id}/logs?offset=${offset}`);
    process.stdout.write(log.text);
    offset = log.next_offset;
    if (log.eof) break;
}
if (job.state !== 'succeeded') {
    console.error(job.diagnostic);
    process.exit(1);
}
await mkdir('downloaded-artifacts', { recursive: true });
for (const artifact of await api(`/api/v1/builds/${job.id}/artifacts`)) {
    const response = await fetch(`${base}/api/v1/builds/${job.id}/artifacts/${artifact.id}`, { headers });
    if (!response.ok || !response.body) throw new Error('Artifact download failed');
    const hash = createHash('sha256');
    const digesting = new Transform({ transform(chunk, _encoding, callback) {
        hash.update(chunk); callback(null, chunk);
    } });
    const destination = `downloaded-artifacts/${artifact.id}-${basename(artifact.path)}`;
    await pipeline(Readable.fromWeb(response.body as any), digesting, createWriteStream(destination));
    if (hash.digest('hex') !== artifact.sha256) {
        await unlink(destination);
        throw new Error('Artifact digest mismatch');
    }
    console.log('Downloaded', destination);
}
