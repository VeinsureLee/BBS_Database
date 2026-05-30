import type {
  CrawlTarget,
  RouteHit,
  SearchAlgorithm,
  ThreadHit,
} from './types.js';
import { NotImplementedError } from './types.js';

const ERR = 'search.kind=null — set DatabaseConfig.search.kind to enable';

export class NullSearch implements SearchAlgorithm {
  readonly kind = 'null' as const;

  async routeIntent(_query: string, _topK?: number): Promise<RouteHit[]> {
    throw new NotImplementedError(ERR);
  }

  async threadsByMeaningBoard(
    _meaningBoardId: number,
    _opts?: { limit?: number; minWeight?: number },
  ): Promise<ThreadHit[]> {
    throw new NotImplementedError(ERR);
  }

  async suggestCrawlTargets(
    _input: { meaningBoardId: number } | { query: string },
    _topK?: number,
  ): Promise<CrawlTarget[]> {
    throw new NotImplementedError(ERR);
  }
}
