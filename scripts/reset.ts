/**
 * Drop everything in the Neo4j database. Destructive — for dev only.
 */
import { parseEnv } from '../src/index.js';
import { createDriver } from '../src/graph/driver.js';

const cfg = parseEnv(process.env);
const driver = createDriver(cfg.neo4j);
try {
  await driver.withSession(async (s) => {
    console.log('deleting nodes/edges ...');
    await s.run('MATCH (n) DETACH DELETE n');
    console.log('dropping constraints ...');
    const cs = await s.run('SHOW CONSTRAINTS YIELD name RETURN name');
    for (const r of cs.records) await s.run(`DROP CONSTRAINT ${r.get('name') as string}`);
    console.log('dropping indexes ...');
    const ix = await s.run('SHOW INDEXES YIELD name, type WHERE type <> "LOOKUP" RETURN name');
    for (const r of ix.records) await s.run(`DROP INDEX ${r.get('name') as string}`);
    console.log('done');
  });
} catch (e) {
  console.error(e);
  process.exitCode = 1;
} finally {
  await driver.close();
}
