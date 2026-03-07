import os

class Settings:
    # Ajusta esta URL cuando conectemos a Postgres real
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg2://user:pass@localhost:5432/la_perfeccion"
    )

settings = Settings()