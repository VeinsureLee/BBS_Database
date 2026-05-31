import 'dotenv/config';
import { createDatabase, parseEnv } from '../src/index.js';
import { createDriver, type DriverHandle } from '../src/graph/driver.js';

async function countLabel(driver: DriverHandle, label: string): Promise<number> {
  return driver.withSession(async (s) => {
    const r = await s.run(`MATCH (n:${label}) RETURN count(n) AS n`);
    return Number(r.records[0]?.get('n') ?? 0);
  });
}
async function countRel(driver: DriverHandle, type: string): Promise<number> {
  return driver.withSession(async (s) => {
    const r = await s.run(`MATCH ()-[r:${type}]->() RETURN count(r) AS n`);
    return Number(r.records[0]?.get('n') ?? 0);
  });
}

const cfg = parseEnv(process.env);
const db = await createDatabase(cfg);
const counter = createDriver(cfg.neo4j);

try {
  console.log('[1/3] ensureSchema');
  await db.graph.ensureSchema();
  console.log('[2/3] bootstrap');
  console.log('       ', await db.graph.bootstrap());
  console.log('[3/3] sync');
  console.log('       ', await db.graph.sync());

  console.log('\ngraph summary:', {
    Site:       await countLabel(counter, 'Site'),
    Forum:      await countLabel(counter, 'Forum'),
    SubForum:   await countLabel(counter, 'SubForum'),
    Board:      await countLabel(counter, 'Board'),
    Thread:     await countLabel(counter, 'Thread'),
    Month:      await countLabel(counter, 'Month'),
    HAS_CHILD:  await countRel(counter, 'HAS_CHILD'),
    LOCATED_IN: await countRel(counter, 'LOCATED_IN'),
    POSTED_IN:  await countRel(counter, 'POSTED_IN'),
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
  await counter.close();
  await db.shutdown();
}
