import bcrypt
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.deps import get_db, get_current_user
from app.models.user import User
from app.schemas.auth import LoginRequest

router = APIRouter()


def _partner_display_name(db: Session, user: User) -> str:
    """The other user's display name (this is a fixed two-person household)."""
    other = db.query(User).filter(User.id != user.id).order_by(User.id).first()
    return other.display_name if other else "Partner"


@router.post("/login")
def login(request: Request, body: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == body.username).first()
    if user is None or not bcrypt.checkpw(body.password.encode(), user.password_hash.encode()):
        raise HTTPException(
            status_code=401,
            detail="Invalid username or password. Check your credentials and try again.",
        )
    request.session["user_id"] = user.id
    return {
        "ok": True,
        "user": {
            "id": user.id,
            "username": user.username,
            "display_name": user.display_name,
            "partner_display_name": _partner_display_name(db, user),
        },
    }


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "partner_display_name": _partner_display_name(db, user),
    }
