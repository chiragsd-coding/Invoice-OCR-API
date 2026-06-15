from fastapi import Header, HTTPException
from app.api_keys import is_valid_key

async def require_api_key(x_api_key: str = Header(...)):
    if not is_valid_key(x_api_key):
        raise HTTPException(status_code=401, detail="Invalid API key")
    return x_api_key
