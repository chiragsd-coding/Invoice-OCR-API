import secrets

# In-memory store for demo. Replace with DB-backed store for production.
_API_KEYS: set[str] = set()

def create_api_key() -> str:
    key = secrets.token_hex(32)
    _API_KEYS.add(key)
    return key

def is_valid_key(key: str) -> bool:
    return key in _API_KEYS

# Seed a default key for easy testing
DEFAULT_KEY = create_api_key()
