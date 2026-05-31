# bbs-database

Neo4j-backed graph layer for the BBS_MCP stack. Reads the crawler's SQLite
tree (sites, forums, sub-forums, boards, threads) and exposes the same
structure as a property graph that supports semantic / multi-meaning
queries against board nodes.

Companion package of `bbs-crawler` (the writer) and `bbs-mcp` (the
embedder). The package is workspace-internal — only `bbs-mcp` imports
from it today.

## What it does

- **Graph bootstrap** — one-time MERGE of every Site / forum / sub_forum /
  board into Neo4j, with `LOCATED_IN` edges to their parents.
- **Thread sync** — idempotent insert of crawled threads into the same
  graph, with `POSTED_IN` (thread → board) and `LOCATED_IN` (thread →
  monthly partition node) edges.
- **Visualize info** — returns the Neo4j Browser URL + user/database
  hint so an agent can tell a human "open this URL to see the graph".
- **Search API (placeholder)** — `SearchAlgorithm` interface defines
  `routeIntent` / `threadsByMeaningBoard` / `suggestCrawlTargets`. The
  only shipped implementation is `NullSearch` (throws
  `NotImplementedError`); real implementations (vector / heuristic) land
  in M5+.

## Install + build

```bash
npm install
npm run build
```

The package compiles to `dist/index.js`. Workspace consumers depending
on `bbs-database: "*"` resolve via npm workspaces — no publish.

## Configuration

Reads env via `parseEnv(env)`:

| Env var | Default | Meaning |
|---|---|---|
| `BBS_DATA_ROOT` | `<package>/data/crawler.db` | Crawler SQLite root (must match the writer's path) |
| `NEO4J_URI` | `bolt://localhost:7687` | Neo4j bolt endpoint |
| `NEO4J_USER` | `neo4j` | Username |
| `NEO4J_PASSWORD` | — (REQUIRED) | Password (no default; bootstrap throws if unset) |
| `NEO4J_DATABASE` | `neo4j` | Database name |

When embedded by bbs-mcp, `BBS_DATA_ROOT` is injected from
`BBS_MCP_DATA_ROOT` so the crawler-writer and graph-reader see the same
location.

## API

```ts
import { createDatabase, parseEnv } from 'bbs-database';

const db = await createDatabase(parseEnv(process.env));
//                ↑ { graph, search, visualize, shutdown }

await db.graph.ensureSchema();        // create constraints + indexes
await db.graph.bootstrap();           // import the structure tree
await db.graph.sync();                // sync newly crawled threads

const info = db.visualize.info();
console.log(info.url, info.hint);

// Search is null for now:
try {
  await db.search.routeIntent({ query: 'whatever' });
} catch (e) {
  // NotImplementedError until M5+
}

await db.shutdown();
```

## Layout

```
src/
  factory.ts            createDatabase entry; wires graph + search + visualize
  config.ts             parseEnv() — reads NEO4J_* + BBS_DATA_ROOT
  graph/
    driver.ts           Neo4j driver handle + session helper
    schema.ts           constraints + indexes (ensureSchema)
    bootstrap.ts        Site → forum/sub_forum/board MERGE
    sync.ts             threads + LOCATED_IN(month) sync
    ops.ts              GraphOps shape returned by createDatabase
    types.ts            BootstrapStats / SyncStats / GraphOps types
  sqlite/
    reader.ts           Read-only SQLite reader for the crawler's data
  search/
    types.ts            SearchAlgorithm + RouteHit / ThreadHit / CrawlTarget
    null.ts             NullSearch — throws NotImplementedError
    index.ts            createSearch dispatcher
  visualize/
    types.ts            VisualizeProvider + VisualizeInfo
    neo4j-browser.ts    Provider that returns the Neo4j Browser URL
    index.ts            createVisualize dispatcher
  embed/
    types.ts            Embedder interface (used by future vector search)
```

## Neo4j setup

The package does NOT manage a Neo4j process. You bring your own. Easiest
path on a dev machine:

```bash
# Linux / macOS / WSL
brew install neo4j        # or apt install neo4j
neo4j console             # foreground; first login at http://localhost:7474
```

See `NEO4J_QUICKSTART.md` for a longer walkthrough.

## Development

```bash
npm test                  # vitest — 34 tests cover schema, bootstrap, sync, search dispatch
npm run lint:tsc          # tsc --noEmit
npm run build             # tsc → dist/
```

The build was packaging-broken in v3.0 (output landed in `dist/src/`
while `package.json.main` pointed at `dist/index.js`). Fixed in 5db21a6
— `tsconfig.json` now sets `rootDir: "src"` and excludes scripts/tests.

## Status

Pre-release. Graph layer is functional (bootstrap + sync + visualize).
Search is intentionally `null` — the API exists so MCP can wire it
unconditionally; real implementations land when the embedding /
classification work is done.
