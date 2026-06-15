from fastapi import FastAPI
from app.routes.api import router
from app.api_keys import DEFAULT_KEY

app = FastAPI(title="Invoice OCR API")
app.include_router(router)

@app.get("/")
def root():
    return {"status": "ok", "default_api_key": DEFAULT_KEY}
