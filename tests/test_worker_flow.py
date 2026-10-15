"""Kiểm thử luồng App Thợ + bộ điều phối ghép cặp trên PostgreSQL/PostGIS thật.

Mỗi lần chạy đặt khu vực test ở 1 toạ độ ngẫu nhiên để không lẫn với dữ liệu lần chạy trước.
"""

import random
import uuid
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.database import SessionLocal
from app.main import app
from app.services import dispatch_service, social_auth
from app.services.social_auth import SocialProfile
from app.utils.dates import now_vn

client = TestClient(app)
API = "/api/v1"
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 200
RNG = random.Random()
# Tâm khu vực test: điểm ngẫu nhiên trong vùng Bắc Bộ
LAT0 = round(RNG.uniform(20.0, 22.0), 5)
LNG0 = round(RNG.uniform(105.0, 106.5), 5)


def off(dlat_km=0.0, dlng_km=0.0):
    return LAT0 + dlat_km / 111.32, LNG0 + dlng_km / 103.8


def _sql(q, **kw):
    with SessionLocal() as db:
        res = db.execute(text(q), kw)
        db.commit()
        try:
            return res.scalar()
        except Exception:
            return None


def _email(prefix):
    return f"{prefix}.{uuid.uuid4().hex[:10]}@test.thonhanh.vn"


def _phone():
    return "09" + str(uuid.uuid4().int)[:8]


def _login(identifier, password="12345678", role=None):
    body = {"identifier": identifier, "password": password}
    if role:
        body["role"] = role
    r = client.post(f"{API}/auth/login", json=body)
    client.cookies.clear()
    assert r.status_code == 200, r.text
    return r.json()["data"]["user"]["id"], {"Authorization": f"Bearer {r.json()['data']['access_token']}"}


def _register(role, email=None, phone=None, name=None):
    email = email or _email(role)
    body = {"email": email, "password": "12345678", "full_name": name or f"Test {role}", "role": role}
    if phone:
        body["phone"] = phone
    r = client.post(f"{API}/auth/register", json=body)
    assert r.status_code == 201, r.text
    uid, h = _login(email, role=role)
    return uid, h, email


