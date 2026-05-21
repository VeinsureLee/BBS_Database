/**
 * Probe structure.db + a sample forum db to confirm current schema.
 * Run: npx tsx scripts/inspect.ts
 */
import Database from 'better-sqlite3';
import { resolve } from 'node:path';

const DATA_ROOT = resolve(import.meta.dirname, '..', 'data', 'crawler.db');
const STRUCTURE = resolve(DATA_ROOT, 'structure.db');
const SAMPLE_FORUM = resolve(DATA_ROOT, 'forums', '0', 'Advice.db');

function listSchema(file: string) {
  console.log(`\n=== ${file} ===`);
  const db = new Database(file, { readonly: true, fileMustExist: true });
  const rows = db
    .prepare(
      "SELECT type, name, sql FROM sqlite_master WHERE type IN ('table','view','index') AND name NOT LIKE 'sqlite_%' ORDER BY type, name",
    )
    .all() as Array<{ type: string; name: string; sql: string | null }>;
  for (const r of rows) {
    console.log(`--- ${r.type} ${r.name}`);
    if (r.sql) console.log(r.sql);
  }
  db.close();
}

function preview(file: string, table: string, n = 5) {
  console.log(`\n>>> preview ${table} (${file})`);
  const db = new Database(file, { readonly: true, fileMustExist: true });
  try {
    const rows = db.prepare(`SELECT * FROM ${table} LIMIT ${n}`).all();
    for (const r of rows) console.log(JSON.stringify(r));
    const c = db.prepare(`SELECT COUNT(*) AS n FROM ${table}`).get() as { n: number };
    console.log(`(total rows = ${c.n})`);
  } catch (e) {
    console.log('!! err', (e as Error).message);
  }
  db.close();
}

listSchema(STRUCTURE);
preview(STRUCTURE, 'sites');
preview(STRUCTURE, 'nodes', 10);

listSchema(SAMPLE_FORUM);
preview(SAMPLE_FORUM, 'threads', 3);

// Aggregate node types across structure.db
const sdb = new Database(STRUCTURE, { readonly: true, fileMustExist: true });
console.log('\n=== nodes by type/level ===');
console.log(
  sdb
    .prepare('SELECT type, level, COUNT(*) AS n FROM nodes GROUP BY type, level ORDER BY type, level')
    .all(),
);
console.log('\n=== sites ===');
console.log(sdb.prepare('SELECT * FROM sites').all());
console.log('\n=== sample board node rows (level=2..) ===');
console.log(
  sdb
    .prepare(
      "SELECT id, parent_id, site_key, node_key, name, type, level, db_path FROM nodes WHERE type='board' LIMIT 5",
    )
    .all(),
);
console.log('\n=== forum node rows (top level) ===');
console.log(
  sdb
    .prepare("SELECT id, parent_id, name, type, level, db_path FROM nodes WHERE type='forum'")
    .all(),
);
sdb.close();
