from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, Field

from app.sommelier.card.catalog import SLUG_PATTERN


class ToastRequest(BaseModel):
    occasion: Annotated[str, Field(max_length=40)] = "friends"
    question: Annotated[str, Field(max_length=300)] = ""
    wine_slug: Annotated[str, Field(max_length=300, pattern=SLUG_PATTERN.pattern)]


class MissingWineRecord(BaseModel):
    id: str
    timestamp: str
    source: str
    query_text: str
    image_url: str
    confidence: float | None
    status: str
    admin_notes: str


class MissingWineDashboard(BaseModel):
    total: int
    pending: int
    in_progress: int
    resolved: int
    sources: dict[str, int]
    records: list[MissingWineRecord]


class MissingWineStatusRequest(BaseModel):
    status: str = Field(pattern="^(pending|in_progress|resolved)$")
    admin_notes: Annotated[str, Field(max_length=1000)] = ""
