/**
 * Bootstrap the physical structure from crawler's structure.db into Neo4j.
 *
 * Maps SQLite nodes to graph labels:
 *   sites    -> :Site
 *   nodes.type = 'forum'      -> :Forum
 *   nodes.type = 'sub_forum'  -> :SubForum
 *   nodes.type = 'board'      -> :Board
 *
 * Edges:
 *   (:Site)-[:HAS_CHILD]->(:Forum) for every top-level forum on the site
 *   (parent)-[:HAS_CHILD]->(child) for every node with parent_id
 *
 * Convergent (not just idempotent): each run **deletes all existing HAS_CHILD
 * edges first**, then re-creates them from the current structure.db. This
 * means re-running after the crawler corrects a parent_id reliably ends with
 * the right topology — a board that moved between forums will lose its old
 * parent edge, not accumulate a second one. Nodes (:Thread / :Month) and
 * non-tree edges (:LOCATED_IN / :POSTED_IN / future :MEANS) are untouched.
 */
import { readNodes, readSites, type NodeRow, type NodeType } from '../sqlite/reader.js';
import type { DriverHandle } from './driver.js';
import { withSession as legacyWithSession } from './driver.js';
import type { BootstrapStats } from './types.js';
export type { BootstrapStats } from './types.js';

const LABEL_BY_TYPE: Record<NodeType, 'Forum' | 'SubForum' | 'Board'> = {
  forum: 'Forum',
  sub_forum: 'SubForum',
  board: 'Board',
};

function nodeProps(n: NodeRow) {
  return {
    node_id: n.id,
    node_key: n.node_key,
    name: n.name,
    level: n.level,
    full_path: n.full_path,
    db_path: n.db_path,
    site_key: n.site_key,
  };
}

export interface BootstrapDeps {
  driver: DriverHandle;
  // future: sqlite: SqliteReader (Task 14)
}

export async function bootstrapStructure(deps?: BootstrapDeps): Promise<BootstrapStats> {
  const sites = readSites();
  const nodes = readNodes();

  const stats: BootstrapStats = {
    sites: sites.length,
    forums: nodes.filter((n) => n.type === 'forum').length,
    sub_forums: nodes.filter((n) => n.type === 'sub_forum').length,
    boards: nodes.filter((n) => n.type === 'board').length,
    edges: 0,
    pruned_edges: 0,
  };

  const runIn = deps
    ? <T>(fn: (s: import('neo4j-driver').Session) => Promise<T>) => deps.driver.withSession(fn)
    : legacyWithSession;

  await runIn(async (s) => {
    // Prune all existing HAS_CHILD edges before re-creating from SQLite. This
    // ensures convergence after the crawler fixes a wrong parent_id — a board
    // that re-attached to a different forum won't keep its stale parent edge.
    // Safe: only HAS_CHILD is wiped; nodes + LOCATED_IN + POSTED_IN survive.
    const cnt = await s.run('MATCH ()-[r:HAS_CHILD]->() RETURN count(r) AS n');
    stats.pruned_edges = Number(cnt.records[0]?.get('n') ?? 0);
    if (stats.pruned_edges > 0) {
      await s.run('MATCH ()-[r:HAS_CHILD]->() DELETE r');
    }

    // Sites — single-site MVP, show the Chinese root label "论坛" so the
    // Neo4j Browser visualisation has an obvious root all 讨论区 hang off.
    // Original crawler display_name kept under `display_name`.
    for (const site of sites) {
      await s.run(
        `MERGE (x:Site {key: $key})
           SET x.name         = $name,
               x.display_name = $display_name,
               x.base_url     = $base_url`,
        {
          key: site.site_key,
          name: '论坛',
          display_name: site.display_name,
          base_url: site.base_url,
        },
      );
    }

    // Nodes — write in level order so parents exist when children get MERGEd.
    const ordered = [...nodes].sort((a, b) => a.level - b.level);
    for (const n of ordered) {
      const label = LABEL_BY_TYPE[n.type];
      await s.run(
        `MERGE (x:${label} {node_id: $node_id})
           SET x.node_key  = $node_key,
               x.name      = $name,
               x.level     = $level,
               x.full_path = $full_path,
               x.db_path   = $db_path,
               x.site_key  = $site_key`,
        nodeProps(n),
      );
    }

    // Edges
    // Site -> top-level Forum (parent_id IS NULL means top-level under its site)
    for (const n of nodes) {
      if (n.parent_id === null && n.type === 'forum') {
        const r = await s.run(
          `MATCH (s:Site {key: $site_key})
           MATCH (f:Forum {node_id: $nid})
           MERGE (s)-[:HAS_CHILD]->(f)
           RETURN 1`,
          { site_key: n.site_key, nid: n.id },
        );
        stats.edges += r.records.length;
      }
    }

    // child node -> parent node, label-agnostic (parent could be Forum / SubForum)
    for (const n of nodes) {
      if (n.parent_id !== null) {
        const childLabel = LABEL_BY_TYPE[n.type];
        const r = await s.run(
          `MATCH (p) WHERE (p:Forum OR p:SubForum) AND p.node_id = $pid
           MATCH (c:${childLabel} {node_id: $cid})
           MERGE (p)-[:HAS_CHILD]->(c)
           RETURN 1`,
          { pid: n.parent_id, cid: n.id },
        );
        stats.edges += r.records.length;
      }
    }
  });

  return stats;
}
