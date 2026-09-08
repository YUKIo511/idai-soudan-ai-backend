"""config.yaml のロードと、環境変数によるプロバイダ上書き。"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = REPO_ROOT / "config.yaml"


@dataclass
class Settings:
    raw: dict[str, Any]
    root: Path = REPO_ROOT

    # --- paths ---
    @property
    def characters_dir(self) -> Path:
        return self.root / self.raw["paths"]["characters_dir"]

    @property
    def schemas_dir(self) -> Path:
        return self.root / self.raw["paths"]["schemas_dir"]

    @property
    def vectorstore_dir(self) -> Path:
        return self.root / self.raw["paths"].get("vectorstore_dir", ".vectorstore")

    @property
    def chroma_dir(self) -> Path:
        return self.root / self.raw["paths"].get("chroma_dir", ".chroma")

    # --- embeddings ---
    @property
    def embeddings_provider(self) -> str:
        return os.environ.get("KB_EMBEDDINGS_PROVIDER", self.raw["embeddings"]["provider"])

    def embeddings_cfg(self) -> dict[str, Any]:
        return self.raw["embeddings"].get(self.embeddings_provider, {})

    # --- vector store ---
    @property
    def vectorstore_backend(self) -> str:
        return os.environ.get("KB_VECTORSTORE_BACKEND", self.raw["vectorstore"]["backend"])

    @property
    def collection_prefix(self) -> str:
        return self.raw["vectorstore"].get("collection_prefix", "char__")

    # --- llm ---
    @property
    def llm_provider(self) -> str:
        return os.environ.get("KB_LLM_PROVIDER", self.raw["llm"]["provider"])

    def llm_cfg(self) -> dict[str, Any]:
        return self.raw["llm"].get(self.llm_provider, {})

    @property
    def llm_temperature(self) -> float:
        return float(self.raw["llm"].get("temperature", 0.7))

    @property
    def llm_max_tokens(self) -> int:
        return int(self.raw["llm"].get("max_tokens", 1200))

    @property
    def gen_temperature(self) -> float:
        """生成に使う温度。ollama は llm.ollama.temperature、cloudflare は llm.cloudflare.temperature を優先。"""
        if self.llm_provider == "ollama":
            v = self.ollama_options().get("temperature")
            if v is not None:
                return float(v)
        if self.llm_provider == "cloudflare":
            v = self.cloudflare_options().get("temperature")
            if v is not None:
                return float(v)
        return self.llm_temperature

    @property
    def gen_max_tokens(self) -> int:
        """生成トークン上限。ollama は num_predict、cloudflare は llm.cloudflare.max_tokens を優先。"""
        if self.llm_provider == "ollama":
            v = self.ollama_options().get("num_predict")
            if v is not None:
                return int(v)
        if self.llm_provider == "cloudflare":
            v = self.cloudflare_options().get("max_tokens")
            if v is not None:
                return int(v)
        return self.llm_max_tokens

    @property
    def retrieval_k(self) -> int:
        return int(self.retrieval.get("k", 6))

    @property
    def retrieval_k_complex(self) -> int:
        return int(self.retrieval.get("k_complex", self.retrieval_k + 2))

    @property
    def answer_style(self) -> str:
        """回答の作り方。advisor=偉人の思想を"参照"して助言（既定） / embody=一人称で演じる。"""
        return os.environ.get("KB_ANSWER_STYLE") or self.raw["llm"].get("answer_style", "dialogue")

    # --- Ollama（ローカル LLM）---
    def ollama_options(self) -> dict[str, Any]:
        return self.raw["llm"].get("ollama", {}) or {}

    @property
    def ollama_model(self) -> str:
        return (
            os.environ.get("KB_OLLAMA_MODEL")
            or self.ollama_options().get("model")
            or self.raw["llm"].get("model")   # フラット表記 llm.model も許容
            or "qwen3:8b"
        )

    @property
    def ollama_base_url(self) -> str:
        return (
            os.environ.get("KB_OLLAMA_BASE_URL")
            or self.ollama_options().get("base_url")
            or self.raw["llm"].get("base_url")
            or "http://localhost:11434"
        )

    # --- Cloudflare Workers AI（本番用。認証は環境変数のみ）---
    def cloudflare_options(self) -> dict[str, Any]:
        return self.raw["llm"].get("cloudflare", {}) or {}

    @property
    def cloudflare_account_id(self) -> str:
        return (
            os.environ.get("CLOUDFLARE_ACCOUNT_ID")
            or self.cloudflare_options().get("account_id")
            or ""
        )

    @property
    def cloudflare_api_token(self) -> str:
        # トークンは config.yaml に書かせない（環境変数 / .env のみ）
        return os.environ.get("CLOUDFLARE_API_TOKEN", "")

    @property
    def cloudflare_model(self) -> str:
        return (
            os.environ.get("KB_CLOUDFLARE_MODEL")
            or self.cloudflare_options().get("model")
            or "@cf/meta/llama-3.3-70b-instruct-fp8-fast"
        )

    # --- retrieval ---
    @property
    def retrieval(self) -> dict[str, Any]:
        return self.raw.get("retrieval", {})


def _load_dotenv(root: Path) -> None:
    """依存追加なしの軽量 .env ローダー。KEY=VALUE を1行ずつ os.environ へ。
    既にセット済みの変数は上書きしない（実際の環境変数が優先）。"""
    env_path = root / ".env"
    if not env_path.is_file():
        return
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val
    except OSError:
        pass


def load_settings(path: str | Path | None = None) -> Settings:
    p = Path(path) if path else DEFAULT_CONFIG_PATH
    _load_dotenv(p.resolve().parent)
    with open(p, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return Settings(raw=raw, root=p.resolve().parent)
