from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.schemas.wines import MissingWineStatusRequest
from app.services.missing_wines_service import MissingWinesService

logger = logging.getLogger(__name__)
router = APIRouter(tags=["missing-wines"])


class MissingWineReportInput(BaseModel):
    source: Annotated[str, Field(max_length=50)] = "catalog_search"
    query_text: Annotated[str, Field(max_length=200)] = ""


def _service(request: Request) -> MissingWinesService:
    service: MissingWinesService | None = getattr(request.app.state, "missing_wines", None)
    if service is None:
        raise HTTPException(status_code=503, detail="Missing wines service not initialized")
    return service


@router.get("/missing-wines/image/{filename}")
async def get_missing_wine_image(filename: Annotated[str, Path(pattern=r"^[A-Za-z0-9_\-\.]+$")], request: Request):
    svc = _service(request)
    path = svc.resolve_image_path(filename)
    if path is None:
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(str(path))


@router.post("/missing-wines/report")
async def report_missing_wine(req: MissingWineReportInput, request: Request):
    svc = _service(request)
    return svc.log_missing(source=req.source, query_text=req.query_text)


@router.get("/admin/dashboard/missing-wines")
async def admin_dashboard_missing_wines(request: Request):
    svc = _service(request)
    return svc.get_dashboard()


@router.post("/admin/dashboard/missing-wines/{req_id}/status")
async def admin_update_status(
    req_id: Annotated[str, Path(pattern=r"^[A-Za-z0-9_\-]+$")],
    req: MissingWineStatusRequest,
    request: Request,
):
    svc = _service(request)
    ok = svc.update_status(req_id, req.status, req.admin_notes)
    if not ok:
        raise HTTPException(status_code=404, detail="Request not found")
    return {"success": True, "id": req_id, "new_status": req.status}
