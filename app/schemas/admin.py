from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

class PermissionUpdateRequest(BaseModel):
    role_name: str = Field(..., example="LOAN_OFFICER")
    module_code: str = Field(..., example="A1")
    is_allowed: bool

class PolicyDocumentResponse(BaseModel):
    document_id: int
    title: str
    filename: str
    category: Optional[str]
    file_path: str
    version: str
    status: str
    uploaded_by: Optional[str]
    uploaded_at: datetime

    class Config:
        from_attributes = True