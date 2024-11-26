from typing import Optional

from sqlmodel import Field, SQLModel, create_engine


class Vocab(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    word: str
    context: Optional[str] = None
    source: Optional[str] = None
    done: bool = False


sqlite_fname = 'database.db'
sqlite_url = f'sqlite:///{sqlite_fname}'

engine = create_engine(sqlite_url, echo=True)  # for production, remove echo


def create_db_and_tables():
    SQLModel.metadata.create_all(engine)


if __name__ == '__main__':
    create_db_and_tables()