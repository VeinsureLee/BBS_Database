/**
 * Drop everything in the Neo4j database (nodes + relationships + constraints).
 * Useful if you change schema during development. Be careful — this is a
 * destructive op.
 */
import { withSession, closeDriver } from '../src/graph/driver.js';

async function main() {
  await withSession(async (s) => {
    console.log('deleting nodes/edges ...');
    await s.run('MATCH (n) DETACH DELETE n');
    console.log('dropping constraints ...');
    const cs = await s.run('SHOW CONSTRAINTS YIELD name RETURN name');
    for (const r of cs.records) {
      const name = r.get('name') as string;
      await s.run(`DROP CONSTRAINT ${name}`);
    }
    console.log('dropping indexes ...');
    const ix = await s.run('SHOW INDEXES YIELD name, type WHERE type <> "LOOKUP" RETURN name');
    for (const r of ix.records) {
      const name = r.get('name') as string;
      await s.run(`DROP INDEX ${name}`);
    }
    console.log('done');
  });
}

main()
  .catch((e) => {
    console.error(e);
    process.exitCode = 1;
  })
  .finally(() => closeDriver());
