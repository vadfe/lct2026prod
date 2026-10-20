import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import get_settings
from app.db.session import create_engine_and_session_factory
from app.pipelines.search.v1.pipeline import SearchPipelineV1
from app.pipelines.search.v1.reranking import SiftReranker
from app.services.batch_import import BatchImportService
from app.services.detector import DetectorService
from app.services.embeddings import EmbeddingService
from app.services.images import ImageService
from app.services.product_ingestion import ProductIngestionService
from app.services.sommelier_service import SommelierService
from app.sommelier.llm import GeminiLLM
from app.sommelier.pairing import build_pairing_service
from app.sommelier.pairing.catalog import RetailConfig
from app.sommelier.pairing.llm_layer import make_llm_client

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    engine, session_factory = create_engine_and_session_factory(settings.database_url)
    images = ImageService(settings.media_dir, settings.canonical_size, settings.max_upload_bytes, settings.max_image_pixels)
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.images = images
    app.state.detector = None
    app.state.pipeline_v1 = None
    app.state.ingestion = None
    app.state.batch_import = None
    app.state.import_tasks = set()
    app.state.sommelier = None
    app.state.sommelier_pairing = None
    app.state.wine_card = None
    app.state.missing_wines = None
    try:
        from app.services.wine_card_service import WineCardService
        from app.services.missing_wines_service import MissingWinesService

        app.state.wine_card = await asyncio.to_thread(WineCardService, settings.resolved_sommelier_csv_path)
        app.state.missing_wines = MissingWinesService(settings.media_dir)
        logger.info("WineCard service loaded: %d wines; MissingWines service ready", len(app.state.wine_card.wines))
    except Exception:
        logger.exception("WineCard or MissingWines service failed to load")

    try:
        sommelier_llm = None
        if settings.google_api_key and settings.google_api_key.get_secret_value():
            sommelier_llm = GeminiLLM(settings.google_api_key.get_secret_value(), settings.sommelier_llm_model, settings.sommelier_llm_timeout_seconds)
        sommelier_service = await asyncio.to_thread(
            SommelierService,
            settings.resolved_sommelier_csv_path,
            settings.resolved_sommelier_feedback_path,
            settings.sommelier_max_sessions,
            settings.sommelier_session_ttl_seconds,
            sommelier_llm,
        )
        app.state.sommelier = sommelier_service
        logger.info("Sommelier catalog loaded: %d wines; LLM layer: %s", len(sommelier_service.wines),
                    settings.sommelier_llm_model if sommelier_llm else "off (templates only)")
    except Exception:
        logger.exception("Sommelier service failed to load")
    try:
        recognition = {w["id"]: w for w in app.state.sommelier.wines}.get if app.state.sommelier is not None else None
        api_key = settings.google_api_key.get_secret_value() if settings.google_api_key else None
        pairing_llm = make_llm_client(settings.sommelier_llm_provider, api_key, settings.sommelier_llm_model, settings.sommelier_llm_timeout_seconds)
        retail = RetailConfig(kind=settings.retail_source_kind, url=settings.retail_source_url, schedule=settings.retail_refresh_cron,
                              api_key=settings.retail_api_key.get_secret_value() if settings.retail_api_key else "")
        service_wines = app.state.sommelier.wines if app.state.sommelier is not None else None
        app.state.sommelier_pairing = await asyncio.to_thread(
            build_pairing_service, settings.catalog_source, pairing_llm, str(settings.resolved_sommelier_llm_log_path), recognition,
            retail, None, service_wines,
        )
        logger.info("Sommelier pairing loaded: catalog=%s (Russian wines only), LLM=%s", settings.catalog_source,
                    pairing_llm.name if pairing_llm else "off (templates)")
    except Exception:
        logger.exception("Sommelier pairing failed to load")

    try:
        from app.pipelines.ocr.stage5_ocr import Stage5OCRDecoder
        ocr_decoder, detector, embeddings = await asyncio.gather(
            asyncio.to_thread(Stage5OCRDecoder),
            asyncio.to_thread(DetectorService, settings.yolo_model_path, settings.yolo_confidence),
            asyncio.to_thread(EmbeddingService, settings.dino_model_path, settings.dino_base_model_path, settings.embedding_dimension),
        )
        app.state.ocr_decoder = ocr_decoder
        # Populate dynamic vocabulary from DB
        try:
            from sqlalchemy.ext.asyncio import AsyncSession
            from sqlalchemy import select
            from app.db.models.product import Product
            logger.info("Populating dynamic OCR vocabulary from database...")
            async with session_factory() as session:
                result = await session.execute(select(Product.title, Product.slug, Product.manufacturer, Product.description, Product.grape, Product.region, Product.color))
                words_to_add = set()
                for row in result:
                    for field in row:
                        if field:
                            # Basic tokenization
                            tokens = str(field).replace('-', ' ').replace(',', ' ').split()
                            words_to_add.update(tokens)
                if ocr_decoder and hasattr(ocr_decoder, 'lexicon_corrector'):
                    ocr_decoder.lexicon_corrector.update_vocabulary(list(words_to_add))
            logger.info(f"Dynamically added {len(words_to_add)} words to OCR lexicon.")
        except Exception as e:
            logger.error(f"Failed to populate dynamic vocabulary: {e}")
            
        app.state.detector = detector
        
        try:
            from app.pipelines.dewarp.dewarp_engine import CylindricalDewarpEngine
            dewarp_engine = await asyncio.to_thread(
                CylindricalDewarpEngine, 
                use_gpu=True, 
                external_ocr=ocr_decoder, 
                yolo_model_path=str(settings.yolo_model_path)
            )
        except Exception as e:
            logger.error(f"Failed to load DewarpEngine: {e}")
            dewarp_engine = None

        pipeline = SearchPipelineV1(
            embeddings, 
            images, 
            SiftReranker(), 
            asyncio.Semaphore(settings.gpu_concurrency), 
            asyncio.Semaphore(settings.sift_concurrency), 
            settings.candidate_pool_size, 
            ocr_decoder=ocr_decoder,
            dewarp_engine=dewarp_engine
        )
        app.state.pipeline_v1 = pipeline
        ingestion = ProductIngestionService(images, detector, pipeline, settings.embedding_model_name)
        app.state.ingestion = ingestion
        batch_import = BatchImportService(settings.import_staging_dir, settings.max_import_items, settings.max_upload_bytes, images, ingestion, session_factory)
        await batch_import.recover_interrupted()
        app.state.batch_import = batch_import
    except Exception:
        logger.exception("ML services failed to load")
    yield
    for task in app.state.import_tasks:
        task.cancel()
    if app.state.import_tasks:
        await asyncio.gather(*app.state.import_tasks, return_exceptions=True)
    await engine.dispose()
