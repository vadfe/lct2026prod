import uuid

from pydantic import BaseModel


class SearchResult(BaseModel):
    product_id: uuid.UUID
    slug: str | None = None
    title: str
    manufacturer: str
    description: str
    color: str | None = None
    category: str | None = None
    region: str | None = None
    grape: str | None = None
    image_url: str
    bottle_image_url: str | None = None
    dino_similarity: float
    sift_score: float
    inliers: int
    inlier_ratio: float
    pgvector_rank: int
    final_rank: int


class SearchTimings(BaseModel):
    embedding_ms: float
    pgvector_ms: float
    sift_ms: float
    total_ms: float


class SearchResponse(BaseModel):
    winner: SearchResult | None
    results: list[SearchResult]
    timings: SearchTimings
    query_crop: str | None = None
    augmentation_applied: list[str] | None = None


class PredictResponse(BaseModel):
    slug: str | None = None
