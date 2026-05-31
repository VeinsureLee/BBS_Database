import { resolve } from 'node:path';
import type { DatabaseConfig } from './config.js';
import { createDriver, type DriverHandle, type Neo4jConfig } from './graph/driver.js';
import { createSqliteReader, type SqliteReader } from './sqlite/reader.js';
import { createGraphOps } from './graph/ops.js';
import type { GraphOps } from './graph/types.js';
import { createSearch, type SearchAlgorithm } from './search/index.js';
import { createVisualize, type VisualizeProvider } from './visualize/index.js';
import { createEmbedder, type Embedder } from './embed/index.js';

export interface DatabaseFactoryConfig extends Omit<DatabaseConfig, 'dataRoot' | 'neo4j'> {
  dataRoot?: string;
  neo4j: Neo4jConfig;
  search?:    { kind: 'null' };
  visualize?: { kind: 'neo4j-browser'; url?: string };
  embedder?:
    | { kind: 'stub' }
    | { kind: 'dashscope'; apiKey: string; model?: string }
    | { kind: 'openai'; apiKey: string; model?: string };
}

export interface Database {
  graph: GraphOps;
  search: SearchAlgorithm;
  visualize: VisualizeProvider;
  shutdown(): Promise<void>;
}

export async function createDatabase(cfg: DatabaseFactoryConfig): Promise<Database> {
  const dataRoot = cfg.dataRoot ?? defaultDataRoot();
  const driver: DriverHandle = createDriver(cfg.neo4j);
  const sqlite: SqliteReader = createSqliteReader(dataRoot);
  const _embedder: Embedder = createEmbedder(cfg.embedder ?? { kind: 'stub' });

  const graph = createGraphOps({ driver, sqlite });
  const search = createSearch(cfg.search ?? { kind: 'null' }, {});
  const visualize = createVisualize(
    cfg.visualize ?? { kind: 'neo4j-browser' },
    { neo4j: { uri: cfg.neo4j.uri, user: cfg.neo4j.user, database: cfg.neo4j.database } },
  );

  return {
    graph,
    search,
    visualize,
    shutdown: async () => {
      await driver.close();
      sqlite.close();
    },
  };
}

function defaultDataRoot(): string {
  // Resolve relative to this file's compiled location at runtime; matches the
  // legacy config.ts default. Scripts/tests can always pass dataRoot explicitly.
  return resolve(import.meta.dirname, '..', 'data', 'crawler.db');
}
