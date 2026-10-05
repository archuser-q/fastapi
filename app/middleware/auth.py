import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import User

bearer_scheme = HTTPBearer(auto_error=False) 

def _extract_token(request: Request, credentials: HTTPAuthorizationCredentials | None) -> str:
    if credentials and credentials.credentials:
        return credentials.credentials
    token = request.cookies.get(settings.auth_cookie_name)
    if token:
        return token
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Chưa đăng nhập")

def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    token = _extract_token(request, credentials)
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        user_id = int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token không hợp lệ hoặc đã hết hạn")

    user = db.get(User, user_id)
    if not user or user.status != "active":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Tài khoản không tồn tại hoặc đã bị khóa")
    return user


def require_roles(*roles: str):
    def checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Không có quyền truy cập")
        return user

    return checker