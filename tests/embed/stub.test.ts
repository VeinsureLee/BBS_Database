import { describe, it, expect } from 'vitest';
import { StubEmbedder } from '../../src/embed/stub.js';

describe('StubEmbedder', () => {
  it('reports model and dims', () => {
    const e = new StubEmbedder();
    expect(e.model).toBe('stub');
    expect(e.dims).toBe(384);
  });

  it('returns one vector per input', async () => {
    const e = new StubEmbedder();
    const out = await e.embed(['hello', 'world', '张三']);
    expect(out).toHaveLength(3);
  });

  it('vectors are of expected dim and Float32', async () => {
    const e = new StubEmbedder();
    const [v] = await e.embed(['hello']);
    expect(v).toBeInstanceOf(Float32Array);
    expect(v!.length).toBe(384);
  });

  it('same input gives same output (deterministic)', async () => {
    const e = new StubEmbedder();
    const [a] = await e.embed(['张三老师怎么样']);
    const [b] = await e.embed(['张三老师怎么样']);
    expect(Array.from(a!)).toEqual(Array.from(b!));
  });

  it('different input gives different output', async () => {
    const e = new StubEmbedder();
    const [a] = await e.embed(['张三']);
    const [b] = await e.embed(['李四']);
    expect(Array.from(a!)).not.toEqual(Array.from(b!));
  });

  it('vectors are L2-normalized', async () => {
    const e = new StubEmbedder();
    const [v] = await e.embed(['hello world']);
    const norm = Math.sqrt(Array.from(v!).reduce((s, x) => s + x * x, 0));
    expect(norm).toBeCloseTo(1.0, 3);
  });
});
