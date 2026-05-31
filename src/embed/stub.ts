import { createHash } from 'node:crypto';
import type { Embedder } from './types.js';

const DIMS = 384;

/**
 * Deterministic SHA-256-derived pseudo-embedding. Zero API calls. Vectors are
 * L2-normalized so cosine similarity is well-defined. Use as default in tests
 * and wiring smoke checks; replace with DashScopeEmbedder for real semantics.
 */
export class StubEmbedder implements Embedder {
  readonly model = 'stub';
  readonly dims = DIMS;

  async embed(texts: string[]): Promise<Float32Array[]> {
    return texts.map((t) => deriveVector(t));
  }
}

function deriveVector(text: string): Float32Array {
  const out = new Float32Array(DIMS);
  // Stream SHA-256 digests with rolling salt to fill DIMS float slots (2 bytes of hash material each).
  let salt = 0;
  let filled = 0;
  while (filled < DIMS) {
    const h = createHash('sha256').update(`${salt}:${text}`).digest();
    for (let i = 0; i < h.length && filled < DIMS; i += 2) {
      // map two bytes to a signed float in roughly [-1, 1]
      const u = h.readUInt16LE(i);
      out[filled++] = (u - 32768) / 32768;
    }
    salt++;
  }
  // L2 normalize
  let n = 0;
  for (let i = 0; i < DIMS; i++) n += out[i]! * out[i]!;
  n = Math.sqrt(n) || 1;
  for (let i = 0; i < DIMS; i++) out[i] = out[i]! / n;
  return out;
}
