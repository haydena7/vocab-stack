from typing import Optional

from starlette.applications import Starlette
from starlette.routing import Route, Mount
from starlette.requests import Request
from starlette.responses import RedirectResponse
from starlette.templating import Jinja2Templates
from starlette.staticfiles import StaticFiles
from sqlmodel import Field, Session, SQLModel, or_, create_engine, select, col


class Vocab(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    word: str = Field(index=True)
    context: Optional[str] = None
    source: Optional[str] = None
    freq: Optional[float] = Field(default=None, index=True)  # ¿data type correct?


sqlite_fname = 'database.db'
sqlite_url = f'sqlite:///{sqlite_fname}'

engine = create_engine(sqlite_url, echo=True)


def create_db_and_tables():
    SQLModel.metadata.create_all(engine)


templates = Jinja2Templates(directory='templates')


async def homepage(request: Request):
    return RedirectResponse(url='/vocabs', status_code=301)


async def vocabs(request: Request):
    search = request.query_params.get('q')
    with Session(engine) as session:
        if search is not None:
            vocabs_set = session.exec(select(Vocab).where(or_(
                col(Vocab.word).icontains(search),
                col(Vocab.context).icontains(search),
                col(Vocab.source).icontains(search),
            ))).all()
        else:
            vocabs_set = session.exec(select(Vocab)).all()
    return templates.TemplateResponse(request, 'index.html', {'vocabs': vocabs_set})


async def vocabs_new_get(request: Request):
    return templates.TemplateResponse(request, 'new.html', {'vocab': Vocab()})


async def vocabs_new(request: Request):
    async with request.form() as form:
        with Session(engine) as session:
            v = Vocab(
                word=form.get('word'),
                context=form.get('context'),
                source=form.get('source')
            )
            try:
                session.add(v)
                session.commit()
                # IMPLEMENT flash('Created New Vocab!')
                return RedirectResponse(url='/vocabs', status_code=303)
            except Exception as e:
                session.rollback()
                print(f'An error occurred: {e}')
                return templates.TemplateResponse(request, 'new.html', {'vocab': v})


routes = [
    Route('/', homepage),
    Route('/vocabs', vocabs),
    Route('/vocabs/new', vocabs_new_get, methods=['GET']),
    Route('/vocabs/new', vocabs_new, methods=['POST']),
    Mount('/static', StaticFiles(directory='static'), name='static'),
]

on_startup = [
    create_db_and_tables,
]

app = Starlette(debug=True, routes=routes, on_startup=on_startup)