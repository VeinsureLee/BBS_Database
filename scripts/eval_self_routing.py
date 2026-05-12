"""Eval §6.4 (a) self-name routing and (b) entity routing.

Prints metrics; --json emits machine-readable form. Returns non-zero if thresholds not met.
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from bbs_database.builder.tokenize import Tokenizer, load_stopwords  # noqa: E402
from bbs_database.config import load_config  # noqa: E402


def _direct_scores(
    cx: sqlite3.Connection,
    query_terms: list[str],
    *,
    entity: tuple[str, str] | None = None,
    alpha_declared: float = 1.0,
    alpha_content: float = 1.5,
    alpha_entity: float = 2.0,
    alpha_activity: float = 0.1,
) -> list[tuple[int, float]]:
    if not query_terms and entity is None:
        return []
    profiles = {
        bid: (sig, act)
        for bid, sig, act in cx.execute(
            "SELECT board_node_id, content_signal_strength, activity_score FROM forum_profile"
        )
    }
    score: dict[int, float] = defaultdict(float)
    for bid, (sig, act) in profiles.items():
        score[bid] = alpha_activity * act

    if query_terms:
        placeholders = ",".join("?" * len(query_terms))
        for bid, td, tc in cx.execute(
            f"SELECT board_node_id, SUM(tfidf_declared), SUM(tfidf_content) "
            f"FROM edge_forum_topic WHERE term IN ({placeholders}) GROUP BY board_node_id",
            query_terms,
        ):
            sig = profiles[bid][0]
            score[bid] += alpha_declared * (td or 0.0) + alpha_content * (tc or 0.0) * sig

    if entity is not None:
        ent, ty = entity
        for bid, cnt in cx.execute(
            "SELECT board_node_id, thread_count FROM edge_forum_entity "
            "WHERE entity=? AND entity_type=?",
            (ent, ty),
        ):
            score[bid] += alpha_entity * math.log(1 + cnt)

    return sorted(score.items(), key=lambda x: -x[1])


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--config", required=True)
    p.add_argument("--min-top3-accuracy", type=float, default=None)
    p.add_argument("--min-entity-top5-accuracy", type=float, default=None)
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    cfg_path = Path(args.config).resolve()
    cfg = load_config(cfg_path, root=cfg_path.parent.parent)
    cx = sqlite3.connect(f"file:{cfg.index_db_path.as_posix()}?mode=ro", uri=True)
    tok = Tokenizer(stopwords=load_stopwords(cfg.build.stopwords_path),
                    min_length=cfg.build.min_token_length)

    boards = list(cx.execute("SELECT board_node_id, name FROM forum_profile"))
    n_top1 = n_top3 = 0
    misses_name: list[tuple[int, str]] = []
    for bid, name in boards:
        terms = tok.cut(name)
        if not terms:
            continue
        ranking = _direct_scores(cx, terms)
        ranked_ids = [b for b, _ in ranking]
        if ranked_ids[:1] == [bid]:
            n_top1 += 1
        if bid in ranked_ids[:3]:
            n_top3 += 1
        else:
            misses_name.append((bid, name))
    total = len(boards) or 1
    top1 = n_top1 / total
    top3 = n_top3 / total

    # (b) entity routing
    entity_rows = list(cx.execute(
        "SELECT board_node_id, entity, entity_type, thread_count FROM edge_forum_entity"
    ))
    by_entity: dict[tuple[str, str], list[tuple[int, int]]] = defaultdict(list)
    for bid, ent, ty, cnt in entity_rows:
        by_entity[(ent, ty)].append((bid, cnt))
    n_entity_total = 0
    n_entity_top5 = 0
    misses_entity: list[tuple[str, str, int]] = []
    for (ent, ty), pairs in by_entity.items():
        pairs.sort(key=lambda x: -x[1])
        target_board = pairs[0][0]
        ranking = _direct_scores(cx, [ent], entity=(ent, ty))
        ranked_ids = [b for b, _ in ranking]
        n_entity_total += 1
        if target_board in ranked_ids[:5]:
            n_entity_top5 += 1
        else:
            misses_entity.append((ent, ty, target_board))
    ent_top5 = (n_entity_top5 / n_entity_total) if n_entity_total else 1.0

    cx.close()

    metrics = {
        "boards": total,
        "self_name_top1": top1,
        "self_name_top3": top3,
        "entity_pairs": n_entity_total,
        "entity_top5": ent_top5,
        "misses_name": misses_name,
        "misses_entity": misses_entity,
    }
    if args.json:
        print(json.dumps(metrics, ensure_ascii=False))
    else:
        print(f"boards={total}")
        print(f"self-name top1={top1:.3f}  top3={top3:.3f}")
        print(f"entity pairs={n_entity_total}  top5={ent_top5:.3f}")
        if misses_name:
            print(f"misses (name): {misses_name[:10]}")
        if misses_entity:
            print(f"misses (entity): {misses_entity[:10]}")

    rc = 0
    if args.min_top3_accuracy is not None and top3 < args.min_top3_accuracy:
        print(f"FAIL: self-name top3 {top3:.3f} < {args.min_top3_accuracy:.3f}", file=sys.stderr)
        rc = 1
    if args.min_entity_top5_accuracy is not None and ent_top5 < args.min_entity_top5_accuracy:
        print(f"FAIL: entity top5 {ent_top5:.3f} < {args.min_entity_top5_accuracy:.3f}",
              file=sys.stderr)
        rc = 1
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
