# Neo4j 零基础上手指南(BBS 论坛结构可视化)

> 这份文档假设你**完全没用过 Neo4j**,也**没写过 Cypher**。
> 跟着步骤走一遍,你就能在浏览器里看到完整的 BBS 论坛结构图。

---

## 0. Neo4j 是什么,为什么用它

| 概念 | 对应到你已经懂的东西 |
|---|---|
| **Neo4j** | 一种数据库,但存的不是表,而是"节点(点)+ 关系(边)"。论坛的"讨论区 → 版面 → 帖子"这种树状/网状结构存进去天然合适。 |
| **节点 (Node)** | 一个圆圈。代表一个东西。比如一个版面、一个帖子。 |
| **标签 (Label)** | 节点的类型,写法是 `:Forum` / `:Board` / `:Thread`,一个节点可以有多个标签。 |
| **属性 (Property)** | 节点身上挂的键值对,比如 `name="灌水版"`、`url="..."`。 |
| **关系 (Relationship)** | 两个节点之间的有向箭头,比如 `(讨论区)-[:HAS_CHILD]->(版面)`。 |
| **Cypher** | Neo4j 的查询语言,可以理解为"图版本的 SQL"。`MATCH` 类似 `SELECT`,模式像 ASCII 画的图。 |
| **Neo4j Browser** | 浏览器里的可视化界面,跑在 `http://localhost:7474`。**你 99% 的时间都在这里点点点 + 偶尔粘贴一条 Cypher。** |

---

## 1. 启动 Neo4j

前提:你已经从 https://neo4j.com/download-center/ 下载 Neo4j Community Server 并解压(本指南假设解压在 `D:\Neo4j\neo4j-community-2025.12.1\`,实际路径以你为准)。Neo4j 2025 需要 **JDK 21+**,没装就先去装一个。

### 1.1 启动(开一个**新** PowerShell 窗口,**别关**)

```powershell
D:\Neo4j\neo4j-community-2025.12.1\bin\neo4j.bat console
```

`console` 表示前台运行,这个窗口会一直滚日志。看到:

```
Bolt enabled on localhost:7687
Remote interface available at http://localhost:7474/
```

就算起来了。要停:在这个窗口按 `Ctrl+C`。

### 1.2 首次登录改密码

浏览器打开 `http://localhost:7474`,用户名 `neo4j`、密码 `neo4j`(出厂默认),会强制改密。改成你想要的任何密码。

然后到 [BBS_Database/.env](.env)(不存在就 `copy .env.example .env`),把 `NEO4J_PASSWORD=` 那行改成你刚设的密码,保存。

### 1.3 想后台开机自启(可选,以后再做)

管理员 PowerShell 跑:

```powershell
D:\Neo4j\neo4j-community-2025.12.1\bin\neo4j.bat windows-service install
Start-Service neo4j
```

注册成 Windows 服务后下次开机自起,不用再开 console 窗口。

---

## 2. 把 BBS 数据灌进去

```powershell
cd d:\MyProject\BBS_Agent_Project\BBS_MCP\BBS_Database
npm run visualize
```

这会做三件事:
1. **ensureSchema** — 建好约束(`Site.key` 唯一、`Forum.node_id` 唯一、`Thread.url` 唯一 等)和索引。
2. **bootstrapStructure** — 读 `data/crawler.db/structure.db`,把站点 → 讨论区 → 子讨论区 → 版面这棵树镜像到图里,边都用 `:HAS_CHILD`。
3. **syncAllThreads** — 遍历所有 `data/crawler.db/forums/**/*.db`,把每条 thread 当成 `:Thread` 节点写进去,并连一条 `:LOCATED_IN` 边到所属 Board。

跑完会打印一份汇总:

```
graph summary: {
  Site: 1, Forum: 10, SubForum: 10, Board: 259, Thread: 7750,
  HAS_CHILD: 279, LOCATED_IN: 7750
}
```

**这一步是幂等的**——再跑一次只会更新属性,不会重复建节点/边。想清空重来:`npm run reset`,然后再 `npm run visualize`。

---

## 3. 在 Neo4j Browser 里看图(零 Cypher 经验向)

> Neo4j Browser 长这样:**最上面一条输入框**(贴 Cypher,按 Ctrl+Enter 执行)、**左边一条工具栏**(数据库面板、设置)、**中间大块**是结果展示区。

### 3.1 先点两下让 Browser 自带的"概览"出来

左侧工具栏点最上面那个数据库图标 (Database)。会看到:
- **Node labels**: `Site`, `Forum`, `SubForum`, `Board`, `Thread`
- **Relationship types**: `HAS_CHILD`, `LOCATED_IN`
- **Property keys**: 我们写进去的字段

**点任意一个 label**(比如 `Forum`),Browser 自动跑 `MATCH (n:Forum) RETURN n LIMIT 25`,中间出现 10 个圆圈,鼠标悬停能看到名字。

### 3.2 把图从"只看节点"切到"看完整树"

```cypher
MATCH (s:Site)-[:HAS_CHILD]->(f:Forum)
RETURN s, f
```

结果:1 个根节点("论坛")连出 10 条边到 10 个讨论区。可以拖动节点。点节点会高亮属性。

### 3.3 看一整棵子树(以"信息社会"为例)

```cypher
MATCH path = (f:Forum {name: '信息社会'})-[:HAS_CHILD*0..3]->(n)
RETURN path
```

`-[:HAS_CHILD*0..3]->` 的意思是"沿 HAS_CHILD 走 0 到 3 步"——一口气把信息社会下面所有层都画出来。**这就是"讨论区 / 子讨论区 / 版面"的完整可视化。**

