from fastapi import APIRouter, UploadFile, File, Depends
from sqlalchemy.orm import Session
import pytesseract
from PIL import Image
import io

from app.auth import require_api_key
from app.rate_limit import check_rate_limit
from app.models.base import OCRResult, get_db

router = APIRouter()

def _extract_text(file_bytes: bytes, content_type: str) -> str:
    if content_type == "application/pdf":
        from pdf2image import convert_from_bytes
        images = convert_from_bytes(file_bytes)
        return "\n".join(pytesseract.image_to_string(img) for img in images)
    else:
        image = Image.open(io.BytesIO(file_bytes))
        return pytesseract.image_to_string(image)

@router.post("/ocr/upload")
async def upload_invoice(
    file: UploadFile = File(...),
    api_key: str = Depends(require_api_key),
    db: Session = Depends(get_db),
):
    check_rate_limit(api_key)
    contents = await file.read()
    text = _extract_text(contents, file.content_type)
    result = OCRResult(filename=file.filename, text=text)
    db.add(result)
    db.commit()
    db.refresh(result)
    return {"id": result.id, "filename": result.filename, "text": text}

@router.get("/ocr/results")
def list_results(
    api_key: str = Depends(require_api_key),
    db: Session = Depends(get_db),
):
    results = db.query(OCRResult).order_by(OCRResult.id.desc()).limit(20).all()
    return [{"id": r.id, "filename": r.filename, "created_at": r.created_at} for r in results]
