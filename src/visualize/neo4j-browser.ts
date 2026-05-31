import type { VisualizeInfo, VisualizeProvider } from './types.js';

export interface Neo4jBrowserDeps {
  neo4j: { uri: string; user: string; database: string };
  /** Optional override; if omitted, derived from bolt URI host. */
  url?: string;
}

export class Neo4jBrowserProvider implements VisualizeProvider {
  readonly kind = 'neo4j-browser' as const;

  constructor(private readonly deps: Neo4jBrowserDeps) {}

  info(): VisualizeInfo {
    return {
      kind: this.kind,
      url: this.deps.url ?? deriveBrowserUrl(this.deps.neo4j.uri),
      user: this.deps.neo4j.user,
      database: this.deps.neo4j.database,
      hint:
        'In Neo4j Browser run: MATCH (s:Site)-[:HAS_CHILD*]->(b:Board) RETURN s,b LIMIT 100',
    };
  }
}

function deriveBrowserUrl(boltUri: string): string {
  // bolt://host:7687 -> http://host:7474. If parsing fails, fall back.
  try {
    const u = new URL(boltUri.replace(/^bolt(\+s|\+ssc)?:/, 'http:'));
    u.port = '7474';
    return `${u.protocol}//${u.hostname}:${u.port}`;
  } catch {
    return 'http://localhost:7474';
  }
}
