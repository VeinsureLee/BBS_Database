from pathlib import Path

from bbs_database.config import Config, EmbedConfig, load_config


def _write(tmp_path: Path, embed_block: str = None) -> Path:
    if embed_block is None:
        embed_block = """
embed:
  enabled: true
  provider: dashscope
  base_url: https://dashscope.aliyuncs.com/compatible-mode/v1
  model: text-embedding-v3
  dimensions: 1024
  api_key_env: DASHSCOPE_API_KEY
  batch_size: 25
  max_input_chars: 2000
  max_retries: 3
  request_timeout_s: 30
  pinned_only_at_full_build: true
""".strip()
    p = tmp_path / "routing.yaml"
    p.write_text(
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
        "routing:\n"
        "  alpha_declared: 1.0\n"
        "  alpha_content: 1.5\n"
        "  alpha_entity: 2.0\n"
        "  alpha_activity: 0.1\n"
        "  k1_seeds: 5\n"
        "  seed_top_terms: 20\n"
        "  m_expansion: 10\n"
        "  beta_expansion: 0.5\n"
        "  k_final: 8\n"
        "  delta_vector_base: 0.5\n"
        "  delta_vector_cold: 0.7\n"
        "  delta_signal_threshold: 0.5\n"
        "search:\n"
        "  gamma_vector: 0.6\n"
        "  gamma_board: 0.3\n"
        "  gamma_recency: 0.1\n"
        "  recency_tau_days: 180\n"
        "  per_board_limit: 20\n"
        "  total_limit: 50\n"
        + embed_block + "\n",
        encoding="utf-8",
    )
    return p


def test_embed_config_loads(tmp_path):
    cfg = load_config(_write(tmp_path))
    assert isinstance(cfg.embed, EmbedConfig)
    assert cfg.embed.enabled is True
    assert cfg.embed.provider == "dashscope"
    assert cfg.embed.model == "text-embedding-v3"
    assert cfg.embed.dimensions == 1024
    assert cfg.embed.batch_size == 25
    assert cfg.embed.max_input_chars == 2000
    assert cfg.embed.pinned_only_at_full_build is True


def test_routing_section_includes_delta_fields(tmp_path):
    cfg = load_config(_write(tmp_path))
    assert cfg.routing["delta_vector_base"] == 0.5
    assert cfg.routing["delta_vector_cold"] == 0.7
    assert cfg.routing["delta_signal_threshold"] == 0.5


def test_search_section_includes_gamma_vector(tmp_path):
    cfg = load_config(_write(tmp_path))
    assert cfg.search["gamma_vector"] == 0.6
    assert cfg.search["gamma_board"] == 0.3
    assert cfg.search["gamma_recency"] == 0.1


def test_embed_section_missing_defaults_to_disabled(tmp_path):
    # Omit embed section entirely
    cfg = load_config(_write(tmp_path, embed_block="embed: {}"))
    assert cfg.embed.enabled is False
