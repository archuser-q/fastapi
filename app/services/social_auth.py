"""Xác minh token đăng nhập Google / Facebook ở phía server.

App lấy token từ Google/Facebook (expo-auth-session) rồi gửi lên; backend KHÔNG tin thông tin
app gửi kèm mà tự hỏi lại Google/Facebook để biết token có thật, có đúng ứng dụng của mình không.
"""

from dataclasses import dataclass

import httpx
from fastapi import HTTPException, status

from app.config import settings

TIMEOUT = httpx.Timeout(10.0)
GOOGLE_ISSUERS = {"accounts.google.com", "https://accounts.google.com"}


@dataclass
class SocialProfile:
    provider: str
    provider_user_id: str
    email: str | None
    email_verified: bool
    full_name: str | None
    avatar_url: str | None


def google_client_ids() -> list[str]:
    return [
        c
        for c in (
            settings.google_web_client_id,
            settings.google_android_client_id,
            settings.google_ios_client_id,
        )
        if c
    ]


def facebook_enabled() -> bool:
    return bool(settings.facebook_app_id and settings.facebook_app_secret)


def _bad(msg: str) -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, msg)


def _get_json(url: str, **kwargs) -> dict:
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            res = client.get(url, **kwargs)
    except httpx.HTTPError:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Không kết nối được máy chủ đăng nhập, thử lại sau")
    if res.status_code >= 400:
        raise _bad("Phiên đăng nhập không hợp lệ hoặc đã hết hạn")
    return res.json()


def verify_google(id_token: str | None, access_token: str | None) -> SocialProfile:
    allowed = google_client_ids()
    if not allowed:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Máy chủ chưa cấu hình đăng nhập Google")

    if id_token:
        info = _get_json("https://oauth2.googleapis.com/tokeninfo", params={"id_token": id_token})
        if info.get("aud") not in allowed:
            raise _bad("Token Google không thuộc ứng dụng này")
        if info.get("iss") not in GOOGLE_ISSUERS:
            raise _bad("Token Google không hợp lệ")
        profile = info
    else:
        info = _get_json("https://oauth2.googleapis.com/tokeninfo", params={"access_token": access_token})
        if info.get("aud") not in allowed and info.get("azp") not in allowed:
            raise _bad("Token Google không thuộc ứng dụng này")
        profile = _get_json(
            "https://www.googleapis.com/oauth2/v3/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
        )

    sub = profile.get("sub") or info.get("sub")
    if not sub:
        raise _bad("Không đọc được tài khoản Google")
    verified = str(profile.get("email_verified", info.get("email_verified", ""))).lower() == "true"
    return SocialProfile(
        provider="google",
        provider_user_id=str(sub),
        email=(profile.get("email") or "").lower() or None,
        email_verified=verified,
        full_name=profile.get("name"),
        avatar_url=profile.get("picture"),
    )


def verify_facebook(access_token: str) -> SocialProfile:
    if not facebook_enabled():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Máy chủ chưa cấu hình đăng nhập Facebook")

    app_token = f"{settings.facebook_app_id}|{settings.facebook_app_secret}"
    debug = _get_json(
        "https://graph.facebook.com/debug_token",
        params={"input_token": access_token, "access_token": app_token},
    ).get("data", {})
    if not debug.get("is_valid") or str(debug.get("app_id")) != str(settings.facebook_app_id):
        raise _bad("Token Facebook không thuộc ứng dụng này")

    me = _get_json(
        "https://graph.facebook.com/me",
        params={"fields": "id,name,email,picture.width(256).height(256)", "access_token": access_token},
    )
    picture = (me.get("picture") or {}).get("data", {}).get("url")
    return SocialProfile(
        provider="facebook",
        provider_user_id=str(me["id"]),
        email=(me.get("email") or "").lower() or None,
        email_verified=bool(me.get("email")),  # Facebook chỉ trả email đã xác minh
        full_name=me.get("name"),
        avatar_url=picture,
    )
