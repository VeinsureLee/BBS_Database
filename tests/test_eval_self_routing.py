import json
import subprocess
import sys
from pathlib import Path


def _build_index(crawler_dataset, tmp_path):
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
    r = subprocess.run(
        [sys.executable, str(script), "--full", "--config", str(cfg_path)],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    return cfg_path


def test_eval_self_routing_runs_and_emits_metrics(crawler_dataset, tmp_path: Path):
    cfg_path = _build_index(crawler_dataset, tmp_path)
    script = Path(__file__).resolve().parents[1] / "scripts" / "eval_self_routing.py"
    r = subprocess.run(
        [sys.executable, str(script), "--config", str(cfg_path), "--json"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    payload = json.loads(r.stdout)
    assert "self_name_top1" in payload
    assert "self_name_top3" in payload
    assert "entity_top5" in payload
    # synthetic data is tiny, but board names mostly unique → top-3 hits hard
    assert payload["self_name_top3"] >= 0.6


def test_eval_self_routing_threshold_flag_fails_when_below(crawler_dataset, tmp_path: Path):
    cfg_path = _build_index(crawler_dataset, tmp_path)
    script = Path(__file__).resolve().parents[1] / "scripts" / "eval_self_routing.py"
    r = subprocess.run(
        [sys.executable, str(script), "--config", str(cfg_path), "--min-top3-accuracy", "1.5"],
        capture_output=True, text=True,
    )
    assert r.returncode != 0
