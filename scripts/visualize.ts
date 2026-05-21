/**
 * One-shot for Phase 1: ensure schema, mirror tree, sync threads.
 * After this finishes, open http://localhost:7474 and try the Cypher in
 * NEO4J_QUICKSTART.md.
 */
import { ensureSchema } from '../src/graph/schema.js';
import { bootstrapStructure } from '../src/graph/bootstrap.js';
import { syncAllThreads } from '../src/graph/sync.js';
import { closeDriver, withSession } from '../src/graph/driver.js';

async function countLabel(label: string): Promise<number> {
  return withSession(async (s) => {
    const r = await s.run(`MATCH (n:${label}) RETURN count(n) AS n`);
    return Number(r.records[0]?.get('n') ?? 0);
  });
}

async function countRel(type: string): Promise<number> {
  return withSession(async (s) => {
    const r = await s.run(`MATCH ()-[r:${type}]->() RETURN count(r) AS n`);
    return Number(r.records[0]?.get('n') ?? 0);
  });
}

async function summary() {
  return {
    Site: await countLabel('Site'),
    Forum: await countLabel('Forum'),
    SubForum: await countLabel('SubForum'),
    Board: await countLabel('Board'),
    Thread: await countLabel('Thread'),
    HAS_CHILD: await countRel('HAS_CHILD'),
    LOCATED_IN: await countRel('LOCATED_IN'),
  };
}

async function main() {
  console.log('[1/3] ensureSchema');
  await ensureSchema();
  console.log('[2/3] bootstrapStructure');
  console.log('       ', await bootstrapStructure());
  console.log('[3/3] syncAllThreads');
  console.log('       ', await syncAllThreads());
  console.log('graph summary:', await summary());
  console.log('\n  Open http://localhost:7474');
  console.log('  Login: neo4j / bbs_password_123');
  console.log('  Then see BBS_Database/NEO4J_QUICKSTART.md');
}

main()
  .catch((e) => {
    console.error(e);
    process.exitCode = 1;
  })
  .finally(() => closeDriver());
