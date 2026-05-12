import subprocess
import sys
from pathlib import Path


def test_cli_full_builds_index(crawler_dataset, tmp_path: Path):
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
""".strip(),
        encoding="utf-8",
    )

    script = Path(__file__).resolve().parents[1] / "scripts" / "rebuild_index.py"
    res = subprocess.run(
        [sys.executable, str(script), "--full", "--config", str(cfg_path)],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, res.stderr
    assert index_db.exists()


def test_cli_rejects_incremental_in_p1(tmp_path: Path):
    script = Path(__file__).resolve().parents[1] / "scripts" / "rebuild_index.py"
    res = subprocess.run(
        [sys.executable, str(script), "--incremental"],
        capture_output=True,
        text=True,
    )
    assert res.returncode != 0
    assert "not yet supported" in (res.stderr + res.stdout).lower()
