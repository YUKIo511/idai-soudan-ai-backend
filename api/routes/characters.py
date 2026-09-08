"""偉人一覧・詳細エンドポイント。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..deps import get_indexer, run_blocking
from ..schemas import CharacterListResponse, CharacterDetail
from .. import services

router = APIRouter(tags=["characters"])


@router.get("/characters", response_model=CharacterListResponse)
async def characters_list():
    idx = get_indexer()
    items = await run_blocking(services.list_characters, idx)
    return CharacterListResponse(characters=items, total=len(items))


@router.get("/characters/{slug}", response_model=CharacterDetail)
async def character_detail(slug: str):
    idx = get_indexer()
    detail = await run_blocking(services.get_character_detail, idx, slug)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"偉人が見つかりません: {slug}")
    return detail
