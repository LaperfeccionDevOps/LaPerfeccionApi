from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from domain.models.aspirante import RegistroPersonal

def create(db: Session, data: RegistroPersonal) -> RegistroPersonal:
    try:
        db.add(data)
        db.commit()
        db.refresh(data)
        return data
    except Exception as e:
         raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error controlado {str(e)}"
        )