def _upload(h):
    r = client.post(f"{API}/uploads", files={"file": ("a.jpg", JPEG, "image/jpeg")}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()["data"]["url"]


def _tick(batch=False):
    with SessionLocal() as db:
        dispatch_service.expire_offers(db)
        dispatch_service.run_due_instant(db)
        if batch:
            dispatch_service.run_batch_round(db)
        dispatch_service.cancel_overdue(db)


def _set_config(mode="instant", max_offers=2, timeout=60):
    _sql("UPDATE matching_configs SET is_active = FALSE WHERE is_active")
    name = f"Test {mode} {uuid.uuid4().hex[:6]}"
    _sql(
        "INSERT INTO matching_configs(name, mode, weight_distance, weight_trust, weight_price, weight_workload,"
        " batch_window_seconds, search_radius_km, max_offers, offer_timeout_seconds, is_active)"
        " VALUES (:n, :m, 0.4, 0.3, 0.1, 0.2, :bw, 5, :k, :t, TRUE)",
        n=name, m=mode, bw=10 if mode == "batch" else None, k=max_offers, t=timeout,
    )


def _make_ready_worker(admin_h, name, dlat_km, dlng_km, trust=0.8):
    """Tạo thợ đã qua toàn bộ onboarding + admin duyệt + đang bật nhận đơn tại toạ độ cho trước."""
    wid, wh, _ = _register("worker", name=name)
    client.patch(f"{API}/worker/profile", json={"phone": _phone(), "experience_years": 5}, headers=wh)
    assert client.put(f"{API}/worker/services", json={"service_ids": [SVC1, SVC2]}, headers=wh).status_code == 200
    for t in ("id_card_front", "id_card_back", "portrait"):
        assert client.post(f"{API}/worker/documents", json={"doc_type": t, "file_url": _upload(wh)}, headers=wh).status_code == 201
    assert client.post(f"{API}/worker/verification/submit", headers=wh).status_code == 200
    _approve(admin_h, wid)
    _sql("UPDATE worker_profiles SET trust_score=:t WHERE user_id=:w", t=trust, w=wid)
    lat, lng = off(dlat_km, dlng_km)
    r = client.patch(f"{API}/worker/availability", json={"online": True, "latitude": lat, "longitude": lng}, headers=wh)
    assert r.status_code == 200, r.text
    return wid, wh


def _approve(admin_h, wid):
    detail = client.get(f"{API}/admin/workers/{wid}", headers=admin_h).json()["data"]
    for d in detail["documents"]:
        if d["status"] == "pending":
            assert client.patch(f"{API}/admin/worker-documents/{d['id']}/review", json={"status": "approved"}, headers=admin_h).status_code == 200
    r = client.patch(f"{API}/admin/workers/{wid}/verification", json={"status": "approved"}, headers=admin_h)
    assert r.status_code == 200, r.text


def _order(customer_h, dlat_km=0.0, dlng_km=0.0, service_id=None, scheduled_at=None):
    lat, lng = off(dlat_km, dlng_km)
    body = {"service_id": service_id or SVC1, "address_line": "12 Ngõ Test", "latitude": lat, "longitude": lng, "description": "Mất điện phòng bếp"}
    if scheduled_at:
        body["scheduled_at"] = scheduled_at
    r = client.post(f"{API}/customer/orders", json=body, headers=customer_h)
    assert r.status_code == 201, r.text
    return r.json()["data"]["id"]


def _offer(wh):
    return client.get(f"{API}/worker/offers/current", headers=wh).json()["data"]


def setup_module():
    global SVC1, SVC2, ADMIN_H, CUS_ID, CUS_H
    cat = _sql("INSERT INTO service_categories(name) VALUES ('Điện dân dụng (test)') RETURNING id")
    SVC1 = _sql("INSERT INTO services(category_id,name,base_price,unit) VALUES (:c,'Sửa chập điện',250000,'lần') RETURNING id", c=cat)
    SVC2 = _sql("INSERT INTO services(category_id,name,base_price,unit) VALUES (:c,'Thay aptomat',200000,'cái') RETURNING id", c=cat)
    admin_email = _email("admin")
    _sql(
        "INSERT INTO users(phone,email,password_hash,full_name,role) VALUES (:p,:e,:h,'Admin test','admin')",
        p=_phone(), e=admin_email, h=__import__("app.utils.security", fromlist=["x"]).hash_password("12345678"),
    )
    _, ADMIN_H = _login(admin_email)
    CUS_ID, CUS_H, _ = _register("customer", name="Nguyễn Thị Hoa", phone=_phone())
    _set_config("instant", max_offers=2)


def teardown_module():
    _sql("UPDATE worker_profiles SET availability='offline' WHERE user_id IN (SELECT id FROM users WHERE email LIKE '%@test.thonhanh.vn')")


# ---------------------------------------------------------------------------


def test_auth_email_phone_and_role_guard():
    email = _email("worker")
    r = client.post(f"{API}/auth/register", json={"email": email.upper(), "password": "12345678", "full_name": "  Trần   Văn  A ", "role": "worker"})
    assert r.status_code == 201 and r.json()["data"]["email"] == email and r.json()["data"]["phone"] is None
    assert r.json()["data"]["full_name"] == "Trần Văn A"
    # trùng email (khác hoa thường)
    assert client.post(f"{API}/auth/register", json={"email": email, "password": "12345678", "full_name": "X", "role": "worker"}).status_code == 400
    # đăng nhập bằng app khách -> chặn
    r = client.post(f"{API}/auth/login", json={"identifier": email, "password": "12345678", "role": "customer"})
    assert r.status_code == 403 and "thợ" in r.json()["detail"]
    # sai mật khẩu
    assert client.post(f"{API}/auth/login", json={"email": email, "password": "sai-mat-khau"}).status_code == 401
    # web admin / app khách cũ vẫn đăng nhập bằng phone
    phone = _phone()
    assert client.post(f"{API}/auth/register", json={"phone": phone, "password": "12345678", "full_name": "Khách cũ"}).status_code == 201
    assert client.post(f"{API}/auth/login", json={"phone": phone, "password": "12345678"}).status_code == 200
    client.cookies.clear()


def test_forgot_and_reset_password():
    _, _, email = _register("worker")
    r = client.post(f"{API}/auth/forgot-password", json={"email": email})
    code = r.json()["data"]["debug_code"]
    assert len(code) == 6
    assert client.post(f"{API}/auth/forgot-password", json={"email": email}).status_code == 429  # chờ 1 phút
    bad = "000000" if code != "000000" else "111111"
    assert client.post(f"{API}/auth/reset-password", json={"email": email, "code": bad, "new_password": "matkhaumoi1"}).status_code == 400
    assert client.post(f"{API}/auth/reset-password", json={"email": email, "code": code, "new_password": "matkhaumoi1"}).status_code == 200
    _login(email, "matkhaumoi1")
    # mã đã dùng không dùng lại được
    assert client.post(f"{API}/auth/reset-password", json={"email": email, "code": code, "new_password": "matkhaumoi2"}).status_code == 400
    # email lạ: vẫn trả lời chung chung
    assert client.post(f"{API}/auth/forgot-password", json={"email": _email("none")}).status_code == 200


def test_social_login_google_and_facebook(monkeypatch):
    sub = uuid.uuid4().hex
    email = _email("gg")
    monkeypatch.setattr(
        social_auth, "verify_google",
        lambda id_token, access_token: SocialProfile("google", sub, email, True, "Lê Văn Google", "https://x/a.png"),
    )
    r = client.post(f"{API}/auth/google", json={"id_token": "x" * 50, "role": "worker"})
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["is_new"] and d["user"]["role"] == "worker" and d["user"]["email"] == email
    # lần 2: cùng tài khoản
    r2 = client.post(f"{API}/auth/google", json={"id_token": "y" * 50, "role": "worker"})
    assert r2.json()["data"]["user"]["id"] == d["user"]["id"] and not r2.json()["data"]["is_new"]
    # tài khoản Google không có mật khẩu -> báo dùng nút Google
    r3 = client.post(f"{API}/auth/login", json={"identifier": email, "password": "12345678"})
    assert r3.status_code == 401 and "Google" in r3.json()["detail"]
    # có hồ sơ thợ
    h = {"Authorization": f"Bearer {d['access_token']}"}
    assert client.get(f"{API}/worker/me", headers=h).json()["data"]["profile"]["verification_status"] == "pending"
    # đặt mật khẩu lần đầu không cần mật khẩu cũ
    assert client.post(f"{API}/auth/change-password", json={"new_password": "abcdefgh"}, headers=h).status_code == 200

    # Facebook: email trùng tài khoản khách có sẵn -> liên kết, nhưng app thợ bị chặn đúng vai trò
    _, _, cus_email = _register("customer")
    monkeypatch.setattr(
        social_auth, "verify_facebook",
        lambda token: SocialProfile("facebook", uuid.uuid4().hex, cus_email, True, "Khách FB", None),
    )
    r = client.post(f"{API}/auth/facebook", json={"access_token": "t" * 30, "role": "worker"})
    assert r.status_code == 403
    r = client.post(f"{API}/auth/facebook", json={"access_token": "t" * 30, "role": "customer"})
    assert r.status_code == 200 and r.json()["data"]["user"]["email"] == cus_email
    client.cookies.clear()


def test_upload_validation():
    _, h, _ = _register("worker")
    r = client.post(f"{API}/uploads", files={"file": ("a.txt", b"hello world", "text/plain")}, headers=h)
    assert r.status_code == 400
    assert client.post(f"{API}/uploads", files={"file": ("a.jpg", JPEG, "image/jpeg")}).status_code == 401
    url = _upload(h)
    assert "/media/" in url
    path = url.split("/media/", 1)[1]
    assert client.get(f"/media/{path}").status_code == 200


def test_onboarding_and_verification():
    wid, wh, _ = _register("worker", name="Phạm Thợ Mới")
    me = client.get(f"{API}/worker/me", headers=wh).json()["data"]
    ob = me["onboarding"]
    assert not ob["can_submit"] and not ob["has_phone"] and not ob["has_skills"]
    assert any("số điện thoại" in m for m in ob["missing"]) and any("CCCD mặt trước" in m for m in ob["missing"])
    # chưa duyệt thì không bật nhận đơn được
    lat, lng = off()
    r = client.patch(f"{API}/worker/availability", json={"online": True, "latitude": lat, "longitude": lng}, headers=wh)
    assert r.status_code == 400 and "duyệt" in r.json()["detail"]
    # nộp thiếu -> không gửi được
    assert client.post(f"{API}/worker/verification/submit", headers=wh).status_code == 400

    client.patch(f"{API}/worker/profile", json={"phone": _phone(), "bio": "Thợ điện 10 năm", "service_radius_km": 8}, headers=wh)
    client.put(f"{API}/worker/services", json={"service_ids": [SVC1]}, headers=wh)
    assert client.put(f"{API}/worker/services", json={"service_ids": [999999]}, headers=wh).status_code == 400
    for t in ("id_card_front", "id_card_back", "portrait"):
        client.post(f"{API}/worker/documents", json={"doc_type": t, "file_url": _upload(wh)}, headers=wh)
    # tải lại CCCD mặt trước khi đang chờ duyệt -> thay ảnh, không tạo bản trùng
    client.post(f"{API}/worker/documents", json={"doc_type": "id_card_front", "file_url": _upload(wh)}, headers=wh)
    docs = client.get(f"{API}/worker/documents", headers=wh).json()["data"]
    assert len([d for d in docs if d["doc_type"] == "id_card_front"]) == 1
    me = client.get(f"{API}/worker/me", headers=wh).json()["data"]
    assert me["onboarding"]["missing"] == [] and me["onboarding"]["can_submit"]
    assert me["profile"]["service_radius_km"] == 8
    r = client.post(f"{API}/worker/verification/submit", headers=wh)
    assert r.status_code == 200 and r.json()["data"]["onboarding"]["submitted_at"]
    assert client.post(f"{API}/worker/verification/submit", headers=wh).status_code == 400  # đã gửi

    # admin từ chối 1 giấy tờ -> thợ thấy lý do + được báo
    detail = client.get(f"{API}/admin/workers/{wid}", headers=ADMIN_H).json()["data"]
    front = next(d for d in detail["documents"] if d["doc_type"] == "id_card_front")
    client.patch(f"{API}/admin/worker-documents/{front['id']}/review", json={"status": "rejected", "reject_reason": "Ảnh bị mờ"}, headers=ADMIN_H)
    me = client.get(f"{API}/worker/me", headers=wh).json()["data"]
    assert any("Ảnh bị mờ" in x for x in me["onboarding"]["reject_reasons"])
    assert any("Tải lại CCCD mặt trước" in m for m in me["onboarding"]["missing"])
    notes = client.get(f"{API}/notifications", headers=wh).json()["data"]["items"]
    assert any(n["type"] == "verification" for n in notes)

    # Giấy tờ bắt buộc đã duyệt: gửi ảnh mới thành 1 bản CHỜ DUYỆT riêng, bản đã duyệt vẫn giữ nguyên;
    # không gỡ được bản đã duyệt, gỡ được bản cập nhật đang chờ; bản bị từ chối vẫn tải lại được
    back = next(d for d in detail["documents"] if d["doc_type"] == "id_card_back")
    client.patch(f"{API}/admin/worker-documents/{back['id']}/review", json={"status": "approved"}, headers=ADMIN_H)
    r = client.post(f"{API}/worker/documents", json={"doc_type": "id_card_back", "file_url": _upload(wh)}, headers=wh)
    assert r.status_code == 201 and "ảnh cũ vẫn dùng" in r.json()["message"]
    update_id = r.json()["data"]["id"]
    docs = client.get(f"{API}/worker/documents", headers=wh).json()["data"]
    backs = {d["id"]: d["status"] for d in docs if d["doc_type"] == "id_card_back"}
    assert backs == {back["id"]: "approved", update_id: "pending"}
    r = client.delete(f"{API}/worker/documents/{back['id']}", headers=wh)
    assert r.status_code == 400 and "gửi ảnh mới" in r.json()["detail"]
    assert client.delete(f"{API}/worker/documents/{update_id}", headers=wh).status_code == 200
    r = client.post(f"{API}/worker/documents", json={"doc_type": "id_card_front", "file_url": _upload(wh)}, headers=wh)
    assert r.status_code == 201


def test_update_documents_after_approval():
    """Thợ đã duyệt gửi CCCD mới: ảnh cũ vẫn hiệu lực tới khi admin duyệt ảnh mới; chứng chỉ đã duyệt gỡ được."""
    wid, wh = _make_ready_worker(ADMIN_H, "Thợ Đổi Giấy Tờ", 9.0, 9.0)
    client.patch(f"{API}/worker/availability", json={"online": False}, headers=wh)
    r = client.post(f"{API}/worker/documents", json={"doc_type": "id_card_front", "file_url": _upload(wh)}, headers=wh)
    new_id = r.json()["data"]["id"]
    me = client.get(f"{API}/worker/me", headers=wh).json()["data"]
    assert me["profile"]["verification_status"] == "approved"  # vẫn được nhận việc trong lúc chờ duyệt ảnh mới
    client.patch(f"{API}/admin/worker-documents/{new_id}/review", json={"status": "approved"}, headers=ADMIN_H)
    notes = client.get(f"{API}/notifications", headers=wh).json()["data"]["items"]
    assert any(n["title"] == "Đã duyệt giấy tờ mới" for n in notes)
    fronts = [d for d in client.get(f"{API}/worker/documents", headers=wh).json()["data"] if d["doc_type"] == "id_card_front"]
    assert fronts[0]["id"] == new_id and all(d["status"] == "approved" for d in fronts)  # mới nhất đứng đầu, bản cũ giữ làm lịch sử
    # chứng chỉ đã duyệt: thợ tự gỡ được (không bắt buộc)
    cert = client.post(f"{API}/worker/documents", json={"doc_type": "certificate", "file_url": _upload(wh)}, headers=wh).json()["data"]
    client.patch(f"{API}/admin/worker-documents/{cert['id']}/review", json={"status": "approved"}, headers=ADMIN_H)
    assert client.delete(f"{API}/worker/documents/{cert['id']}", headers=wh).status_code == 200


def test_full_instant_job_flow():
    w1, w1h = _make_ready_worker(ADMIN_H, "Thợ Một", 0.5, 0.0, trust=0.9)
    w2, w2h = _make_ready_worker(ADMIN_H, "Thợ Hai", 1.5, 0.0, trust=0.7)
    oid = _order(CUS_H)

    # chế độ tức thời: đợt 1 gửi cho top-2
    o1, o2 = _offer(w1h), _offer(w2h)
    assert o1 and o2 and o1["order_id"] == o2["order_id"] == oid
    assert o1["match_score"] > o2["match_score"]  # gần hơn + tin cậy cao hơn
    assert o1["customer_name"] == "Hoa" and o1["estimated_earning"] == 250000 - 37500
    assert 0 < o1["expires_in_seconds"] <= 60
    detail = client.get(f"{API}/customer/orders/{oid}", headers=CUS_H).json()["data"]
    assert detail["matching_mode"] == "instant" and detail["status"] == "pending"

    # thợ 1 nhận -> thợ 2 hết lời mời
    r = client.post(f"{API}/worker/offers/{o1['id']}/accept", headers=w1h)
    assert r.status_code == 200, r.text
    job = r.json()["data"]
    assert job["status"] == "accepted" and job["customer"]["phone"] is not None and job["next_status"] == "on_the_way"
    assert _offer(w2h) is None
    assert client.post(f"{API}/worker/offers/{o2['id']}/accept", headers=w2h).status_code == 409
    home = client.get(f"{API}/worker/home", headers=w1h).json()["data"]
    assert home["availability"] == "busy" and home["active_job"]["id"] == oid

    # khách thấy thợ
    c = client.get(f"{API}/customer/orders/{oid}", headers=CUS_H).json()["data"]
    assert c["status"] == "accepted" and c["worker"]["id"] == w1

    # nhảy bước -> lỗi
    assert client.post(f"{API}/worker/orders/{oid}/status", json={"status": "arrived"}, headers=w1h).status_code == 400
    for st in ("on_the_way", "arrived"):
        r = client.post(f"{API}/worker/orders/{oid}/status", json={"status": st}, headers=w1h)
        assert r.status_code == 200 and r.json()["data"]["status"] == st
    # vị trí khi đang làm đơn -> lưu vết
    lat, lng = off(0.1, 0.1)
    client.patch(f"{API}/worker/location", json={"latitude": lat, "longitude": lng}, headers=w1h)
    assert _sql("SELECT count(*) FROM worker_location_logs WHERE worker_id=:w", w=w1) >= 1
    t = client.get(f"{API}/customer/orders/{oid}/tracking", headers=CUS_H).json()["data"]
    assert abs(t["worker_latitude"] - lat) < 1e-9

    # ảnh trước khi sửa
    r = client.post(f"{API}/worker/orders/{oid}/photos", json={"kind": "before", "urls": [_upload(w1h)]}, headers=w1h)
    assert r.status_code == 201
    assert client.post(f"{API}/worker/orders/{oid}/photos", json={"kind": "after", "urls": [_upload(w1h)]}, headers=w1h).status_code == 400
    # chưa xác nhận an toàn điện -> không cho bắt đầu sửa
    r = client.post(f"{API}/worker/orders/{oid}/status", json={"status": "in_progress"}, headers=w1h)
    assert r.status_code == 400 and "an toàn" in r.json()["detail"]
    r = client.post(f"{API}/worker/orders/{oid}/status", json={"status": "in_progress", "safety_confirmed": True}, headers=w1h)
    assert r.status_code == 200 and r.json()["data"]["safety_checked_at"]

    # báo giá phát sinh -> khách duyệt
    r = client.post(f"{API}/worker/orders/{oid}/extra-quotes", json={"description": "Thay dây điện 10m", "amount": 120000}, headers=w1h)
    assert r.status_code == 201 and r.json()["data"]["has_pending_quote"]
    assert client.post(f"{API}/worker/orders/{oid}/extra-quotes", json={"description": "Thêm nữa", "amount": 1000}, headers=w1h).status_code == 400
    # chưa duyệt báo giá -> chưa hoàn thành được
    assert client.post(f"{API}/worker/orders/{oid}/status", json={"status": "completed"}, headers=w1h).status_code == 400
    qid = r.json()["data"]["extra_quotes"][0]["id"]
    assert client.post(f"{API}/customer/orders/{oid}/extra-quotes/{qid}/approve", headers=CUS_H).json()["data"]["total_amount"] == 370000

    # chưa có ảnh sau -> chưa hoàn thành được
    r = client.post(f"{API}/worker/orders/{oid}/status", json={"status": "completed"}, headers=w1h)
    assert r.status_code == 400 and "ảnh" in r.json()["detail"]
    client.post(f"{API}/worker/orders/{oid}/photos", json={"kind": "after", "urls": [_upload(w1h), _upload(w1h)]}, headers=w1h)
    r = client.post(f"{API}/worker/orders/{oid}/status", json={"status": "completed"}, headers=w1h)
    assert r.status_code == 200, r.text
    job = r.json()["data"]
    assert job["final_price"] == 370000 and job["warranty"] and job["can_confirm_cash"] and job["amount_to_collect"] == 370000
    assert client.get(f"{API}/worker/home", headers=w1h).json()["data"]["availability"] == "online"
    photos = client.get(f"{API}/orders/{oid}/photos", headers=CUS_H).json()["data"]
    assert [p["kind"] for p in photos] == ["before", "after", "after"]

    # khách chọn tiền mặt -> thợ xác nhận thu tiền -> ví trừ hoa hồng
    client.post(f"{API}/customer/orders/{oid}/payments", json={"method": "cash"}, headers=CUS_H)
    r = client.post(f"{API}/worker/orders/{oid}/confirm-cash", headers=w1h)
    assert r.status_code == 200 and r.json()["data"]["paid"] and r.json()["data"]["earning"]["net_amount"] == 370000 - 55500
    assert client.post(f"{API}/worker/orders/{oid}/confirm-cash", headers=w1h).status_code == 400
    wallet = client.get(f"{API}/worker/wallet", headers=w1h).json()["data"]
    assert wallet["balance"] == -55500 and wallet["recent"][0]["type"] == "commission"
    s = client.get(f"{API}/worker/earnings/summary", params={"period": "today"}, headers=w1h).json()["data"]
    assert s["totals"]["net"] == 314500 and s["totals"]["cash_collected"] == 370000 and s["totals"]["orders"] == 1
    assert s["chart"][-1]["net"] == 314500 and len(s["chart"]) == 7
    assert client.get(f"{API}/worker/earnings/summary", params={"period": "month"}, headers=w1h).json()["data"]["totals"]["net"] == 314500

    # khách đánh giá -> thợ xem được
    client.post(f"{API}/customer/orders/{oid}/review", json={"rating": 5, "comment": "Thợ nhiệt tình"}, headers=CUS_H)
    rv = client.get(f"{API}/worker/reviews", headers=w1h).json()["data"]
    assert rv["summary"]["review_count"] == 1 and rv["items"][0]["customer_name"] == "Hoa"
    done = client.get(f"{API}/worker/orders", params={"group": "completed"}, headers=w1h).json()["data"]["items"]
    assert next(x for x in done if x["id"] == oid)["rating"] == 5  # thợ thấy số sao ngay ở danh sách đơn
    perf = client.get(f"{API}/worker/performance", headers=w1h).json()["data"]
    assert perf["jobs_completed"] == 1 and perf["acceptance_rate"] == 1.0 and perf["total_completed"] == 1

    # chat với khách
    assert client.post(f"{API}/orders/{oid}/messages", json={"content": "Em đã sửa xong ạ"}, headers=w1h).status_code == 201
    lst = client.get(f"{API}/worker/orders", params={"group": "history"}, headers=w1h).json()["data"]
    assert lst["items"][0]["id"] == oid and lst["items"][0]["paid"]

    # báo cáo sự cố
    assert client.post(f"{API}/worker/orders/{oid}/report", json={"reason": "Khách thanh toán chậm"}, headers=w1h).status_code == 201
    assert client.post(f"{API}/worker/orders/{oid}/report", json={"reason": "Lần 2"}, headers=w1h).status_code == 400

    # ví: rút tiền
    assert client.post(f"{API}/worker/wallet/withdrawals", json={"amount": 100000}, headers=w1h).status_code == 400  # chưa có ngân hàng
    client.put(f"{API}/worker/bank-account", json={"bank_name": "Vietcombank", "account_number": "0123456789", "account_holder": "thợ một"}, headers=w1h)
    assert client.post(f"{API}/worker/wallet/withdrawals", json={"amount": 100000}, headers=w1h).status_code == 400  # ví âm
    client.post(f"{API}/worker/wallet/topup", json={"amount": 500000}, headers=w1h)
    r = client.post(f"{API}/worker/wallet/withdrawals", json={"amount": 200000}, headers=w1h)
    assert r.status_code == 201 and r.json()["data"]["status"] == "completed" and r.json()["data"]["account_holder"] == "THỢ MỘT"
    assert client.get(f"{API}/worker/wallet", headers=w1h).json()["data"]["balance"] == -55500 + 500000 - 200000
    assert client.post(f"{API}/worker/wallet/withdrawals", json={"amount": 30000}, headers=w1h).status_code == 400  # dưới mức tối thiểu

    for wh in (w1h, w2h):
        client.patch(f"{API}/worker/availability", json={"online": False}, headers=wh)


def test_reject_next_wave_and_timeout():
    w1, w1h = _make_ready_worker(ADMIN_H, "Thợ A", 0.3, 0.3, trust=0.9)
    w2, w2h = _make_ready_worker(ADMIN_H, "Thợ B", 0.6, 0.3, trust=0.8)
    w3, w3h = _make_ready_worker(ADMIN_H, "Thợ C", 2.5, 0.3, trust=0.5)
    oid = _order(CUS_H, 0.3, 0.3)
    a, b = _offer(w1h), _offer(w2h)
    assert a and b and _offer(w3h) is None  # top-2 trước

    # cả 2 từ chối -> đợt 2 tới thợ C ngay
    client.post(f"{API}/worker/offers/{a['id']}/reject", json={"reason": "Đang bận việc khác"}, headers=w1h)
    assert _offer(w3h) is None  # còn offer của B
    client.post(f"{API}/worker/offers/{b['id']}/reject", json={"reason": "Quá xa"}, headers=w2h)
    c = _offer(w3h)
    assert c and c["order_id"] == oid and c["round"] == 2
    assert _offer(w1h) is None  # không mời lại thợ đã từ chối

    # thợ C không trả lời -> hết hạn -> không còn ai -> đơn chờ, quá hạn thì hệ thống hủy
    _sql("UPDATE order_offers SET expires_at = NOW() - interval '1 second' WHERE id=:i", i=c["id"])
    _tick()
    assert _sql("SELECT status FROM order_offers WHERE id=:i", i=c["id"]) == "expired"
    assert _sql("SELECT status FROM orders WHERE id=:o", o=oid) == "pending"
    _sql("UPDATE order_dispatches SET deadline_at = NOW() - interval '1 second' WHERE order_id=:o", o=oid)
    _tick()
    assert _sql("SELECT status FROM orders WHERE id=:o", o=oid) == "cancelled"
    notes = client.get(f"{API}/notifications", headers=CUS_H).json()["data"]["items"]
    assert any(n["reference_id"] == oid and n["type"] == "order_cancelled" for n in notes)

    # thợ tắt nhận đơn -> offer đang có bị thu hồi
    oid2 = _order(CUS_H, 0.3, 0.3)
    assert _offer(w1h)["order_id"] == oid2
    client.patch(f"{API}/worker/availability", json={"online": False}, headers=w1h)
    assert _offer(w1h) is None
    _tick()
    assert _offer(w2h)["order_id"] == oid2 or _offer(w3h)["order_id"] == oid2
    client.patch(f"{API}/customer/orders/{oid2}/cancel", json={"reason": "Không cần nữa"}, headers=CUS_H)
    assert _offer(w2h) is None and _offer(w3h) is None
    for wh in (w2h, w3h):
        client.patch(f"{API}/worker/availability", json={"online": False}, headers=wh)


def test_worker_cancel_requeues_to_other_worker():
    w1, w1h = _make_ready_worker(ADMIN_H, "Thợ Hủy", -0.4, -0.4, trust=0.9)
    w2, w2h = _make_ready_worker(ADMIN_H, "Thợ Thay", -0.8, -0.4, trust=0.6)
    _set_config("instant", max_offers=1)
    try:
        oid = _order(CUS_H, -0.4, -0.4)
        a = _offer(w1h)
        assert a and _offer(w2h) is None
        client.post(f"{API}/worker/offers/{a['id']}/accept", headers=w1h)
        client.post(f"{API}/worker/orders/{oid}/status", json={"status": "on_the_way"}, headers=w1h)
        r = client.post(f"{API}/worker/orders/{oid}/cancel", json={"reason": "Xe bị hỏng giữa đường"}, headers=w1h)
        assert r.status_code == 200 and r.json()["data"]["status"] == "pending"
        assert client.get(f"{API}/worker/home", headers=w1h).json()["data"]["availability"] == "online"
        b = _offer(w2h)
        assert b and b["order_id"] == oid and _offer(w1h) is None
        hist = [h["status"] for h in client.get(f"{API}/customer/orders/{oid}", headers=CUS_H).json()["data"]["history"]]
        assert hist == ["pending", "accepted", "on_the_way", "pending"]
        perf = client.get(f"{API}/worker/performance", headers=w1h).json()["data"]
        assert perf["jobs_cancelled_by_worker"] == 1
        client.post(f"{API}/worker/offers/{b['id']}/accept", headers=w2h)
        for st in ("on_the_way", "arrived"):
            client.post(f"{API}/worker/orders/{oid}/status", json={"status": st}, headers=w2h)
        # đã đến nơi mà hủy (khách vắng mặt) -> đơn hủy luôn
        r = client.post(f"{API}/worker/orders/{oid}/cancel", json={"reason": "Khách không có mặt"}, headers=w2h)
        assert r.json()["data"]["status"] == "cancelled"
        assert client.get(f"{API}/customer/orders/{oid}", headers=CUS_H).json()["data"]["cancel_reason"] == "[Thợ] Khách không có mặt"
    finally:
        _set_config("instant", max_offers=2)
        for wh in (w1h, w2h):
            client.patch(f"{API}/worker/availability", json={"online": False}, headers=wh)


def test_batch_mode_hungarian():
    _set_config("batch")
    try:
        w1, w1h = _make_ready_worker(ADMIN_H, "Thợ Lô 1", 5.0, 5.0, trust=0.9)
        w2, w2h = _make_ready_worker(ADMIN_H, "Thợ Lô 2", 5.0, 7.0, trust=0.9)
        _, cus2_h, _ = _register("customer")
        # Đơn A gần cả 2 thợ, đơn B chỉ gần thợ 2: tham lam theo thứ tự có thể để A lấy thợ 2,
        # Hungarian phải ghép A-thợ1, B-thợ2 (tổng điểm cao hơn, ghép được cả 2 đơn).
        oa = _order(CUS_H, 5.0, 6.2)
        ob = _order(cus2_h, 5.0, 9.5)
        assert _offer(w1h) is None and _offer(w2h) is None  # batch: chưa gửi ngay
        assert client.get(f"{API}/customer/orders/{oa}", headers=CUS_H).json()["data"]["matching_mode"] == "batch"
        with SessionLocal() as db:
            res = dispatch_service.run_batch_round(db)
        assert res.assigned == 2
        assert dict(res.pairs) == {oa: w1, ob: w2}
        assert _offer(w1h)["order_id"] == oa and _offer(w2h)["order_id"] == ob
        assert _offer(w1h)["mode"] == "batch"
        # thợ 1 từ chối -> lượt sau đơn A không còn ai (thợ 2 đang giữ offer B)
        client.post(f"{API}/worker/offers/{_offer(w1h)['id']}/reject", json={}, headers=w1h)
        with SessionLocal() as db:
            assert dispatch_service.run_batch_round(db).assigned == 0
        for oid, h in ((oa, CUS_H), (ob, cus2_h)):
            client.patch(f"{API}/customer/orders/{oid}/cancel", json={"reason": "Test xong"}, headers=h)
        for wh in (w1h, w2h):
            client.patch(f"{API}/worker/availability", json={"online": False}, headers=wh)
    finally:
        _set_config("instant", max_offers=2)


def test_auto_mode_hybrid():
    """Chế độ auto: trong cùng 1 nhịp, nhóm đơn tranh cùng thợ -> Hungarian; đơn đứng một mình -> tức thời top-k."""
    _set_config("auto", max_offers=2)
    try:
        w1, w1h = _make_ready_worker(ADMIN_H, "Thợ Auto 1", -10.0, -10.0, trust=0.9)
        w2, w2h = _make_ready_worker(ADMIN_H, "Thợ Auto 2", -10.0, -8.0, trust=0.9)
        w3, w3h = _make_ready_worker(ADMIN_H, "Thợ Auto 3", -25.0, -25.0, trust=0.8)
        w4, w4h = _make_ready_worker(ADMIN_H, "Thợ Auto 4", -25.0, -24.0, trust=0.7)
        _, cus2_h, _ = _register("customer")
        _, cus3_h, _ = _register("customer")
        oa = _order(CUS_H, -10.0, -8.8)  # gần cả thợ 1 và thợ 2
        ob = _order(cus2_h, -10.0, -5.5)  # chỉ gần thợ 2 hơn -> tranh thợ 2 với đơn A
        oc = _order(cus3_h, -25.0, -24.5)  # khu khác, không tranh với ai
        assert all(_offer(h) is None for h in (w1h, w2h, w3h, w4h))  # auto: chờ nhịp điều phối, không gửi ngay
        with SessionLocal() as db:
            res = dispatch_service.run_auto_round(db)
        assert res.orders == 3 and res.instant_orders == 1 and res.batch_groups == 1 and res.batch.assigned == 2
        assert dict(res.batch.pairs) == {oa: w1, ob: w2}  # Hungarian: tối ưu toàn cục, đủ cả 2 đơn
        assert _offer(w1h)["order_id"] == oa and _offer(w1h)["mode"] == "batch"
        assert _offer(w2h)["order_id"] == ob
        # đơn đứng một mình: gửi ngay cho top-k (k=2) thợ quanh đó
        assert _offer(w3h)["order_id"] == oc and _offer(w4h)["order_id"] == oc and _offer(w3h)["mode"] == "instant"
        modes = {oid: client.get(f"{API}/customer/orders/{oid}", headers=h).json()["data"]["matching_mode"]
                 for oid, h in ((oa, CUS_H), (oc, cus3_h))}
        assert modes == {oa: "batch", oc: "instant"}  # đơn ghi chế độ thực tế đã dùng
        for oid, h in ((oa, CUS_H), (ob, cus2_h), (oc, cus3_h)):
            client.patch(f"{API}/customer/orders/{oid}/cancel", json={"reason": "Test xong"}, headers=h)
        for wh in (w1h, w2h, w3h, w4h):
            client.patch(f"{API}/worker/availability", json={"online": False}, headers=wh)
    finally:
        _set_config("instant", max_offers=2)


def test_competition_groups_union_find():
    from app.matching.grouping import competition_groups

    # đơn 0-1 chung thợ 10, đơn 1-2 chung thợ 11 (nối bắc cầu) -> 1 nhóm; đơn 3 riêng; đơn 4 không có ứng viên
    groups = competition_groups([{10: 0}, {10: 0, 11: 0}, {11: 0, 12: 0}, {20: 0}, {}])
    assert sorted(groups) == [[0, 1, 2], [3], [4]]


def test_scheduled_order_start_window_conflict_and_quote_rule():
    """Đơn hẹn trước: lời mời ghi rõ giờ hẹn; chỉ được bắt đầu di chuyển trong 60 phút trước giờ hẹn;
    thợ đã có lịch hẹn trùng giờ không nhận lời mời mới; chỉ báo giá phát sinh sau khi đã đến nơi."""
    w1, w1h = _make_ready_worker(ADMIN_H, "Thợ Hẹn Một", -5.0, 5.0, trust=0.9)
    w2, w2h = _make_ready_worker(ADMIN_H, "Thợ Hẹn Hai", -5.0, 5.5, trust=0.5)
    when = (now_vn() + timedelta(days=2)).replace(hour=19, minute=0, second=0, microsecond=0)
    oid = _order(CUS_H, -5.0, 5.0, scheduled_at=when.isoformat() + "+07:00")
    a = _offer(w1h)
    assert a and a["order_id"] == oid and a["scheduled_at"]
    assert client.post(f"{API}/worker/offers/{a['id']}/accept", headers=w1h).status_code == 200
    home = client.get(f"{API}/worker/home", headers=w1h).json()["data"]
    assert home["availability"] == "online" and home["upcoming"][0]["id"] == oid  # lịch còn xa: vẫn nhận đơn khác
    assert "demand" not in home

    # còn xa giờ hẹn: chưa được bắt đầu di chuyển, app biết giờ sớm nhất để hiển thị
    d = client.get(f"{API}/worker/orders/{oid}", headers=w1h).json()["data"]
    assert d["start_available_at"].startswith((when - timedelta(minutes=60)).strftime("%Y-%m-%dT%H:%M"))
    r = client.post(f"{API}/worker/orders/{oid}/status", json={"status": "on_the_way"}, headers=w1h)
    assert r.status_code == 400 and "18:00" in r.json()["detail"]
    # chưa đến nơi -> chưa báo giá phát sinh
    assert d["can_quote"] is False
    r = client.post(f"{API}/worker/orders/{oid}/extra-quotes", json={"description": "Thay dây điện", "amount": 50000}, headers=w1h)
    assert r.status_code == 400 and "đến nơi" in r.json()["detail"]

    # đơn hẹn thứ 2 lệch 30 phút: thợ 1 đã có lịch trùng giờ -> chỉ thợ 2 được mời
    oid2 = _order(CUS_H, -5.0, 5.2, scheduled_at=(when + timedelta(minutes=30)).isoformat() + "+07:00")
    b1, b2 = _offer(w1h), _offer(w2h)
    assert not (b1 and b1["order_id"] == oid2)
    assert b2 and b2["order_id"] == oid2
    client.patch(f"{API}/customer/orders/{oid2}/cancel", json={"reason": "Đổi lịch"}, headers=CUS_H)

    # còn 30 phút tới giờ hẹn -> được bắt đầu di chuyển; đang đi vẫn chưa báo giá được
    _sql("UPDATE orders SET scheduled_at=:t WHERE id=:o", t=now_vn() + timedelta(minutes=30), o=oid)
    d = client.get(f"{API}/worker/orders/{oid}", headers=w1h).json()["data"]
    assert d["start_available_at"] is None
    r = client.post(f"{API}/worker/orders/{oid}/status", json={"status": "on_the_way"}, headers=w1h)
    assert r.status_code == 200 and r.json()["data"]["can_quote"] is False
    r = client.post(f"{API}/worker/orders/{oid}/status", json={"status": "arrived"}, headers=w1h)
    assert r.status_code == 200 and r.json()["data"]["can_quote"] is True

    assert client.post(f"{API}/worker/orders/{oid}/cancel", json={"reason": "Dọn dữ liệu test"}, headers=w1h).status_code == 200
    _sql("UPDATE orders SET status='cancelled' WHERE id IN (:a, :b) AND status <> 'completed'", a=oid, b=oid2)
    for wh in (w1h, w2h):
        client.patch(f"{API}/worker/availability", json={"online": False}, headers=wh)


def test_worker_level_thresholds():
    from app.services.worker_service import worker_level

    assert worker_level(0, None)["key"] == "dong"
    assert worker_level(30, 4.6)["key"] == "bac"
    assert worker_level(30, 4.4)["key"] == "dong"  # đủ số đơn nhưng đánh giá chưa đạt
    assert worker_level(150, 4.8)["key"] == "vang"
    top = worker_level(350, 4.9)
    assert top["key"] == "kim_cuong" and top["next_name"] is None and top["progress"] == 1.0
    mid = worker_level(65, 4.8)
    assert mid["key"] == "bac" and mid["next_name"] == "Thợ Vàng" and 0 < mid["progress"] < 1


def test_home_has_location_and_level():
    wid, wh = _make_ready_worker(ADMIN_H, "Thợ Trang Chủ", 40.0, 40.0)
    h = client.get(f"{API}/worker/home", headers=wh).json()["data"]
    lat, lng = off(40.0, 40.0)
    assert abs(h["location"]["latitude"] - lat) < 1e-6 and abs(h["location"]["longitude"] - lng) < 1e-6
    assert h["service_radius_km"] > 0
    assert h["level"]["key"] == "dong" and h["level"]["next_name"] == "Thợ Bạc"
    assert h["week"]["completed"] == 0 and h["week"]["net_income"] == 0
    assert "demand" not in h  # trang chủ không còn bản đồ vùng nhiều đơn
    client.patch(f"{API}/worker/availability", json={"online": False}, headers=wh)
    assert client.get(f"{API}/worker/schedule", headers=wh).status_code == 404  # đã bỏ khung giờ làm việc


def test_earnings_compare_same_period():
    """So sánh thu nhập với cùng kỳ: kỳ trước chỉ tính tới đúng thời điểm tương ứng."""
    from datetime import datetime as dt

    from app.controllers.worker_finance_controller import _windows

    now = dt(2026, 10, 13, 15, 0)  # Thứ 3
    start, end, (ps, pe) = _windows("week", now)
    assert start == dt(2026, 10, 12) and ps == dt(2026, 10, 5) and pe == dt(2026, 10, 6, 15, 0)
    start, end, (ps, pe) = _windows("today", now)
    assert ps == dt(2026, 10, 12) and pe == dt(2026, 10, 12, 15, 0)


def test_seed_media_is_png_and_upgrades_old_svg():
    """Ảnh mẫu phải là PNG (React Native không hiển thị SVG); CSDL seed bản cũ (.svg) được đổi sang .png."""
    from pathlib import Path as P

    from app.config import settings
    from db.seed_media import NAMES, seed_media_urls, upgrade_svg_urls

    urls = seed_media_urls()
    assert set(urls) == set(NAMES)
    for name, url in urls.items():
        assert url.endswith(f"/media/seed/{name}.png")
        f = P(settings.media_dir) / "seed" / f"{name}.png"
        assert f.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"

    wid, _ = _make_ready_worker(ADMIN_H, "Thợ Ảnh Mẫu", 60.0, 60.0)
    old = urls["job-before"].replace(".png", ".svg")
    other = "http://192.168.1.5:8000/media/2026/10/giay-to.svg"  # không phải ảnh mẫu -> giữ nguyên
    with SessionLocal() as db:
        db.execute(text("UPDATE worker_documents SET file_url = :u WHERE worker_id = :w AND doc_type = 'id_card_front'"), {"u": old, "w": wid})
        db.execute(text("UPDATE worker_documents SET file_url = :u WHERE worker_id = :w AND doc_type = 'portrait'"), {"u": other, "w": wid})
        db.commit()
        assert upgrade_svg_urls(db) >= 1
        db.commit()
        rows = dict(db.execute(text("SELECT doc_type, file_url FROM worker_documents WHERE worker_id = :w"), {"w": wid}).all())
    assert rows["id_card_front"] == urls["job-before"]
    assert rows["portrait"] == other
