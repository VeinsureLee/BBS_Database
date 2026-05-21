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
 * MERGE-only: rerunning is idempotent.
 */
import { readNodes, readSites, type NodeRow, type NodeType } from '../sqlite/reader.js';
import { withSession } from './driver.js';

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

export interface BootstrapStats {
  sites: number;
  forums: number;
  sub_forums: number;
  boards: number;
  edges: number;
}

export async function bootstrapStructure(): Promise<BootstrapStats> {
  const sites = readSites();
  const nodes = readNodes();

  const stats: BootstrapStats = {
    sites: sites.length,
    forums: nodes.filter((n) => n.type === 'forum').length,
    sub_forums: nodes.filter((n) => n.type === 'sub_forum').length,
    boards: nodes.filter((n) => n.type === 'board').length,
    edges: 0,
  };

  await withSession(async (s) => {
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
