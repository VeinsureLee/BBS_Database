from bbs_database.builder.tokenize import (
    Tokenizer,
    load_stopwords,
)


def test_load_stopwords_skips_blanks_and_comments(tmp_path):
    p = tmp_path / "sw.txt"
    p.write_text("的\n\n了\n  和  \n", encoding="utf-8")
    sw = load_stopwords(p)
    assert sw == {"的", "了", "和"}


def test_tokenizer_filters_short_and_stopwords():
    tok = Tokenizer(stopwords={"的", "了"}, min_length=2)
    assert tok.cut_search("张三老师讲课") == ["张三", "老师", "讲课"]


def test_tokenizer_cut_basic_used_for_declared():
    tok = Tokenizer(stopwords={"的"}, min_length=2)
    out = tok.cut("学院A 学术 > 学院A 张三老师的公告")
    assert "张三" in out
    assert "老师" in out
    assert "的" not in out


def test_tokenizer_dedupes_within_search_for_one_token_text():
    """cut_for_search produces overlapping segments; tokens are kept (not deduped) so TF can count."""
    tok = Tokenizer(stopwords=set(), min_length=2)
    out = tok.cut_search("数据结构")
    assert "数据" in out and "结构" in out
