from bbs_database.router.errors import (
    BBSDatabaseError,
    IndexNotBuiltError,
    EmptyQueryError,
    InvalidBoardError,
    ThreadNotFoundError,
    ForumDbNotFoundError,
    EmbedAPIError,
    EmbedConfigError,
    VectorIndexEmptyError,
)


def test_all_errors_inherit_from_base():
    for cls in [IndexNotBuiltError, EmptyQueryError, InvalidBoardError,
                ThreadNotFoundError, ForumDbNotFoundError, EmbedAPIError,
                EmbedConfigError, VectorIndexEmptyError]:
        assert issubclass(cls, BBSDatabaseError)


def test_each_error_has_unique_code():
    codes = {
        IndexNotBuiltError.code,
        EmptyQueryError.code,
        InvalidBoardError.code,
        ThreadNotFoundError.code,
        ForumDbNotFoundError.code,
        EmbedAPIError.code,
        EmbedConfigError.code,
        VectorIndexEmptyError.code,
    }
    assert len(codes) == 8
    assert "" not in codes


def test_embed_client_imports_from_router_errors():
    # Confirms there's only one source of truth for these classes
    from bbs_database.embed import client as ec
    from bbs_database.router import errors as re
    assert ec.EmbedAPIError is re.EmbedAPIError
    assert ec.EmbedConfigError is re.EmbedConfigError
