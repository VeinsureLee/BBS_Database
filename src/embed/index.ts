import type { Embedder } from './types.js';
import { StubEmbedder } from './stub.js';

export type EmbedderConfig =
  | { kind: 'stub' }
  | { kind: 'dashscope'; apiKey: string; model?: string }
  | { kind: 'openai'; apiKey: string; model?: string };

export function createEmbedder(cfg: EmbedderConfig = { kind: 'stub' }): Embedder {
  switch (cfg.kind) {
    case 'stub':
      return new StubEmbedder();
    case 'dashscope':
      throw new Error('dashscope embedder not implemented yet (Phase 6 in design.md)');
    case 'openai':
      throw new Error('openai embedder not implemented yet');
    default: {
      const _exhaustive: never = cfg;
      throw new Error(`unknown embedder kind: ${JSON.stringify(_exhaustive)}`);
    }
  }
}

export { StubEmbedder } from './stub.js';
export type { Embedder, EmbedderKind } from './types.js';
