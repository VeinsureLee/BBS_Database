export { createDatabase } from './factory.js';
export type { Database, DatabaseFactoryConfig } from './factory.js';

export type { DatabaseConfig } from './config.js';
export { parseEnv } from './config.js';

export type { GraphOps, BootstrapStats, SyncStats } from './graph/types.js';
export type {
  SearchAlgorithm,
  RouteHit,
  ThreadHit,
  CrawlTarget,
  SearchKind,
} from './search/types.js';
export { NotImplementedError } from './search/types.js';
export type { VisualizeProvider, VisualizeInfo, VisualizeKind } from './visualize/types.js';
export type { Embedder, EmbedderKind } from './embed/types.js';

// --- DEPRECATED legacy bridges. Plan Task 21 removes these. ---
export { bootstrapStructure } from './graph/bootstrap.js';
export { syncAllThreads } from './graph/sync.js';
export { ensureSchema } from './graph/schema.js';
export { closeDriver, withSession } from './graph/driver.js';
export { config } from './config.js';
