# bbs-database

BBS_MCP 套件的 Neo4j 图层。从 crawler 的 SQLite 树（sites、forums、
sub_forums、boards、threads）读结构，在 Neo4j 中维护一份同构的属性图，
支撑面向版面的语义 / 多义查询。

`bbs-crawler`（写入方）与 `bbs-mcp`（嵌入方）的伴随包。目前只有 `bbs-mcp`
通过 workspace 引用它，不对外发布。

## 它做什么

- **图引导（bootstrap）** —— 一次性 MERGE 全部 Site / forum / sub_forum /
  board 节点及其 `LOCATED_IN` 父子边
- **帖子同步（sync）** —— 幂等地把已抓帖子写入图，附带 `POSTED_IN`
  （thread → board）和 `LOCATED_IN`（thread → 月份分区节点）边
- **可视化信息（visualize.info）** —— 返回 Neo4j Browser 的 URL +
  user/database 提示，agent 可以告诉用户"去这个网址看图"
- **搜索 API（占位）** —— `SearchAlgorithm` 接口定义了 `routeIntent` /
  `threadsByMeaningBoard` / `suggestCrawlTargets`。目前唯一实现是
  `NullSearch`（一律抛 `NotImplementedError`）。真实实现（向量 / 启发）
  留给 M5+

## 安装 + 构建

```bash
npm install
npm run build
```

包编译产物在 `dist/index.js`。workspace 消费者通过 `bbs-database: "*"`
解析，不需要发布。

## 配置

`parseEnv(env)` 读取的环境变量：

| 变量 | 默认值 | 含义 |
|---|---|---|
| `BBS_DATA_ROOT` | `<package>/data/crawler.db` | crawler SQLite 根目录（必须与写入方一致） |
| `NEO4J_URI` | `bolt://localhost:7687` | Neo4j bolt 端点 |
| `NEO4J_USER` | `neo4j` | 用户名 |
| `NEO4J_PASSWORD` | —（必填） | 密码（无默认；缺失时抛错） |
| `NEO4J_DATABASE` | `neo4j` | 数据库名 |

被 bbs-mcp 嵌入时，`BBS_DATA_ROOT` 由 `BBS_MCP_DATA_ROOT` 注入，
保证写入方（crawler）与读取方（database）看到同一路径。

## API

```ts
import { createDatabase, parseEnv } from 'bbs-database';

const db = await createDatabase(parseEnv(process.env));
//                ↑ { graph, search, visualize, shutdown }

await db.graph.ensureSchema();        // 建约束与索引
await db.graph.bootstrap();           // 导入结构树
await db.graph.sync();                // 同步新抓的帖子

const info = db.visualize.info();
console.log(info.url, info.hint);

// 搜索现在是 null：
try {
  await db.search.routeIntent({ query: '随便什么' });
} catch (e) {
  // M5+ 之前一律抛 NotImplementedError
}

await db.shutdown();
```

## 目录结构

```
src/
  factory.ts            createDatabase 入口；装配 graph + search + visualize
  config.ts             parseEnv() —— 读 NEO4J_* + BBS_DATA_ROOT
  graph/
    driver.ts           Neo4j driver 句柄 + session helper
    schema.ts           约束 + 索引（ensureSchema）
    bootstrap.ts        Site → forum/sub_forum/board 的 MERGE
    sync.ts             threads + LOCATED_IN(month) 同步
    ops.ts              createDatabase 返回的 GraphOps 实现
    types.ts            BootstrapStats / SyncStats / GraphOps 类型
  sqlite/
    reader.ts           crawler 数据的只读 SQLite 读取器
  search/
    types.ts            SearchAlgorithm + RouteHit / ThreadHit / CrawlTarget
    null.ts             NullSearch —— 抛 NotImplementedError
    index.ts            createSearch 分派
  visualize/
    types.ts            VisualizeProvider + VisualizeInfo
    neo4j-browser.ts    返回 Neo4j Browser URL 的 provider
    index.ts            createVisualize 分派
  embed/
    types.ts            Embedder 接口（留给未来向量搜索）
```

## Neo4j 准备

本包**不**管理 Neo4j 进程，需要你自己跑一个。开发机最简单：

```bash
# Linux / macOS / WSL
brew install neo4j        # 或 apt install neo4j
neo4j console             # 前台运行；首次访问 http://localhost:7474 改密码
```

更详细的步骤见 `NEO4J_QUICKSTART.md`。

## 开发

```bash
npm test                  # vitest —— 34 个测试覆盖 schema、bootstrap、sync、search dispatch
npm run lint:tsc          # tsc --noEmit
npm run build             # tsc → dist/
```

v3.0 时打包是坏的（输出在 `dist/src/` 但 `package.json.main` 指向
`dist/index.js`），已在 5db21a6 修复 —— `tsconfig.json` 现在
`rootDir: "src"`、排除 scripts/tests。

## 状态

预发布。图层（bootstrap + sync + visualize）可用，搜索特意保留为
`null` —— API 先打好让 MCP 可以无条件接，真实实现等 embedding /
分类工作完成后再补。
