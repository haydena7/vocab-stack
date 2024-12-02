from typing import Optional

from sqlmodel import Field, SQLModel

class Vocab(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    word: str = Field(index=True)
    context: Optional[str] = None
    source: Optional[str] = None
    freq: Optional[float] = Field(default=None, index=True)  # ¿data type correct?