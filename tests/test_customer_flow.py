import uuid
from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.database import SessionLocal
from app.main import app

client = TestClient(app)
API = "/api/v1"


def _phone():
    return "09" + str(uuid.uuid4().int)[:8]


def _register_login(role="customer"):
    phone = _phone()
    r = client.post(f"{API}/auth/register", json={"phone": phone, "password": "12345678", "full_name": f"Test {role}", "role": role})
    assert r.status_code == 201, r.text
    r = client.post(f"{API}/auth/login", json={"phone": phone, "password": "12345678"})
    client.cookies.clear()  # chỉ dùng Bearer để tách 2 user
    return r.json()["data"]["user"]["id"], {"Authorization": f"Bearer {r.json()['data']['access_token']}"}


def _sql(q, **kw):
    with SessionLocal() as db:
        res = db.execute(text(q), kw)
        db.commit()
        try:
            return res.scalar()
        except Exception:
            return None


def setup_module():
    global SERVICE_ID, CUS_ID, CUS, WK_ID, WK
    cat = _sql("INSERT INTO service_categories(name) VALUES ('Điện nước') RETURNING id")
    SERVICE_ID = _sql("INSERT INTO services(category_id,name,base_price,unit) VALUES (:c,'Sửa ống nước',200000,'lần') RETURNING id", c=cat)
    CUS_ID, CUS = _register_login("customer")
    WK_ID, WK = _register_login("worker")
    _sql("UPDATE worker_profiles SET verification_status='approved', availability='online', current_latitude=21.03, current_longitude=105.78 WHERE user_id=:w", w=WK_ID)
    _sql("INSERT INTO worker_services VALUES (:w,:s)", w=WK_ID, s=SERVICE_ID)


def test_catalog_public():
    r = client.get(f"{API}/catalog/categories")
    assert r.status_code == 200 and any(c["services_count"] >= 1 for c in r.json()["data"])
    r = client.get(f"{API}/catalog/services", params={"keyword": "ống"})
    assert any(s["id"] == SERVICE_ID for s in r.json()["data"])


def test_profile_and_addresses():
    r = client.patch(f"{API}/customer/profile", json={"full_name": "Nguyễn Văn A"}, headers=CUS)
    assert r.json()["data"]["full_name"] == "Nguyễn Văn A"

    a1 = client.post(f"{API}/customer/addresses", json={"label": "Nhà", "address_line": "1 Cầu Giấy", "latitude": 21.03, "longitude": 105.79}, headers=CUS).json()["data"]
    assert a1["is_default"] is True  # địa chỉ đầu tự mặc định
    a2 = client.post(f"{API}/customer/addresses", json={"address_line": "2 Xuân Thủy", "latitude": 21.04, "longitude": 105.78, "is_default": True}, headers=CUS).json()["data"]
    lst = client.get(f"{API}/customer/addresses", headers=CUS).json()["data"]
    assert [a["is_default"] for a in lst] == [True, False] and lst[0]["id"] == a2["id"]
    client.delete(f"{API}/customer/addresses/{a2['id']}", headers=CUS)
    lst = client.get(f"{API}/customer/addresses", headers=CUS).json()["data"]
    assert lst[0]["id"] == a1["id"] and lst[0]["is_default"]

    # thợ không gọi được API khách
    assert client.get(f"{API}/customer/addresses", headers=WK).status_code == 403


