from typing import Any, Optional

from pydantic import BaseModel, Field


class Exchange(BaseModel):
    question: str = Field(max_length=500)
    answer: str = Field(max_length=2000)


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    # The browser sends the last few exchanges back with each question; nothing
    # about a conversation is stored on the server.
    history: list[Exchange] = Field(default_factory=list, max_length=10)


class AskResponse(BaseModel):
    answered: bool
    stage: str
    answer: str
    resolved_question: str = ""
    sql: Optional[str] = None
    columns: list[str] = []
    rows: list[list[Any]] = []
    truncated: bool = False
    calls_used: int = 0
    detail: Optional[str] = None
    warning: Optional[str] = None


class AccessInfo(BaseModel):
    is_admin: bool
    restricted: bool          # may ask about salary / payroll (intelligence.approve + HR access)
    modules: list[str]        # display names of the modules this user may ask about


class StatusResponse(BaseModel):
    llm_configured: bool
    database_configured: bool
    rows_sent_to_llm: bool
    model: str
    access: AccessInfo
