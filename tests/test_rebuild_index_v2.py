import subprocess
import sqlite3
import sys
from pathlib import Path


def test_cli_no_embed_skips_vector_phase(crawler_dataset, tmp_path):
    sw = tmp_path / "sw.txt"
    sw.write_text("\n", encoding="utf-8")
    index_db = tmp_path / "index.db"
    cfg_path = tmp_path / "routing.yaml"
    cfg_path.write_text(
        f"""
data_root: {crawler_dataset['root'].as_posix()}
index_db: {index_db.as_posix()}
site_key: school-bbs
build:
  min_token_length: 2
  stopwords_file: {sw.as_posix()}
  pmi_threshold: -1.0
  similar_top_n: 5
  seed_top_terms_for_cooccur: 20
  cooccur_min_df: 2
  content_signal_strength_full: 5
routing: {{}}
search: {{}}
embed:
  enabled: true
  provider: dashscope
  base_url: https://example.test/v1
  model: text-embedding-v3
  dimensions: 1024
  api_key_env: TEST_KEY
  batch_size: 25
  max_input_chars: 2000
  max_retries: 3
  request_timeout_s: 30
  pinned_only_at_full_build: true
""".strip(),
        encoding="utf-8",
    )
    script = Path(__file__).resolve().parents[1] / "scripts" / "rebuild_index.py"
    res = subprocess.run(
        [sys.executable, str(script), "--full", "--no-embed", "--config", str(cfg_path)],
        capture_output=True, text=True,
    )
    assert res.returncode == 0, res.stderr
    cx = sqlite3.connect(index_db)
    try:
        bv = cx.execute("SELECT count(*) FROM board_vector").fetchone()[0]
        assert bv == 0
        fp = cx.execute("SELECT count(*) FROM forum_profile").fetchone()[0]
        assert fp == 3
    finally:
        cx.close()
