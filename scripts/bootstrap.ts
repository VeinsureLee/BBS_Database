/**
 * Phase 1, step 1: mirror sites + nodes tree into Neo4j.
 * Idempotent — safe to re-run.
 */
import { ensureSchema } from '../src/graph/schema.js';
import { bootstrapStructure } from '../src/graph/bootstrap.js';
import { closeDriver } from '../src/graph/driver.js';

async function main() {
  console.log('[1/2] ensuring constraints / indexes ...');
  await ensureSchema();
  console.log('[2/2] mirroring structure.db ...');
  const stats = await bootstrapStructure();
  console.log('done:', stats);
}

main()
  .catch((e) => {
    console.error(e);
    process.exitCode = 1;
  })
  .finally(() => closeDriver());
