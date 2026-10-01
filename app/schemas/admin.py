from typing import Literal

from pydantic import BaseModel, model_validator

from app.schemas.user import UserOut
from app.schemas.worker import WorkerDocumentOut, WorkerProfileOut


class UserStatusUpdate(BaseModel):
    status: Literal["active", "blocked"]


class ReviewDocumentRequest(BaseModel):
    status: Literal["approved", "rejected"]
    reject_reason: str | None = None

    @model_validator(mode="after")
    def check_reason(self):
        if self.status == "rejected" and not self.reject_reason:
            raise ValueError("Cần nhập lý do từ chối")
        return self


class WorkerVerificationRequest(BaseModel):
    status: Literal["approved", "rejected"]


class AdminWorkerItem(BaseModel):
    user: UserOut
    profile: WorkerProfileOut


class AdminWorkerDetail(BaseModel):
    user: UserOut
    profile: WorkerProfileOut
    documents: list[WorkerDocumentOut]