"""API の入出力 DTO（kb.models とは分離。フロントに渡す形だけを定義）。"""
from __future__ import annotations

from pydantic import BaseModel, Field


# ---------- 偉人一覧 ----------
class CharacterSummary(BaseModel):
    slug: str
    name: str                      # 表示名（日本語優先）
    name_en: str | None = None
    icon: str                      # 絵文字（portrait 未設定時のフォールバック）
    portrait: str | None = None    # 画像 URL（manifest.portrait があれば）
    occupation: str = ""           # 代表職業
    categories: list[str] = []     # カテゴリー（manifest.tags）
    one_line: str = ""             # 短い説明
    era: str = ""
    birth_year: str | None = None
    death_year: str | None = None
    status: str = "draft"
    knowledge_count: int = 0       # Vector Store 登録チャンク数（0 は未ビルド）


class CharacterListResponse(BaseModel):
    characters: list[CharacterSummary]
    total: int


# ---------- 偉人詳細 ----------
class TimelineItem(BaseModel):
    year: str | None = None
    age: int | None = None
    title: str
    summary: str = ""


class AchievementItem(BaseModel):
    title: str
    summary: str = ""
    year: str | None = None


class PhilosophyItem(BaseModel):
    domain: str
    title: str = ""
    view: str = ""


class QuoteItem(BaseModel):
    text: str
    original: str | None = None
    context: str = ""
    attribution_status: str
    source_ids: list[str] = []


class CharacterDetail(CharacterSummary):
    intro: str = ""                # 人物紹介（profile.summary）
    real_name: str | None = None
    nationality: list[str] = []
    titles: list[str] = []
    speaking_style_note: str = ""
    timeline: list[TimelineItem] = []
    achievements: list[AchievementItem] = []
    philosophy: list[PhilosophyItem] = []
    quotes: list[QuoteItem] = []   # 本人発言と確認/推定できるもののみ
    sources_count: int = 0


# ---------- 相談 ----------
class ConsultTurn(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str = Field(min_length=1, max_length=4000)


class ConsultRequest(BaseModel):
    character: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1, max_length=2000)
    history: list[ConsultTurn] | None = None   # 予約（現状は未使用でも受け付ける）


class KnowledgeCitation(BaseModel):
    """回答生成に使った Knowledge の要約（本文全文は返さない）。"""
    id: str
    type: str
    title: str
    reliability: str
    attribution_status: str | None = None
    authenticity: str | None = None
    disputed: bool = False
    source_ids: list[str] = []
    ref: str                        # 例: quotes.json#/quotes/3
    excerpt: str = ""               # 短い抜粋（透明性のため）


class ConsultResponse(BaseModel):
    character: str
    answer: str
    knowledge: list[KnowledgeCitation]
    llm_provider: str
    llm_model: str
    disclaimer: str


class HealthResponse(BaseModel):
    status: str
    embeddings: str
    vectorstore: str
    llm: str
    characters: int
