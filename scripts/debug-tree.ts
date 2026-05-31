/**
 * Cross-check: structure.db says parent_id=X for each node; what does the
 * Neo4j graph actually show as HAS_CHILD edges? If they disagree, bootstrap
 * has a bug.
 */
import Database from 'better-sqlite3';
import { resolve } from 'node:path';
import { parseEnv } from '../src/config.js';
import { createDriver } from '../src/graph/driver.js';

const cfg = parseEnv(process.env);
const driver = createDriver(cfg.neo4j);
const sdb = new Database(resolve(cfg.dataRoot, 'structure.db'), { readonly: true });

const forums = sdb
  .prepare(`SELECT id, name FROM nodes WHERE type='forum' ORDER BY id`)
  .all() as Array<{ id: number; name: string }>;
const byId = new Map(
  (sdb.prepare(`SELECT id, parent_id, name, type, level FROM nodes`).all() as any[]).map((r) => [r.id, r]),
);

console.log('--- forums (top-level, parent_id=null) ---');
for (const f of forums) console.log(`  id=${f.id}  ${f.name}`);

// For each forum, list direct children + sample deeper descendants
async function main() {
  for (const f of forums) {
    const directChildren = sdb
      .prepare(`SELECT id, name, type, level FROM nodes WHERE parent_id=?`)
      .all(f.id) as Array<{ id: number; name: string; type: string; level: number }>;
    console.log(`\n[${f.name}] (id=${f.id}) has ${directChildren.length} direct children in SQLite:`);
    for (const c of directChildren.slice(0, 5)) console.log(`    ${c.type} L${c.level}  id=${c.id}  ${c.name}`);
    if (directChildren.length > 5) console.log(`    ... +${directChildren.length - 5} more`);
  }

  console.log('\n=== Neo4j: 乡亲乡爱 reachable subtree ===');
  await driver.withSession(async (s) => {
    const q = await s.run(`
      MATCH (f:Forum {name:'乡亲乡爱'})-[:HAS_CHILD*0..3]->(n)
      RETURN labels(n) AS labels, n.node_id AS nid, n.name AS name
      ORDER BY n.node_id LIMIT 50
    `);
    for (const r of q.records) {
      console.log(`  ${(r.get('labels') as string[]).join(':')}  nid=${r.get('nid')}  name=${r.get('name')}`);
    }
  });

  console.log('\n=== Neo4j: who points at game boards (Warcraft etc.) ===');
  await driver.withSession(async (s) => {
    const q = await s.run(`
      MATCH (p)-[:HAS_CHILD]->(b:Board)
      WHERE b.name IN ['魔兽世界', 'Diablo', 'StarCraft', 'CounterStrike', 'WarCraft3']
      RETURN p.name AS parent_name, labels(p) AS parent_labels, b.name AS board
    `);
    for (const r of q.records) {
      console.log(`  parent=${r.get('parent_name')} (${(r.get('parent_labels') as string[]).join(':')})  →  ${r.get('board')}`);
    }
  });

  console.log('\n=== Neo4j: forums each level-2/3 board is reachable from ===');
  await driver.withSession(async (s) => {
    const q = await s.run(`
      MATCH (f:Forum)-[:HAS_CHILD*]->(b:Board)
      WHERE b.level >= 2
      WITH b, collect(DISTINCT f.name) AS forum_names
      WHERE size(forum_names) > 1
      RETURN b.name AS board, b.level AS level, forum_names
      LIMIT 20
    `);
    if (q.records.length === 0) console.log('  (none — every level≥2 board reachable from exactly one forum)');
    for (const r of q.records) {
      console.log(`  L${r.get('level')}  ${r.get('board')}  ←  forums: ${(r.get('forum_names') as string[]).join(', ')}`);
    }
  });

  sdb.close();
}

main().catch((e) => { console.error(e); process.exitCode = 1; }).finally(() => driver.close());
