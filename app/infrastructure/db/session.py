from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import os
from dotenv import load_dotenv

dotenv_path = os.path.join(os.path.dirname(__file__), '../../../.env')
load_dotenv(dotenv_path)

DATABASE_URL = os.getenv("DATABASE_URL")
print("DATABASE_URL:", DATABASE_URL)

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,   # ✅ revisa conexión antes de usarla
    pool_recycle=1800,    # ✅ recicla conexiones viejas (30 min)
)


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)