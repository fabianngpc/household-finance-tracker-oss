from pydantic import BaseModel


class LinkCodeOut(BaseModel):
    code: str
    expires_in_minutes: int
