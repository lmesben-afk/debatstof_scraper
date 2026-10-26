from db.database import initialize_database

initialize_database()
from rescore_db import ensure_current_scoring
ensure_current_scoring()
from app.app import app
