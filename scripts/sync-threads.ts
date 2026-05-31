/**
 * Phase 1, step 2: sync every thread into Neo4j with :LOCATED_IN edge.
 */
import { createDatabase, parseEnv } from '../src/index.js';

const db = await createDatabase(parseEnv(process.env));
try {
  console.log('syncing threads ...');
  console.log('done:', await db.graph.sync());
} catch (e) {
  console.error(e);
  process.exitCode = 1;
} finally {
  await db.shutdown();
}
