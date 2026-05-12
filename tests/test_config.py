from pathlib import Path

from bbs_database.config import Config, load_config


def test_load_config_reads_routing_yaml(tmp_path: Path):
    cfg_file = tmp_path / "routing.yaml"
    cfg_file.write_text(
        "data_root: ./data\n"
        "index_db: ./data/index.db\n"
        "site_key: school-bbs\n"
        "build:\n"
        "  min_token_length: 2\n"
        "  stopwords_file: ./config/stopwords_zh.txt\n"
        "  pmi_threshold: 0.3\n"
        "  similar_top_n: 5\n"
        "  seed_top_terms_for_cooccur: 50\n"
        "  cooccur_min_df: 2\n"
        "  content_signal_strength_full: 200\n"
        "routing: {}\n"
        "search: {}\n",
        encoding="utf-8",
    )
    cfg = load_config(cfg_file)
    assert isinstance(cfg, Config)
    assert cfg.data_root == "./data"
    assert cfg.site_key == "school-bbs"
    assert cfg.build.pmi_threshold == 0.3
    assert cfg.build.similar_top_n == 5
    assert cfg.build.content_signal_strength_full == 200


def test_load_config_resolves_paths_relative_to_repo(tmp_path: Path):
    cfg_file = tmp_path / "routing.yaml"
    cfg_file.write_text(
        "data_root: ./data/crawler.db\n"
        "index_db: ./data/index.db\n"
        "site_key: school-bbs\n"
        "build:\n"
        "  min_token_length: 2\n"
        "  stopwords_file: ./config/stopwords_zh.txt\n"
        "  pmi_threshold: 0.3\n"
        "  similar_top_n: 5\n"
        "  seed_top_terms_for_cooccur: 50\n"
        "  cooccur_min_df: 2\n"
        "  content_signal_strength_full: 200\n"
        "routing: {}\n"
        "search: {}\n",
        encoding="utf-8",
    )
    cfg = load_config(cfg_file, root=tmp_path)
    assert cfg.data_root_path == tmp_path / "data" / "crawler.db"
    assert cfg.index_db_path == tmp_path / "data" / "index.db"
    assert cfg.build.stopwords_path == tmp_path / "config" / "stopwords_zh.txt"
