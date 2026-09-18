#!/usr/bin/env node
// Local stand-in for a TTS vendor API, used to test the runner + exporter + site
// pipeline when the real host is unreachable. Speaks the Inworld streaming shape.
// Output bytes are a short WAV tone, so the site's players work in a preview.
import { createServer } from 'node:http';

function wavTone(hz = 440, seconds = 0.6, rate = 8000) {
  const n = Math.floor(seconds * rate);
  const data = Buffer.alloc(n * 2);
  for (let i = 0; i < n; i++) {
    const env = Math.min(1, i / (0.05 * rate), (n - i) / (0.1 * rate));
    data.writeInt16LE(Math.round(0.3 * env * Math.sin((2 * Math.PI * hz * i) / rate) * 32767), i * 2);
  }
  const h = Buffer.alloc(44);
  h.write('RIFF', 0); h.writeUInt32LE(36 + data.length, 4); h.write('WAVE', 8); h.write('fmt ', 12);
  h.writeUInt32LE(16, 16); h.writeUInt16LE(1, 20); h.writeUInt16LE(1, 22); h.writeUInt32LE(rate, 24);
  h.writeUInt32LE(rate * 2, 28); h.writeUInt16LE(2, 32); h.writeUInt16LE(16, 34); h.write('data', 36); h.writeUInt32LE(data.length, 40);
  return Buffer.concat([h, data]);
}

const port = Number(process.env.PORT ?? 9999);
createServer(async (req, res) => {
  let body = ''; for await (const c of req) body += c;
  if (!req.headers.authorization?.startsWith('Basic ')) { res.writeHead(401); return res.end('{"error":"unauthorized"}'); }
  const { text = '' } = JSON.parse(body || '{}');
  const wav = wavTone(300 + (text.length % 300));
  if (req.url === '/tts/v1/voice:stream') {
    res.writeHead(200, { 'Content-Type': 'application/x-ndjson' });
    const half = Math.floor(wav.length / 2);
    setTimeout(() => res.write(JSON.stringify({ result: { audioContent: wav.subarray(0, half).toString('base64') } }) + '\n'), 80);
    setTimeout(() => { res.write(JSON.stringify({ result: { audioContent: wav.subarray(half).toString('base64') } }) + '\n'); res.end(); }, 200 + text.length);
  } else if (req.url === '/tts/v1/voice') {
    setTimeout(() => { res.writeHead(200, { 'Content-Type': 'application/json' }); res.end(JSON.stringify({ audioContent: wav.toString('base64') })); }, 150 + text.length);
  } else { res.writeHead(404); res.end('not found'); }
}).listen(port, () => console.log(`mock tts on http://localhost:${port}`));
