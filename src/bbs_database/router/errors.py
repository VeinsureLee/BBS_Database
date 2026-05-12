"""Error hierarchy for BBS_Database.

Every error carries a `code` string suitable for surfacing as a JSON-RPC
error code through MCP.
"""


class BBSDatabaseError(Exception):
    code: str = "bbs_database_error"


class IndexNotBuiltError(BBSDatabaseError):
    code = "index_not_built"


class EmptyQueryError(BBSDatabaseError):
    code = "empty_query"


class InvalidBoardError(BBSDatabaseError):
    code = "invalid_board"


class ThreadNotFoundError(BBSDatabaseError):
    code = "thread_not_found"


class ForumDbNotFoundError(BBSDatabaseError):
    code = "forum_db_not_found"


class EmbedAPIError(BBSDatabaseError):
    code = "embed_api_error"


class EmbedConfigError(BBSDatabaseError):
    code = "embed_config_error"


class VectorIndexEmptyError(BBSDatabaseError):
    code = "vector_index_empty"
