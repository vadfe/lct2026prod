from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np

logger = logging.getLogger(__name__)

USER_FRIENDLY_MESSAGE = "Данного вина пока нет в каталоге, скоро появится, спасибо за проявленный интерес."


class MissingWinesService:
    """Хранилище запросов на отсутствующие в каталоге вина.

    Данные сохраняются строго внутри `media_dir / missing_wines` (единственный каталог, доступный на запись в контейнере).
    """

    def __init__(self, media_dir: Path):
        self.base_dir = media_dir / "missing_wines"
        self.images_dir = self.base_dir / "images"
        self.db_file = self.base_dir / "missing_wines.json"
        try:
            self.images_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            logger.warning("Could not create missing_wines directory at %s", self.images_dir)

    def _read_records(self) -> list[dict[str, Any]]:
        if not self.db_file.is_file():
            return []
        try:
            with open(self.db_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            logger.exception("Failed to read missing wines DB")
            return []

    def _write_records(self, records: list[dict[str, Any]]) -> None:
        try:
            with open(self.db_file, "w", encoding="utf-8") as f:
                json.dump(records, f, ensure_ascii=False, indent=2)
        except Exception:
            logger.exception("Failed to write missing wines DB")

    def log_missing(
        self,
        source: str,
        query_text: str = "",
        img_bgr: np.ndarray | None = None,
        confidence: float | None = None,
    ) -> dict[str, Any]:
        req_id = f"req_{int(time.time())}_{uuid.uuid4().hex[:6]}"
        now_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        image_url = ""

        if img_bgr is not None and img_bgr.size > 0:
            filename = f"{req_id}.jpg"
            filepath = self.images_dir / filename
            try:
                cv2.imwrite(str(filepath), img_bgr)
                image_url = f"/api/missing-wines/image/{filename}"
            except Exception:
                logger.exception("Failed to save missing wine image")

        record = {
            "id": req_id,
            "timestamp": now_iso,
            "source": source,
            "query_text": query_text.strip() if query_text else "",
            "image_url": image_url,
            "confidence": confidence,
            "status": "pending",
            "admin_notes": "",
        }

        records = self._read_records()
        records.insert(0, record)
        self._write_records(records)

        return {
            "success": True,
            "id": req_id,
            "message": USER_FRIENDLY_MESSAGE,
            "record": record,
        }

    def get_dashboard(self) -> dict[str, Any]:
        records = self._read_records()
        return {
            "total": len(records),
            "pending": sum(1 for r in records if r.get("status") == "pending"),
            "in_progress": sum(1 for r in records if r.get("status") == "in_progress"),
            "resolved": sum(1 for r in records if r.get("status") == "resolved" or r.get("status") == "added"),
            "sources": {
                "scanner": sum(1 for r in records if r.get("source") == "scanner"),
                "catalog_search": sum(1 for r in records if r.get("source") == "catalog_search"),
            },
            "records": records[:100],
        }

    def update_status(self, req_id: str, new_status: str, admin_notes: str = "") -> bool:
        records = self._read_records()
        found = False
        for r in records:
            if r.get("id") == req_id:
                r["status"] = new_status
                if admin_notes:
                    r["admin_notes"] = admin_notes
                found = True
                break
        if found:
            self._write_records(records)
        return found

    def resolve_image_path(self, filename: str) -> Path | None:
        safe_name = Path(filename).name
        target = self.images_dir / safe_name
        if target.is_file():
            return target
        return None
