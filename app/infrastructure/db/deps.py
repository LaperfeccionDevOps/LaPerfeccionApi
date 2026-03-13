from typing import Generator
from infrastructure.db.session import SessionLocal


def get_db() -> Generator:
    print("➡️ Entró a get_db()")
    db = SessionLocal()
    print(f"➡️ DB creada: {db}")
    try:
        yield db
    finally:
        db.close()