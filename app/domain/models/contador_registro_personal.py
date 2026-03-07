from sqlalchemy import Column, Integer
from infrastructure.db.base import Base

class ContadorRegistroPersonal(Base):
    __tablename__ = 'ContadorRegistroPersonal'
    IdRegistroPersonal = Column(Integer, primary_key=True, index=True)
    Contador = Column(Integer, nullable=False, default=1)
