/**
 * Phase 1, step 2: sync every thread into Neo4j with :LOCATED_IN edge.
 * Requires bootstrap.ts to have run first (so Board nodes exist).
 */
import { syncAllThreads } from '../src/graph/sync.js';
import { closeDriver } from '../src/graph/driver.js';

async function main() {
  console.log('syncing threads ...');
  const stats = await syncAllThreads();
  console.log('done:', stats);
}

main()
  .catch((e) => {
    console.error(e);
    process.exitCode = 1;
  })
  .finally(() => closeDriver());
