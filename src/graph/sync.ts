/**
 * Sync threads from every board.db that exists on disk into Neo4j.
 *
 * Edges emitted:
 *   (:Thread)-[:LOCATED_IN]->(:Board)            physical board the thread is in
 *   (:Thread)-[:POSTED_IN]->(:Month {year_month}) post-month bucket (year_month = "YYYY-MM")
 *
 * No :MEANS yet (Phase 3 once we have an embedder).
 *
 * Thread key:
 *   - design.md originally proposed (forum_db, kind, thread_id) back when there
 *     were separate pinned/plain tables. Crawler has since unified to a single
 *     `threads` table with `is_pinned` column and `url UNIQUE`.
 *   - We use `url` as Neo4j Thread key and store is_pinned as a boolean property.
 */
import { readBoardsWithDb, readThreadsForBoard, type ThreadRow } from '../sqlite/reader.js';
import type { DriverHandle } from './driver.js';
import { withSession as legacyWithSession } from './driver.js';
import type { SyncStats } from './types.js';
export type { SyncStats } from './types.js';

const BATCH = 500;

function yearMonthOf(posted_at: string | null): string | null {
  if (!posted_at || posted_at.length < 7) return null;
  const ym = posted_at.slice(0, 7);
  // sanity check: "YYYY-MM"
  if (!/^\d{4}-\d{2}$/.test(ym)) return null;
  return ym;
}

export interface SyncDeps {
  driver: DriverHandle;
  // future: sqlite: SqliteReader（Task 14）
}

export async function syncAllThreads(deps?: SyncDeps): Promise<SyncStats> {
  const boards = readBoardsWithDb();
  const stats: SyncStats = {
    boards_scanned: boards.length,
    boards_with_threads: 0,
    threads_synced: 0,
    located_in_edges: 0,
    posted_in_edges: 0,
    months_seen: 0,
  };
  const monthsSeen = new Set<string>();

  const runIn = deps
    ? <T>(fn: (s: import('neo4j-driver').Session) => Promise<T>) => deps.driver.withSession(fn)
    : legacyWithSession;

  await runIn(async (s) => {
    for (const board of boards) {
      const threads = readThreadsForBoard(board);
      if (threads.length === 0) continue;
      stats.boards_with_threads++;

      for (let i = 0; i < threads.length; i += BATCH) {
        const chunk = threads.slice(i, i + BATCH).map(threadParam);
        for (const row of chunk) if (row.year_month) monthsSeen.add(row.year_month);

        const result = await s.run(
          `UNWIND $rows AS row
           MERGE (t:Thread {url: row.url})
             SET t.thread_id     = row.thread_id,
                 t.board_node_id = row.board_node_id,
                 t.title         = row.title,
                 t.author        = row.author,
                 t.posted_at     = row.posted_at,
                 t.last_reply_at = row.last_reply_at,
                 t.reply_count   = row.reply_count,
                 t.view_count    = row.view_count,
                 t.is_pinned     = row.is_pinned,
                 t.forum_db      = row.forum_db
           WITH t, row
           MATCH (b:Board {node_id: row.board_node_id})
           MERGE (t)-[loc:LOCATED_IN]->(b)
           WITH t, row, loc
           FOREACH (ym IN CASE WHEN row.year_month IS NULL THEN [] ELSE [row.year_month] END |
             MERGE (m:Month {year_month: ym})
             MERGE (t)-[:POSTED_IN]->(m)
           )
           RETURN count(t) AS n_threads, count(loc) AS n_located`,
          { rows: chunk },
        );

        const rec = result.records[0];
        if (rec) {
          stats.threads_synced += Number(rec.get('n_threads'));
          stats.located_in_edges += Number(rec.get('n_located'));
        }
        stats.posted_in_edges += chunk.filter((r) => r.year_month !== null).length;
      }
    }
  });

  stats.months_seen = monthsSeen.size;
  return stats;
}

function threadParam(t: ThreadRow & { forum_db?: string }) {
  return {
    thread_id: t.id,
    board_node_id: t.board_node_id,
    url: t.url,
    title: t.title,
    author: t.author,
    posted_at: t.posted_at,
    last_reply_at: t.last_reply_at,
    reply_count: t.reply_count,
    view_count: t.view_count,
    is_pinned: t.is_pinned === 1,
    forum_db: t.forum_db ?? null,
    year_month: yearMonthOf(t.posted_at),
  };
}
