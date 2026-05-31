/**
 * Probe: are forum node_key (URL slug) and name (display text) consistent
 * with each other? If they're misaligned, the bug is in listSections (the
 * adapter parses anchors and pairs href→text wrong); if they match but
 * children are wrong, the bug is in the URL the BBS renders.
 */
import 'dotenv/config';
import Database from 'better-sqlite3';
import { resolve } from 'node:path';
import { parseEnv } from '../src/config.js';

const cfg = parseEnv(process.env);
const structureDb = resolve(cfg.dataRoot, 'structure.db');
const sdb = new Database(structureDb, { readonly: true });

const forums = sdb
  .prepare(`SELECT id, node_key, name FROM nodes WHERE type='forum' ORDER BY id`)
  .all() as Array<{ id: number; node_key: string; name: string }>;

console.log('id | node_key (URL slug) | name (display)');
console.log('---|---------------------|---------------');
for (const f of forums) {
  console.log(`${String(f.id).padStart(2)} | ${f.node_key.padEnd(20)} | ${f.name}`);
}

// Also: for each forum, list a couple direct children with their node_keys
console.log('\n--- direct children sample per forum ---');
for (const f of forums) {
  const ch = sdb
    .prepare(`SELECT node_key, name, type FROM nodes WHERE parent_id=? ORDER BY id LIMIT 3`)
    .all(f.id) as Array<{ node_key: string; name: string; type: string }>;
  console.log(`\n[${f.id}] ${f.name} (slug=${f.node_key})`);
  for (const c of ch) console.log(`    ${c.type.padEnd(10)} slug=${c.node_key.padEnd(20)} name=${c.name}`);
}

sdb.close();
