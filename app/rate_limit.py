from collections import defaultdict
from time import time
from fastapi import HTTPException

# 10 requests per 60 seconds per API key
LIMIT = 10
WINDOW = 60

_requests: dict[str, list[float]] = defaultdict(list)

def check_rate_limit(api_key: str):
    now = time()
    timestamps = _requests[api_key]
    # Drop old entries outside window
    _requests[api_key] = [t for t in timestamps if now - t < WINDOW]
    if len(_requests[api_key]) >= LIMIT:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")
    _requests[api_key].append(now)
