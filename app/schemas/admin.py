from pydantic import BaseModel, EmailStr, Field


class CreateStaffRequest(BaseModel):
    phone: str = Field(pattern=r"^0\d{9}$")
    password: str = Field(min_length=8, max_length=72)
    full_name: str = Field(min_length=1, max_length=150)
    email: EmailStr | None = None