换名字看其它讨论区:`本站站务` / `北邮校园` / `学术科技` / `人文艺术` / `生活时尚` / `休闲娱乐` / `体育健身` / `游戏对战` / `乡亲乡爱`。

### 3.4 看某个版面下的帖子

```cypher
MATCH (b:Board)<-[:LOCATED_IN]-(t:Thread)
WHERE b.name = '意见与建议'
RETURN b, t
LIMIT 50
```

### 3.5 一条 Cypher 看到"根 → 讨论区 → 子讨论区 → 版面 → 帖子"全连

```cypher
MATCH path = (s:Site)-[:HAS_CHILD*1..3]->(b:Board)<-[:LOCATED_IN]-(t:Thread)
WHERE b.name = '意见与建议'
RETURN path
LIMIT 25
```

### 3.6 调整可视化样式(让节点上显示名字)

点节点时,左下角弹出属性面板,有个 "caption" 按钮(三横线那种),可以把节点上显示的字段从 `<id>` 换成 `name` / `title`。**强烈建议设一下**:

- `:Site` → 显示 `name`
- `:Forum` / `:SubForum` / `:Board` → 显示 `name`
- `:Thread` → 显示 `title`

设置一次会记住。

---

## 4. 实用 Cypher 速查

### 4.1 数量统计

```cypher
MATCH (n:Board)  RETURN count(n);
MATCH (n:Thread) RETURN count(n);
MATCH ()-[r:LOCATED_IN]->() RETURN count(r);
```

### 4.2 哪几个版面帖子最多

```cypher
MATCH (b:Board)<-[:LOCATED_IN]-(t:Thread)
RETURN b.name AS board, count(t) AS n
ORDER BY n DESC LIMIT 20
```

### 4.3 看置顶帖

```cypher
MATCH (t:Thread {is_pinned: true})-[:LOCATED_IN]->(b:Board)
RETURN b.name, t.title, t.author
LIMIT 30
```

### 4.4 找标题含某关键词的帖子

```cypher
MATCH (t:Thread)
WHERE t.title CONTAINS '北邮'
RETURN t.title, t.url
LIMIT 30
```

### 4.5 一个帖子的完整"物理路径"(回溯到根)

```cypher
MATCH path = (s:Site)-[:HAS_CHILD*]->(b:Board)<-[:LOCATED_IN]-(t:Thread)
WHERE t.title CONTAINS '北邮'
RETURN [n IN nodes(path) | coalesce(n.name, n.title)] AS chain
LIMIT 5
```

---

## 5. Cypher 30 秒入门(看完就能改上面的查询)

```
MATCH    (n:Label {prop: value})-[:REL_TYPE]->(m)   WHERE m.x > 1   RETURN n, m
  ↑                ↑                  ↑
"找这种模式"   "节点+标签+属性筛选"   "边的类型,可加方向"
```

- 圆括号 `()` 是节点,方括号 `[]` 是关系,`{}` 内是属性筛选,`-->` / `<--` / `--` 表示方向。
- `MATCH` 找,`WHERE` 过滤,`RETURN` 输出。
- `*0..3` 表示这条边走 0 到 3 步(广度可控)。
- `MERGE` 是"有就拿,没有就建"——代码里 bootstrap/sync 全在用它,这保证脚本反复跑也不会重复建数据。
- `OPTIONAL MATCH` 允许某段模式匹配不到也不报空。

---

## 6. 出问题时

| 现象 | 原因 | 怎么办 |
|---|---|---|
| `http://localhost:7474` 打不开 | Neo4j 没启动 | 确认 `neo4j.bat console` 窗口还在、日志最后一行有 "Started." |
| 登录页报 "Failed to establish connection" | Bolt 端口没就绪 / 端口冲突 | 看 Neo4j 日志里出现 "Bolt enabled on localhost:7687" 才算就绪;`netstat -ano \| findstr :7687` 看端口占用 |
| `npm run visualize` 报 `Neo.ClientError.Security.Unauthorized` | 密码不对 | [BBS_Database/.env](.env) 里 `NEO4J_PASSWORD=` 写你实际的密码 |
| 改完 `.env` 还是连不上 | 文件名错 | 必须叫 `.env`(不是 `.env.example`),保存在 `BBS_Database/` 下,`dotenv` 自动加载 |
| 图里一团乱看不清 | 节点太多 | 加 `LIMIT 50`,或者用更窄的 `WHERE` 条件 |
| 想清空图重灌 | — | `npm run reset` 然后 `npm run visualize`(只清 Neo4j 里的图,不动安装) |
| Neo4j 起不来,报 Java 找不到 | 没装 Java 或 Java 版本太低 | 装 JDK 21+,Neo4j 2025 要 Java 21 |
| 想完全清掉数据库 | 想干净重装 | 停掉 console,删 `D:\Neo4j\neo4j-community-2025.12.1\data\` 目录,再启动 |

---

## 7. 下一步(等你玩明白当前可视化)

按 `BBS_Database/docs/design.md §13` 的分期:
- **Phase 1–2(本指南)**:物理结构 + Thread + `:LOCATED_IN`。已完成。
- **Phase 3**:加 StubEmbedder + `:MEANS` 边(语义归属)。
- **Phase 4**:把这些查询包成 MCP 工具,接 Claude / agent。

到 Phase 3 时,图里同一条 Thread 会有两组边:
- `:LOCATED_IN`(物理):它实际在哪个版。
- `:MEANS`(语义):它"应该"出现在哪几个版。

那时候用 Cypher 同时画两种边、对比,会很直观。
