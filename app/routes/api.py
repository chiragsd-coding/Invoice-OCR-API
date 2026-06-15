from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, Query
from sqlalchemy.orm import Session
import pytesseract
from PIL import Image
import io

from app.auth import require_user
from app.rate_limit import check_usage_limit
from app.models.base import OCRResult, User, get_db

router = APIRouter(tags=["ocr"])


def _extract_text(file_bytes: bytes, content_type: str) -> str:
    if content_type == "application/pdf":
        from pdf2image import convert_from_bytes
        images = convert_from_bytes(file_bytes)
        return "\n".join(pytesseract.image_to_string(img) for img in images)
    else:
        image = Image.open(io.BytesIO(file_bytes))
        return pytesseract.image_to_string(image)


@router.post("/ocr/upload", summary="Upload an invoice for OCR extraction")
async def upload_invoice(
    file: UploadFile = File(...),
    user: User = Depends(check_usage_limit),  # auth + plan limit enforcement
    db: Session = Depends(get_db),
):
    """
    Upload a JPEG, PNG, or PDF invoice. Returns the extracted text and a
    result ID. Counts against the monthly plan limit.
    """
    contents = await file.read()
    text = _extract_text(contents, file.content_type)
    result = OCRResult(filename=file.filename, text=text, user_id=user.id)
    db.add(result)
    db.commit()
    db.refresh(result)
    return {"id": result.id, "filename": result.filename, "text": text}


@router.get("/ocr/results", summary="List OCR results (paginated)")
def list_results(
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
    limit: int = Query(default=20, ge=1, le=100, description="Number of results to return"),
    offset: int = Query(default=0, ge=0, description="Number of results to skip"),
):
    """Return OCR results for the authenticated user, newest first."""
    total = db.query(OCRResult).filter(OCRResult.user_id == user.id).count()
    results = (
        db.query(OCRResult)
        .filter(OCRResult.user_id == user.id)
        .order_by(OCRResult.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [
            {"id": r.id, "filename": r.filename, "created_at": r.created_at}
            for r in results
        ],
    }


@router.get("/ocr/results/{result_id}", summary="Get a single OCR result")
def get_result(
    result_id: int,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Fetch full details (including extracted text) for one OCR result."""
    result = (
        db.query(OCRResult)
        .filter(OCRResult.id == result_id, OCRResult.user_id == user.id)
        .first()
    )
    if not result:
        raise HTTPException(status_code=404, detail="Result not found")
    return {
        "id": result.id,
        "filename": result.filename,
        "text": result.text,
        "created_at": result.created_at,
    }


@router.delete("/ocr/results/{result_id}", status_code=204, summary="Delete an OCR result")
def delete_result(
    result_id: int,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Permanently delete an OCR result. Only the owning user can delete it."""
    result = (
        db.query(OCRResult)
        .filter(OCRResult.id == result_id, OCRResult.user_id == user.id)
        .first()
    )
    if not result:
        raise HTTPException(status_code=404, detail="Result not found")
    db.delete(result)
    db.commit()
