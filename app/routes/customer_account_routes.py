"""App khách hàng: hồ sơ và sổ địa chỉ."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.controllers import customer_account_controller as ctl
from app.database import get_db
from app.middleware.auth import require_roles
from app.models import User
from app.schemas.customer import AddressCreate, AddressUpdate, ProfileUpdate

customer_only = require_roles("customer")

router = APIRouter(prefix="/customer", tags=["Customer App - Account"])


@router.patch("/profile")
def update_profile(data: ProfileUpdate, db: Session = Depends(get_db), user: User = Depends(customer_only)):
    return ctl.update_profile(db, user, data)


@router.get("/addresses")
def list_addresses(db: Session = Depends(get_db), user: User = Depends(customer_only)):
    return ctl.list_addresses(db, user)


@router.post("/addresses", status_code=201)
def create_address(data: AddressCreate, db: Session = Depends(get_db), user: User = Depends(customer_only)):
    return ctl.create_address(db, user, data)


@router.patch("/addresses/{address_id}")
def update_address(
    address_id: int, data: AddressUpdate, db: Session = Depends(get_db), user: User = Depends(customer_only)
):
    return ctl.update_address(db, user, address_id, data)


@router.delete("/addresses/{address_id}")
def delete_address(address_id: int, db: Session = Depends(get_db), user: User = Depends(customer_only)):
    return ctl.delete_address(db, user, address_id)