def test_full_order_flow():
    addr = client.get(f"{API}/customer/addresses", headers=CUS).json()["data"][0]
    r = client.post(f"{API}/customer/orders", json={"service_id": SERVICE_ID, "address_id": addr["id"], "description": "Rò nước bồn rửa"}, headers=CUS)
    assert r.status_code == 201, r.text
    order = r.json()["data"]
    oid = order["id"]
    assert order["status"] == "pending" and order["estimated_price"] == 200000 and order["can_cancel"]

    # chưa có thợ thì chưa chat được
    assert client.post(f"{API}/orders/{oid}/messages", json={"content": "hi"}, headers=CUS).status_code == 400

    # giả lập app thợ nhận đơn
    _sql("UPDATE orders SET worker_id=:w, status='in_progress', accepted_at=NOW() WHERE id=:o", w=WK_ID, o=oid)

    # chat 2 chiều
    assert client.post(f"{API}/orders/{oid}/messages", json={"content": "Anh tới chưa?"}, headers=CUS).status_code == 201
    assert client.post(f"{API}/orders/{oid}/messages", json={"content": "5 phút nữa"}, headers=WK).status_code == 201
    msgs = client.get(f"{API}/orders/{oid}/messages", headers=CUS).json()["data"]
    assert [m["is_mine"] for m in msgs] == [True, False]
    assert client.post(f"{API}/orders/{oid}/messages/read", headers=CUS).json()["data"]["updated"] == 1

    # tracking
    t = client.get(f"{API}/customer/orders/{oid}/tracking", headers=CUS).json()["data"]
    assert t["worker_latitude"] == 21.03

    # báo giá phát sinh
    q = _sql("INSERT INTO order_extra_quotes(order_id,worker_id,description,amount) VALUES (:o,:w,'Thay van',50000) RETURNING id", o=oid, w=WK_ID)
    r = client.post(f"{API}/customer/orders/{oid}/extra-quotes/{q}/approve", headers=CUS)
    assert r.json()["data"]["total_amount"] == 250000
    assert client.post(f"{API}/customer/orders/{oid}/extra-quotes/{q}/reject", headers=CUS).status_code == 400

    # đang làm thì không huỷ được
    assert client.patch(f"{API}/customer/orders/{oid}/cancel", json={"reason": "đổi ý"}, headers=CUS).status_code == 400
    # chưa xong thì chưa thanh toán
    assert client.post(f"{API}/customer/orders/{oid}/payments", json={"method": "cash"}, headers=CUS).status_code == 400

    # giả lập thợ hoàn thành + tạo bảo hành
    _sql("UPDATE orders SET status='completed', completed_at=NOW() WHERE id=:o", o=oid)
    w = _sql("INSERT INTO warranties(order_id,terms,start_date,end_date) VALUES (:o,'30 ngày',:s,:e) RETURNING id",
             o=oid, s=date.today(), e=date.today() + timedelta(days=30))

    # thanh toán: chọn cash rồi đổi sang momo
    p1 = client.post(f"{API}/customer/orders/{oid}/payments", json={"method": "cash"}, headers=CUS).json()["data"]
    assert p1["amount"] == 250000
    p2 = client.post(f"{API}/customer/orders/{oid}/payments", json={"method": "momo"}, headers=CUS).json()["data"]
    r = client.post(f"{API}/customer/payments/{p2['id']}/sandbox-confirm", headers=CUS)
    assert r.json()["data"]["status"] == "success", r.text
    pays = client.get(f"{API}/customer/orders/{oid}/payments", headers=CUS).json()["data"]
    assert [p["status"] for p in pays] == ["failed", "success"]
    assert client.post(f"{API}/customer/orders/{oid}/payments", json={"method": "cash"}, headers=CUS).status_code == 400

    # đánh giá
    assert client.post(f"{API}/customer/orders/{oid}/review", json={"rating": 5, "comment": "Nhanh"}, headers=CUS).status_code == 201
    assert client.post(f"{API}/customer/orders/{oid}/review", json={"rating": 4}, headers=CUS).status_code == 400
    prof = client.get(f"{API}/customer/workers/{WK_ID}", headers=CUS).json()["data"]
    assert prof["review_count"] == 1 and prof["recent_reviews"][0]["rating"] == 5

    detail = client.get(f"{API}/customer/orders/{oid}", headers=CUS).json()["data"]
    assert not detail["can_pay"] and not detail["can_review"] and detail["warranty"]["status"] == "active"
    assert [h["status"] for h in detail["history"]] == ["pending"]

    # bảo hành -> sinh khiếu nại; khiếu nại trùng bị chặn
    r = client.post(f"{API}/customer/warranties/{w}/claim", json={"description": "Lại rò nước"}, headers=CUS)
    assert r.status_code == 201, r.text
    assert client.post(f"{API}/customer/orders/{oid}/complaints", json={"reason": "Làm ẩu"}, headers=CUS).status_code == 400
    assert client.get(f"{API}/customer/complaints", headers=CUS).json()["data"]["total"] == 1

    # thợ nhận được thông báo
    n = client.get(f"{API}/notifications/unread-count", headers=WK).json()["data"]["unread"]
    assert n >= 4
    client.patch(f"{API}/notifications/read-all", headers=WK)
    assert client.get(f"{API}/notifications/unread-count", headers=WK).json()["data"]["unread"] == 0


def test_cancel_and_list():
    r = client.post(f"{API}/customer/orders", json={"service_id": SERVICE_ID, "address_line": "5 Láng", "latitude": 21.0, "longitude": 105.8}, headers=CUS)
    oid = r.json()["data"]["id"]
    r = client.patch(f"{API}/customer/orders/{oid}/cancel", json={"reason": "Không cần nữa"}, headers=CUS)
    assert r.json()["data"]["status"] == "cancelled"
    assert client.get(f"{API}/customer/orders", params={"group": "cancelled"}, headers=CUS).json()["data"]["total"] == 1
    assert client.get(f"{API}/customer/orders", headers=CUS).json()["data"]["total"] == 2

    # lịch hẹn trong quá khứ bị chặn
    r = client.post(f"{API}/customer/orders", json={"service_id": SERVICE_ID, "address_line": "5 Láng", "latitude": 21.0, "longitude": 105.8, "scheduled_at": "2020-01-01T10:00:00+07:00"}, headers=CUS)
    assert r.status_code == 400

    # khách khác không xem được đơn
    _, other = _register_login("customer")
    assert client.get(f"{API}/customer/orders/{oid}", headers=other).status_code == 404


def test_device_token():
    tok = "fcm-" + uuid.uuid4().hex
    assert client.post(f"{API}/notifications/device-tokens", json={"token": tok, "platform": "android"}, headers=CUS).status_code == 200
    assert client.delete(f"{API}/notifications/device-tokens/{tok}", headers=CUS).status_code == 200


def test_my_reviews_and_payments():
    r = client.get(f"{API}/customer/reviews", headers=CUS).json()["data"]
    assert r["total"] == 1 and r["items"][0]["rating"] == 5 and r["items"][0]["service_name"] == "Sửa ống nước"
    p = client.get(f"{API}/customer/payments", headers=CUS).json()["data"]
    assert p["total"] == 2 and p["items"][0]["status"] == "success"


def test_simulate_worker_script():
    import subprocess, sys
    oid = client.post(f"{API}/customer/orders", json={"service_id": SERVICE_ID, "address_line": "9 Láng", "latitude": 21.0, "longitude": 105.8}, headers=CUS).json()["data"]["id"]
    for step in ["accepted", "on_the_way"]:
        out = subprocess.run([sys.executable, "-m", "scripts.simulate_worker", str(oid), step], capture_output=True, text=True)
        assert "OK" in out.stdout, out.stderr
    t = client.get(f"{API}/customer/orders/{oid}/tracking", headers=CUS).json()["data"]
    assert t["status"] == "on_the_way" and t["worker_latitude"] is not None
