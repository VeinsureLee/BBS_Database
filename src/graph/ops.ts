import type { DriverHandle } from './driver.js';
import type { SqliteReader } from '../sqlite/reader.js';
import type { GraphOps } from './types.js';
import { ensureSchema } from './schema.js';
import { bootstrapStructure } from './bootstrap.js';
import { syncAllThreads } from './sync.js';

export interface GraphOpsDeps {
  driver: DriverHandle;
  /** SQLite reader for crawler data; used by bootstrap and sync. */
  sqlite: SqliteReader;
}

export function createGraphOps(deps: GraphOpsDeps): GraphOps {
  return {
    ensureSchema: () => ensureSchema(deps.driver),
    bootstrap:    () => bootstrapStructure({ driver: deps.driver, sqlite: deps.sqlite }),
    sync:         () => syncAllThreads({ driver: deps.driver, sqlite: deps.sqlite }),
  };
}
