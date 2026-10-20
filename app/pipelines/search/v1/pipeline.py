import asyncio
import time
from dataclasses import dataclass
from typing import Any

from PIL import Image

from app.db.repositories.products import ProductRepository
from app.pipelines.search.v1.reranking import SiftReranker
from app.schemas.search.v1 import SearchResponse, SearchResult, SearchTimings
from app.services.embeddings import EmbeddingService
from app.services.images import ImageService


from app.pipelines.ocr.tag_scorer import TagScorer
import numpy as np
import cv2

CONFIDENCE_THRESHOLD = 0.90

@dataclass
class SearchPipelineV1:
    embeddings: EmbeddingService
    images: ImageService
    reranker: SiftReranker
    gpu_semaphore: asyncio.Semaphore
    sift_semaphore: asyncio.Semaphore
    candidate_pool_size: int
    ocr_decoder: Any = None
    dewarp_engine: Any = None

    async def run(
        self,
        image: Image.Image,
        repository: ProductRepository,
        k: int,
        query_crop: str | None = None,
        secondary_crops_b64: list[str] | None = None,
        secondary_crop_images: list[Image.Image] | None = None,
        augmentation_applied: list[str] | None = None,
    ) -> SearchResponse:
        started = time.perf_counter()
        async with self.gpu_semaphore:
            embedding_started = time.perf_counter()
            embedding = await asyncio.to_thread(self.embeddings.embed, image)
            embedding_ms = self._elapsed(embedding_started)
        database_started = time.perf_counter()
        candidates = await repository.nearest(embedding, max(k, self.candidate_pool_size))
        pgvector_ms = self._elapsed(database_started)
        sift_started = time.perf_counter()

        async def score(rank: int, candidate):
            try:
                path = self.images.resolve(candidate.image_path)
                candidate_image = await asyncio.to_thread(self._open_image, path)
                similarity = 1.0 - candidate.distance
                async with self.sift_semaphore:
                    sift = await asyncio.to_thread(self.reranker.compare, image, candidate_image, similarity)
                return rank, candidate.product, similarity, sift, candidate.image_path
            except (FileNotFoundError, OSError):
                return None

        scored = [item for item in await asyncio.gather(*(score(rank, candidate) for rank, candidate in enumerate(candidates, 1))) if item]
        scored.sort(key=lambda item: (-item[3].score, item[0]))
        sift_ms = self._elapsed(sift_started)
        results = []
        for rank, item in enumerate(scored[:k], 1):
            product = item[1]
            dino_sim = item[2]
            sift_score = item[3].score
            inliers = item[3].inliers
            inlier_ratio = item[3].inlier_ratio
            img_path = item[4]
            
            base_conf = round(min(0.99, max(0.01, 0.5 * dino_sim + 0.5 * min(1.0, sift_score / 0.8) if inliers >= 8 else dino_sim)), 3)
            final_conf = base_conf
            ocr_tags_dict = None
            
            if self.ocr_decoder:
                try:
                    # Convert PIL Image to OpenCV BGR for OCR
                    cv_image = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
                    ocr_res = await asyncio.to_thread(self.ocr_decoder.process, cv_image)
                    full_text = ocr_res.get("full_text", "")
                    
                    if secondary_crop_images:
                        for sec_img in secondary_crop_images:
                            sec_cv = cv2.cvtColor(np.array(sec_img), cv2.COLOR_RGB2BGR)
                            sec_res = await asyncio.to_thread(self.ocr_decoder.process, sec_cv)
                            full_text += " " + sec_res.get("full_text", "")
                            
                    
                    scorer = TagScorer()
                    bundle = scorer.extract_bundle(full_text)
                    tag_score = scorer.score_candidate(bundle, product)
                    tag_norm = min(tag_score / 11.5, 1.0)
                    
                    # OCR based confidence (percentage of matched tags)
                    ocr_conf = round(tag_norm, 3)
                    
                    # Если визуально похоже, но OCR явно прочитал другой текст (штрафуем)
                    if base_conf > 0.80 and ocr_conf < 0.3 and len(full_text.strip()) > 5:
                        final_conf = base_conf * 0.5
                    else:
                        final_conf = max(base_conf, ocr_conf)

                    # --- DEWARPING FALLBACK ---
                    if final_conf < 0.95 and self.dewarp_engine:
                        print(f"[PIPELINE] Confidence {final_conf} < 0.95. Triggering Dewarp Engine...")
                        try:
                            dewarp_res = await asyncio.to_thread(self.dewarp_engine.process_image, cv_image)
                            full_text = dewarp_res.get("full_text", full_text)
                            
                            if secondary_crop_images:
                                for sec_img in secondary_crop_images:
                                    sec_cv = cv2.cvtColor(np.array(sec_img), cv2.COLOR_RGB2BGR)
                                    sec_dewarp_res = await asyncio.to_thread(self.dewarp_engine.process_image, sec_cv)
                                    full_text += " " + sec_dewarp_res.get("full_text", "")
                                    
                            bundle = scorer.extract_bundle(full_text)
                            tag_score = scorer.score_candidate(bundle, product)
                            tag_norm = min(tag_score / 11.5, 1.0)
                            ocr_conf = round(tag_norm, 3)
                            
                            if base_conf > 0.80 and ocr_conf < 0.3 and len(full_text.strip()) > 5:
                                final_conf = base_conf * 0.5
                            else:
                                final_conf = max(base_conf, ocr_conf)
                            print(f"[PIPELINE] After Dewarping: New Tag Score: {tag_score}, Final: {final_conf}")
                        except Exception as dewarp_e:
                            print(f"[PIPELINE] Dewarp error: {dewarp_e}")

                    ocr_tags_dict = {
                        "full_text": full_text,
                        "tag_score": tag_score,
                        "bundle": bundle.__dict__
                    }
                    print(f"[OCR BOOST] Base: {base_conf}, Tag Score: {tag_score}, Tag Norm: {tag_norm}, Final: {final_conf}", flush=True)
                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    print(f"[OCR BOOST ERROR] {e}", flush=True)
            
            # --- STRICT 35% THRESHOLD ---
            if final_conf < 0.35:
                print(f"[PIPELINE] Rejecting candidate {product.title} because final_conf {final_conf} < 0.35")
                continue
            
            results.append(SearchResult(
                product_id=product.id,
                slug=product.slug,
                title=product.title,
                manufacturer=product.manufacturer,
                description=product.description,
                color=product.color,
                category=product.category,
                region=product.region,
                grape=product.grape,
                image_url=f"/api/media/{img_path}",
                bottle_image_url=f"/api/media/{product.source_image_path}" if product.source_image_path else None,
                dino_similarity=dino_sim,
                sift_score=sift_score,
                inliers=inliers,
                inlier_ratio=inlier_ratio,
                pgvector_rank=item[0],
                final_rank=rank,
                confidence=final_conf,
                ocr_tags=ocr_tags_dict
            ))
        timings = SearchTimings(embedding_ms=embedding_ms, pgvector_ms=pgvector_ms, sift_ms=sift_ms, total_ms=self._elapsed(started))
        return SearchResponse(
            winner=results[0] if results else None,
            results=results,
            timings=timings,
            query_crop=query_crop,
            secondary_crops=secondary_crops_b64,
            augmentation_applied=augmentation_applied,
        )

    @staticmethod
    def _open_image(path) -> Image.Image:
        with Image.open(path) as image:
            return image.convert("RGB")

    @staticmethod
    def _elapsed(started: float) -> float:
        return round((time.perf_counter() - started) * 1000, 2)
