"""DDL for index.db — Single source of truth for the build schema."""

SCHEMA_VERSION = "1.0.0"
ALGORITHM_VERSION = "1.0.0"

DDL_META = """
CREATE TABLE _meta (
  key    TEXT PRIMARY KEY,
  value  TEXT NOT NULL
)
"""

DDL_FORUM_PROFILE = """
CREATE TABLE forum_profile (
  board_node_id            INTEGER PRIMARY KEY,
  site_key                 TEXT NOT NULL,
  forum_db_file            TEXT NOT NULL,
  name                     TEXT NOT NULL,
  path                     TEXT NOT NULL,
  pinned_titles            TEXT,
  title_count              INTEGER NOT NULL,
  activity_score           REAL NOT NULL,
  content_signal_strength  REAL NOT NULL,
  vector_norm              REAL NOT NULL,
  built_at                 TEXT NOT NULL
)
"""

DDL_FORUM_PROFILE_IDX = "CREATE INDEX idx_profile_site ON forum_profile(site_key)"

DDL_EDGE_FORUM_TOPIC = """
CREATE TABLE edge_forum_topic (
  board_node_id    INTEGER NOT NULL,
  term             TEXT NOT NULL,
  tfidf_declared   REAL NOT NULL DEFAULT 0.0,
  tfidf_content    REAL NOT NULL DEFAULT 0.0,
  source           TEXT NOT NULL,
  PRIMARY KEY (board_node_id, term)
)
"""

DDL_EDGE_FORUM_TOPIC_IDX = "CREATE INDEX idx_eft_term ON edge_forum_topic(term)"

DDL_EDGE_FORUM_ENTITY = """
CREATE TABLE edge_forum_entity (
  board_node_id    INTEGER NOT NULL,
  entity           TEXT NOT NULL,
  entity_type      TEXT NOT NULL,
  thread_count     INTEGER NOT NULL,
  PRIMARY KEY (board_node_id, entity, entity_type)
)
"""

DDL_EDGE_FORUM_ENTITY_IDX = "CREATE INDEX idx_efe_entity ON edge_forum_entity(entity)"

DDL_EDGE_TOPIC_COOCCUR = """
CREATE TABLE edge_topic_cooccur (
  term_a   TEXT NOT NULL,
  term_b   TEXT NOT NULL,
  weight   REAL NOT NULL,
  PRIMARY KEY (term_a, term_b),
  CHECK (term_a < term_b)
)
"""

DDL_EDGE_TOPIC_COOCCUR_IDX_A = "CREATE INDEX idx_etc_a ON edge_topic_cooccur(term_a)"
DDL_EDGE_TOPIC_COOCCUR_IDX_B = "CREATE INDEX idx_etc_b ON edge_topic_cooccur(term_b)"

DDL_EDGE_FORUM_SIMILAR = """
CREATE TABLE edge_forum_similar (
  board_a   INTEGER NOT NULL,
  board_b   INTEGER NOT NULL,
  cosine    REAL NOT NULL,
  PRIMARY KEY (board_a, board_b)
)
"""

DDL_FTS = """
CREATE VIRTUAL TABLE thread_title_fts USING fts5(
  title, content=''
)
"""

DDL_FTS_MAP = """
CREATE TABLE fts_map (
  rowid          INTEGER PRIMARY KEY,
  board_node_id  INTEGER NOT NULL,
  thread_id      INTEGER NOT NULL,
  forum_db_file  TEXT NOT NULL
)
"""

DDL_FTS_MAP_IDX = "CREATE INDEX idx_fts_map_board ON fts_map(board_node_id)"

ALL_DDL = [
    DDL_META,
    DDL_FORUM_PROFILE,
    DDL_FORUM_PROFILE_IDX,
    DDL_EDGE_FORUM_TOPIC,
    DDL_EDGE_FORUM_TOPIC_IDX,
    DDL_EDGE_FORUM_ENTITY,
    DDL_EDGE_FORUM_ENTITY_IDX,
    DDL_EDGE_TOPIC_COOCCUR,
    DDL_EDGE_TOPIC_COOCCUR_IDX_A,
    DDL_EDGE_TOPIC_COOCCUR_IDX_B,
    DDL_EDGE_FORUM_SIMILAR,
    DDL_FTS,
    DDL_FTS_MAP,
    DDL_FTS_MAP_IDX,
]


def meta_inserts(built_at: str) -> list[tuple[str, tuple]]:
    return [
        ("INSERT INTO _meta(key, value) VALUES (?, ?)", ("schema_version", SCHEMA_VERSION)),
        ("INSERT INTO _meta(key, value) VALUES (?, ?)", ("algorithm_version", ALGORITHM_VERSION)),
        ("INSERT INTO _meta(key, value) VALUES (?, ?)", ("built_at", built_at)),
    ]


