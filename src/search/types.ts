export interface RouteHit {
  boardNodeId: number;
  name: string;
  score: number;
  isFallback: boolean;
}

export interface ThreadHit {
  url: string;
  title: string;
  meaningWeight: number;
  physicalBoardId: number;
}

export interface CrawlTarget {
  physicalBoardId: number;
  name: string;
  score: number;
}

export type SearchKind = 'null' | 'vector' | 'hybrid';

export interface SearchAlgorithm {
  readonly kind: SearchKind;
  routeIntent(query: string, topK?: number): Promise<RouteHit[]>;
  threadsByMeaningBoard(
    boardNodeId: number,
    opts?: { limit?: number; minWeight?: number },
  ): Promise<ThreadHit[]>;
  suggestCrawlTargets(
    input: { meaningBoardId: number } | { query: string },
    topK?: number,
  ): Promise<CrawlTarget[]>;
}

export class NotImplementedError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'NotImplementedError';
  }
}
