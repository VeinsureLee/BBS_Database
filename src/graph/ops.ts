import type { DriverHandle } from './driver.js';
import type { SqliteReader } from '../sqlite/reader.js';
import type { GraphOps } from './types.js';
import { ensureSchema } from './schema.js';
import { bootstrapStructure } from './bootstrap.js';
import { syncAllThreads } from './sync.js';

export interface GraphOpsDeps {
  driver: DriverHandle;
  /** Reserved: Task 19 will inject the reader into bootstrapStructure / syncAllThreads.
   * Currently unused by createGraphOps — those calls still read SQLite via the
   * module-level bridge (`readNodes()`, etc.). */
  sqlite: SqliteReader;
}

export function createGraphOps(deps: GraphOpsDeps): GraphOps {
  return {
    ensureSchema: () => ensureSchema(deps.driver),
    bootstrap:    () => bootstrapStructure({ driver: deps.driver }),
    sync:         () => syncAllThreads({ driver: deps.driver }),
  };
}
