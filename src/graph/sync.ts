/**
 * Sync threads from every board.db that exists on disk into Neo4j.
 * Phase 1 only: :LOCATED_IN edge (physical). No :MEANS yet.
 *
 * Thread key:
 *   - design.md proposed (forum_db, kind, thread_id) when there were separate
 *     pinned/plain tables. Crawler has since unified to a single `threads`
 *     table with `is_pinned` column and `url UNIQUE`.
 *   - We use `url` as Neo4j Thread key (already URL-unique BBS-wide) and store
 *     is_pinned as a boolean property. Simpler and matches the live schema.
 */
import { readBoardsWithDb, readThreadsForBoard, type ThreadRow } from '../sqlite/reader.js';
import { withSession } from './driver.js';

export interface SyncStats {
  boards_scanned: number;
  boards_with_threads: number;
  threads_synced: number;
  located_in_edges: number;
}

const BATCH = 500;

export async function syncAllThreads(): Promise<SyncStats> {
  const boards = readBoardsWithDb();
  const stats: SyncStats = {
    boards_scanned: boards.length,
    boards_with_threads: 0,
    threads_synced: 0,
    located_in_edges: 0,
  };

  await withSession(async (s) => {
    for (const board of boards) {
      const threads = readThreadsForBoard(board);
      if (threads.length === 0) continue;
      stats.boards_with_threads++;

      for (let i = 0; i < threads.length; i += BATCH) {
        const chunk = threads.slice(i, i + BATCH).map(threadParam);

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
           MERGE (t)-[r:LOCATED_IN]->(b)
           RETURN count(t) AS n_threads, count(r) AS n_edges`,
          { rows: chunk },
        );

        const rec = result.records[0];
        if (rec) {
          stats.threads_synced += Number(rec.get('n_threads'));
          stats.located_in_edges += Number(rec.get('n_edges'));
        }
      }
    }
  });

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
  };
}
