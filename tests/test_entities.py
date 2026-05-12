from bbs_database.builder.entities import extract_entities


def test_person_via_role_regex():
    out = extract_entities("张三老师怎么样")
    names = {e for (e, t) in out if t == "person"}
    assert "张三" in names


def test_person_via_jieba_nr():
    # jieba tags some bare names as nr
    out = extract_entities("找张三")
    names = {e for (e, t) in out if t == "person"}
    assert "张三" in names


def test_course_suffix_regex():
    out = extract_entities("数据结构课很难")
    courses = {e for (e, t) in out if t == "course"}
    assert "数据结构课" in courses


def test_no_false_positive_on_short_strings():
    out = extract_entities("食堂好")
    assert not any(t == "person" for (_e, t) in out)
