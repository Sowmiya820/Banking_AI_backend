from pydantic import BaseModel, EmailStr
from typing import Literal


class UserBase(BaseModel):
    username: str
    email: EmailStr


class UserCreate(UserBase):
    password: str
    role_name: Literal["LOAN_OFFICER", "RELATIONSHIP_MANAGER", "ADMIN"] = "LOAN_OFFICER"


class UserResponse(UserBase):
    user_id: int
    role_name: str
    is_active: bool

    class Config:
        from_attributes = True