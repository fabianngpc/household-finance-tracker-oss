from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.deps import get_db, get_current_user
from app.models.user import User
from app.schemas.link import LinkCodeOut
from app.services.link import generate_link_code, LINK_CODE_TTL_MINUTES

router = APIRouter()


@router.post("/link/generate", response_model=LinkCodeOut)
def generate_link(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> LinkCodeOut:
    code = generate_link_code(db, user)
    return LinkCodeOut(code=code, expires_in_minutes=LINK_CODE_TTL_MINUTES)
