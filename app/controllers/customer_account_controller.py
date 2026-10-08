from fastapi import HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models import CustomerAddress, DeviceToken, User
from app.schemas.customer import AddressCreate, AddressOut, AddressUpdate, DeviceTokenCreate, ProfileUpdate
from app.schemas.user import UserOut
from app.utils.response import success

MAX_ADDRESSES = 10


# ---------- Hồ sơ ----------


def update_profile(db: Session, user: User, data: ProfileUpdate):
    fields = data.model_dump(exclude_unset=True)
    if "email" in fields and fields["email"] and fields["email"] != user.email:
        if db.scalar(select(User.id).where(User.email == fields["email"], User.id != user.id)):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Email đã được sử dụng")
    if "full_name" in fields and not fields["full_name"]:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Họ tên không được trống")

    for key, value in fields.items():
        setattr(user, key, value)
    db.commit()
    db.refresh(user)
    return success(UserOut.model_validate(user), "Đã cập nhật hồ sơ")


def register_device_token(db: Session, user: User, data: DeviceTokenCreate):
    # Token là duy nhất: nếu máy đổi tài khoản thì chuyển token sang user mới
    existing = db.scalar(select(DeviceToken).where(DeviceToken.token == data.token))
    if existing:
        existing.user_id = user.id
        existing.platform = data.platform
    else:
        db.add(DeviceToken(user_id=user.id, token=data.token, platform=data.platform))
    db.commit()
    return success(message="Đã đăng ký thiết bị")


def remove_device_token(db: Session, user: User, token: str):
    item = db.scalar(
        select(DeviceToken).where(DeviceToken.token == token, DeviceToken.user_id == user.id)
    )
    if item:
        db.delete(item)
        db.commit()
    return success(message="Đã gỡ thiết bị")


# ---------- Địa chỉ ----------


def _out(a: CustomerAddress) -> AddressOut:
    return AddressOut(
        id=a.id,
        label=a.label,
        address_line=a.address_line,
        latitude=a.latitude,
        longitude=a.longitude,
        is_default=a.is_default,
        created_at=a.created_at,
    )


def _get_address(db: Session, user: User, address_id: int) -> CustomerAddress:
    a = db.get(CustomerAddress, address_id)
    if not a or a.customer_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy địa chỉ")
    return a


def _clear_default(db: Session, user: User) -> None:
    db.execute(
        update(CustomerAddress)
        .where(CustomerAddress.customer_id == user.id, CustomerAddress.is_default.is_(True))
        .values(is_default=False)
    )


def list_addresses(db: Session, user: User):
    rows = db.scalars(
        select(CustomerAddress)
        .where(CustomerAddress.customer_id == user.id)
        .order_by(CustomerAddress.is_default.desc(), CustomerAddress.created_at.desc())
    ).all()
    return success([_out(a) for a in rows])


def create_address(db: Session, user: User, data: AddressCreate):
    count = db.scalar(
        select(func.count()).select_from(CustomerAddress).where(CustomerAddress.customer_id == user.id)
    )
    if count >= MAX_ADDRESSES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Tối đa {MAX_ADDRESSES} địa chỉ")

    # Địa chỉ đầu tiên tự thành mặc định
    is_default = data.is_default or count == 0
    if is_default:
        _clear_default(db, user)
    a = CustomerAddress(customer_id=user.id, **data.model_dump(exclude={"is_default"}), is_default=is_default)
    db.add(a)
    db.commit()
    db.refresh(a)
    return success(_out(a), "Đã thêm địa chỉ")


def update_address(db: Session, user: User, address_id: int, data: AddressUpdate):
    a = _get_address(db, user, address_id)
    fields = data.model_dump(exclude_unset=True)
    if fields.get("is_default"):
        _clear_default(db, user)
    elif fields.get("is_default") is False and a.is_default:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Hãy chọn địa chỉ khác làm mặc định")
    if "address_line" in fields and not fields["address_line"]:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Địa chỉ không được trống")

    for key, value in fields.items():
        setattr(a, key, value)
    db.commit()
    db.refresh(a)
    return success(_out(a), "Đã cập nhật địa chỉ")


def delete_address(db: Session, user: User, address_id: int):
    a = _get_address(db, user, address_id)
    was_default = a.is_default
    db.delete(a)
    db.flush()
    if was_default:
        # Chuyển mặc định sang địa chỉ mới nhất còn lại
        nxt = db.scalar(
            select(CustomerAddress)
            .where(CustomerAddress.customer_id == user.id)
            .order_by(CustomerAddress.created_at.desc())
            .limit(1)
        )
        if nxt:
            nxt.is_default = True
    db.commit()
    return success(message="Đã xóa địa chỉ")
