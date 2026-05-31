import type { Embedder } from './types.js';
import { StubEmbedder } from './stub.js';

export type EmbedderConfig =
  | { kind: 'stub' }
  | { kind: 'dashscope'; apiKey: string; model?: string }
  | { kind: 'openai'; apiKey: string; model?: string };

export function createEmbedder(cfg: EmbedderConfig = { kind: 'stub' }): Embedder {
  const { kind } = cfg;
  switch (kind) {
    case 'stub':
      return new StubEmbedder();
    case 'dashscope':
      throw new Error('dashscope embedder not implemented yet (Phase 6 in design.md)');
    case 'openai':
      throw new Error('openai embedder not implemented yet (Phase 6 in design.md)');
    default: {
      const _exhaustive: never = kind;
      throw new Error(`unknown embedder kind: ${_exhaustive as string}`);
    }
  }
}

export { StubEmbedder } from './stub.js';
export type { Embedder, EmbedderKind } from './types.js';
