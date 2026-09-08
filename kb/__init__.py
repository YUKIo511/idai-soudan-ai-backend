"""偉人相談AI — Knowledge Base / RAG パイプライン。

Source of Truth は characters/<slug>/*.json。
このパッケージは JSON を読み、チャンク化し、Embedding して Vector Store に載せ、
相談文に対して関連 Knowledge を検索し、偉人の人格・思想を適用して回答を生成する。
"""

__all__ = ["config", "models", "indexer", "chunker", "build", "embed", "retrieve", "answer"]
