/**
 * Phase 1, step 1: mirror sites + nodes tree into Neo4j. Idempotent + convergent.
 */
import { createDatabase, parseEnv } from '../src/index.js';

const db = await createDatabase(parseEnv(process.env));
try {
  console.log('[1/2] ensuring constraints / indexes ...');
  await db.graph.ensureSchema();
  console.log('[2/2] mirroring structure.db ...');
  console.log('done:', await db.graph.bootstrap());
} catch (e) {
  console.error(e);
  process.exitCode = 1;
} finally {
  await db.shutdown();
}
