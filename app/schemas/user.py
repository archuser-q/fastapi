from datetime import datetime

from pydantic import BaseModel, ConfigDict


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    phone: str
    email: str | None
    full_name: str
    avatar_url: str | None
    role: str
    status: str
    created_at: datetime