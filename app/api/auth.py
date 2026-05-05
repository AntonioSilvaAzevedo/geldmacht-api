import logging
import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from ..database import get_db
from ..middleware.auth import get_current_user
from ..models.user import User
from ..services.auth_service import (
    create_access_token,
    create_user,
    get_or_create_google_user,
    get_user_by_email,
    verify_password,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


# ── Schemas ────────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    name: str = ""


class GoogleTokenRequest(BaseModel):
    access_token: str


class UserOut(BaseModel):
    email: str
    name: str | None


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


# ── Credentials ────────────────────────────────────────────────────────────────

@router.post("/login", response_model=AuthResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)) -> AuthResponse:
    user = get_user_by_email(db, body.email)
    if not user or not user.hashed_password:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciais inválidas")
    if not verify_password(body.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciais inválidas")

    token = create_access_token({"sub": user.email})
    logger.info("Login: %s", user.email)
    return AuthResponse(
        access_token=token,
        user=UserOut(email=user.email, name=user.name),
    )


class RegisterResponse(BaseModel):
    message: str
    user: UserOut


@router.post("/register", response_model=RegisterResponse, status_code=status.HTTP_201_CREATED)
def register(body: RegisterRequest, db: Session = Depends(get_db)) -> RegisterResponse:
    if get_user_by_email(db, body.email):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="E-mail já cadastrado")
    if len(body.password) < 8:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Senha deve ter pelo menos 8 caracteres")

    user = create_user(db, body.email, body.password, body.name)
    logger.info("Registro: %s", user.email)
    return RegisterResponse(
        message="Usuário criado com sucesso",
        user=UserOut(email=user.email, name=user.name),
    )


# ── Google OAuth ───────────────────────────────────────────────────────────────

@router.post("/google", response_model=AuthResponse)
async def google_auth(body: GoogleTokenRequest, db: Session = Depends(get_db)) -> AuthResponse:
    async with httpx.AsyncClient() as client:
        res = await client.get(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers={"Authorization": f"Bearer {body.access_token}"},
            timeout=10,
        )
    if res.status_code != 200:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token Google inválido")

    data = res.json()
    user = get_or_create_google_user(
        db,
        google_id=data["id"],
        email=data["email"],
        name=data.get("name", ""),
    )
    token = create_access_token({"sub": user.email})
    logger.info("Google OAuth: %s", user.email)
    return AuthResponse(
        access_token=token,
        user=UserOut(email=user.email, name=user.name),
    )


# ── Me ─────────────────────────────────────────────────────────────────────────

@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)) -> UserOut:
    return UserOut(email=current_user.email, name=current_user.name)
