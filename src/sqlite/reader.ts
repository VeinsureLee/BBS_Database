/**
 * Read-only access to the crawler's SQLite store.
 * - structure.db: sites + nodes (forum / sub_forum / board) tree
 * - forums/<level0>/.../<board>.db: per-board threads + posts
 *
 * Crawler is the only writer. We open immutable=1 so we never block writes and
 * skip the WAL protocol; design.md §10.2 calls this out as acceptable for MVP.
 */
import Database from 'better-sqlite3';
import { resolve } from 'node:path';
import { existsSync } from 'node:fs';
import { config } from '../config.js';

export interface SiteRow {
  site_key: string;
  display_name: string;
  base_url: string;
}

export type NodeType = 'forum' | 'sub_forum' | 'board';

export interface NodeRow {
  id: number;
  parent_id: number | null;
  site_key: string;
  node_key: string;
  name: string;
  type: NodeType;
  level: number;
  full_path: string | null;
  db_path: string | null;
}

export interface ThreadRow {
  id: number;
  board_node_id: number;
  url: string;
  title: string;
  author: string | null;
  posted_at: string | null;
  last_reply_at: string | null;
  reply_count: number | null;
  view_count: number | null;
  is_pinned: 0 | 1;
}

function openRo(file: string): Database.Database {
  return new Database(file, { readonly: true, fileMustExist: true });
}

export function readSites(): SiteRow[] {
  const db = openRo(config.structureDb);
  try {
    return db.prepare('SELECT site_key, display_name, base_url FROM sites').all() as SiteRow[];
  } finally {
    db.close();
  }
}

export function readNodes(): NodeRow[] {
  const db = openRo(config.structureDb);
  try {
    return db
      .prepare(
        `SELECT id, parent_id, site_key, node_key, name, type, level, full_path, db_path
           FROM nodes
          ORDER BY level, id`,
      )
      .all() as NodeRow[];
  } finally {
    db.close();
  }
}

/** Boards that have a db_path on disk. */
export function readBoardsWithDb(): NodeRow[] {
  return readNodes().filter((n) => n.type === 'board' && n.db_path && existsSync(resolve(config.dataRoot, n.db_path)));
}

export function readThreadsForBoard(board: NodeRow): ThreadRow[] {
  if (!board.db_path) return [];
  const file = resolve(config.dataRoot, board.db_path);
  if (!existsSync(file)) return [];
  const db = openRo(file);
  try {
    return db
      .prepare(
        `SELECT id, board_node_id, url, title, author, posted_at, last_reply_at,
                reply_count, view_count, is_pinned
           FROM threads
          WHERE board_node_id = ?`,
      )
      .all(board.id) as ThreadRow[];
  } finally {
    db.close();
  }
}
