"""Load routing.yaml into typed dataclasses."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass(frozen=True)
class BuildConfig:
    min_token_length: int
    stopwords_file: str
    pmi_threshold: float
    similar_top_n: int
    seed_top_terms_for_cooccur: int
    cooccur_min_df: int
    content_signal_strength_full: int
    _root: Path | None = field(default=None, repr=False, compare=False, hash=False)

    @property
    def stopwords_path(self) -> Path:
        return _resolve(self.stopwords_file, self._root)


@dataclass(frozen=True)
class EmbedConfig:
    enabled: bool = False
    provider: str = ""
    base_url: str = ""
    model: str = ""
    dimensions: int = 1024
    api_key_env: str = ""
    batch_size: int = 25
    max_input_chars: int = 2000
    max_retries: int = 3
    request_timeout_s: int = 30
    pinned_only_at_full_build: bool = True


@dataclass(frozen=True)
class Config:
    data_root: str
    index_db: str
    site_key: str
    build: BuildConfig
    routing: dict
    search: dict
    embed: EmbedConfig
    _root: Path | None = field(default=None, repr=False, compare=False, hash=False)

    @property
    def data_root_path(self) -> Path:
        return _resolve(self.data_root, self._root)

    @property
    def index_db_path(self) -> Path:
        return _resolve(self.index_db, self._root)


def _resolve(p: str, root: Path | None) -> Path:
    path = Path(p)
    if path.is_absolute() or root is None:
        return path
    return (root / path).resolve()


def load_config(path: Path, root: Path | None = None) -> Config:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    build_raw = raw["build"]
    build = BuildConfig(
        min_token_length=build_raw["min_token_length"],
        stopwords_file=build_raw["stopwords_file"],
        pmi_threshold=float(build_raw["pmi_threshold"]),
        similar_top_n=int(build_raw["similar_top_n"]),
        seed_top_terms_for_cooccur=int(build_raw["seed_top_terms_for_cooccur"]),
        cooccur_min_df=int(build_raw["cooccur_min_df"]),
        content_signal_strength_full=int(build_raw["content_signal_strength_full"]),
        _root=root,
    )
    embed_raw = raw.get("embed") or {}
    embed = EmbedConfig(
        enabled=bool(embed_raw.get("enabled", False)),
        provider=str(embed_raw.get("provider", "")),
        base_url=str(embed_raw.get("base_url", "")),
        model=str(embed_raw.get("model", "")),
        dimensions=int(embed_raw.get("dimensions", 1024)),
        api_key_env=str(embed_raw.get("api_key_env", "")),
        batch_size=int(embed_raw.get("batch_size", 25)),
        max_input_chars=int(embed_raw.get("max_input_chars", 2000)),
        max_retries=int(embed_raw.get("max_retries", 3)),
        request_timeout_s=int(embed_raw.get("request_timeout_s", 30)),
        pinned_only_at_full_build=bool(embed_raw.get("pinned_only_at_full_build", True)),
    )
    return Config(
        data_root=raw["data_root"],
        index_db=raw["index_db"],
        site_key=raw["site_key"],
        build=build,
        routing=raw.get("routing", {}) or {},
        search=raw.get("search", {}) or {},
        embed=embed,
        _root=root,
    )
