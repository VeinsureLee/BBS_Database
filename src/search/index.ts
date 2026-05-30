import type { SearchAlgorithm } from './types.js';
import { NullSearch } from './null.js';

export type SearchConfig = { kind: 'null' };

// deps shape pre-declared for future implementations (e.g. VectorSearch will need
// driver + embedder). Empty for MVP; consumers may pass {} or omit entirely.
export interface SearchDeps {
  // future: driver: DriverHandle; embedder: Embedder;
}

export function createSearch(
  cfg: SearchConfig,
  _deps: SearchDeps = {},
): SearchAlgorithm {
  switch (cfg.kind) {
    case 'null':
      return new NullSearch();
    default: {
      const _exhaustive: never = cfg.kind;
      throw new Error(`unknown search kind: ${_exhaustive as string}`);
    }
  }
}

export { NullSearch } from './null.js';
export type {
  SearchAlgorithm,
  RouteHit,
  ThreadHit,
  CrawlTarget,
  SearchKind,
} from './types.js';
export { NotImplementedError } from './types.js';
