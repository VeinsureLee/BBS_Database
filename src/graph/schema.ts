/**
 * Phase 1 schema: only the physical hierarchy and threads.
 * No :MEANS edges yet (those need an embedder; see design.md §3.2 / Phase 3).
 */
import type { DriverHandle } from './driver.js';

const STATEMENTS = [
  'CREATE CONSTRAINT site_key      IF NOT EXISTS FOR (s:Site)     REQUIRE s.key IS UNIQUE',
  'CREATE CONSTRAINT forum_nid     IF NOT EXISTS FOR (f:Forum)    REQUIRE f.node_id IS UNIQUE',
  'CREATE CONSTRAINT subforum_nid  IF NOT EXISTS FOR (n:SubForum) REQUIRE n.node_id IS UNIQUE',
  'CREATE CONSTRAINT board_nid     IF NOT EXISTS FOR (b:Board)    REQUIRE b.node_id IS UNIQUE',
  'CREATE CONSTRAINT thread_url    IF NOT EXISTS FOR (t:Thread)   REQUIRE t.url IS UNIQUE',
  'CREATE CONSTRAINT month_ym      IF NOT EXISTS FOR (m:Month)    REQUIRE m.year_month IS UNIQUE',
  'CREATE INDEX board_name         IF NOT EXISTS FOR (b:Board)    ON (b.name)',
  'CREATE INDEX thread_board       IF NOT EXISTS FOR (t:Thread)   ON (t.board_node_id)',
];

export async function ensureSchema(driver: DriverHandle): Promise<void> {
  await driver.withSession(async (s) => {
    for (const stmt of STATEMENTS) await s.run(stmt);
  });
}
