from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

MAX_PRICE = 100_000_000


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


# ---------- Danh mục ----------


class CategoryItem(BaseModel):
    id: int
    parent_id: int | None
    name: str
    description: str | None
    icon_url: str | None
    is_active: bool
    services_total: int
    services_active: int


class CategoryCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    description: str | None = Field(default=None, max_length=1000)
    icon_url: str | None = Field(default=None, max_length=500)
    parent_id: int | None = None

    _strip = field_validator("name", "description", "icon_url")(_clean)


class CategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=100)
    description: str | None = Field(default=None, max_length=1000)
    icon_url: str | None = Field(default=None, max_length=500)
    is_active: bool | None = None

    _strip = field_validator("name", "description", "icon_url")(_clean)


# ---------- Dịch vụ ----------


class ServiceItem(BaseModel):
    id: int
    category_id: int
    category_name: str
    name: str
    description: str | None
    base_price: int
    unit: str | None
    is_active: bool
    workers: int
    orders_30d: int
    avg_final_price_30d: int | None


class ServiceCreate(BaseModel):
    category_id: int
    name: str = Field(min_length=2, max_length=150)
    description: str | None = Field(default=None, max_length=2000)
    base_price: int = Field(gt=0, le=MAX_PRICE)
    unit: str | None = Field(default=None, max_length=30)
    is_active: bool = True

    _strip = field_validator("name", "description", "unit")(_clean)


class ServiceUpdate(BaseModel):
    category_id: int | None = None
    name: str | None = Field(default=None, min_length=2, max_length=150)
    description: str | None = Field(default=None, max_length=2000)
    base_price: int | None = Field(default=None, gt=0, le=MAX_PRICE)
    unit: str | None = Field(default=None, max_length=30)
    is_active: bool | None = None

    _strip = field_validator("name", "description", "unit")(_clean)


class BulkPriceUpdate(BaseModel):
    service_ids: list[int] = Field(min_length=1, max_length=500)
    mode: Literal["percent", "amount"]
    value: float
    round_to: Literal[1, 1000, 5000, 10000] = 1000

    @model_validator(mode="after")
    def check_value(self):
        if self.value == 0:
            raise ValueError("Mức điều chỉnh phải khác 0")
        if self.mode == "percent" and not -90 <= self.value <= 500:
            raise ValueError("Phần trăm điều chỉnh phải từ -90% đến 500%")
        if self.mode == "amount" and abs(self.value) > MAX_PRICE:
            raise ValueError("Số tiền điều chỉnh quá lớn")
        return self


class BulkPriceChange(BaseModel):
    id: int
    name: str
    old_price: int
    new_price: int


class BulkPriceResult(BaseModel):
    updated: int
    changes: list[BulkPriceChange]
    applied_at: datetime
