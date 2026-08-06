"""Pydantic schemas for category request/response models."""

from pydantic import BaseModel


class CategoryCreate(BaseModel):
    name: str
    color: str
    icon: str


class CategoryUpdate(BaseModel):
    name: str | None = None
    color: str | None = None
    icon: str | None = None


class CategoryOut(BaseModel):
    id: int
    name: str
    color: str
    icon: str
    is_protected: bool
    expense_count: int

    model_config = {"from_attributes": True}
