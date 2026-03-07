from sqlalchemy import text
from infrastructure.db.session import engine

with engine.connect() as conn:
    print(conn.execute(text("SELECT version()")).scalar())