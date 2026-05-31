/**
 * One-shot Phase 1: ensure schema, mirror tree, sync threads, then print
 * the visualize URL hint.
 */
import { createDatabase, parseEnv } from '../src/index.js';

async function countLabel(db: Awaited<ReturnType<typeof createDatabase>>, label: string): Promise<number> {
  // Until graph.queries lands, just go through a raw session via the driver
  // we already constructed. Visualization script is dev-only; reusing the
  // factory's driver via a small back-door is OK here.
  const { withSession } = await import('../src/graph/driver.js');
  return withSession(async (s) => {
    const r = await s.run(`MATCH (n:${label}) RETURN count(n) AS n`);
    return Number(r.records[0]?.get('n') ?? 0);
  });
}

async function countRel(db: Awaited<ReturnType<typeof createDatabase>>, type: string): Promise<number> {
  const { withSession } = await import('../src/graph/driver.js');
  return withSession(async (s) => {
    const r = await s.run(`MATCH ()-[r:${type}]->() RETURN count(r) AS n`);
    return Number(r.records[0]?.get('n') ?? 0);
  });
}

const db = await createDatabase(parseEnv(process.env));
try {
  console.log('[1/3] ensureSchema');
  await db.graph.ensureSchema();
  console.log('[2/3] bootstrap');
  console.log('       ', await db.graph.bootstrap());
  console.log('[3/3] sync');
  console.log('       ', await db.graph.sync());

  console.log('\ngraph summary:', {
    Site:      await countLabel(db, 'Site'),
    Forum:     await countLabel(db, 'Forum'),
    SubForum:  await countLabel(db, 'SubForum'),
    Board:     await countLabel(db, 'Board'),
    Thread:    await countLabel(db, 'Thread'),
    Month:     await countLabel(db, 'Month'),
    HAS_CHILD: await countRel(db, 'HAS_CHILD'),
    LOCATED_IN: await countRel(db, 'LOCATED_IN'),
    POSTED_IN: await countRel(db, 'POSTED_IN'),
  });

  const info = db.visualize.info();
  console.log('\nvisualize:', info);
  console.log(`  Open ${info.url}`);
  console.log(`  Login: ${info.user} / <password>`);
  console.log(`  Try: ${info.hint}`);
} catch (e) {
  console.error(e);
  process.exitCode = 1;
} finally {
  await db.shutdown();
}
