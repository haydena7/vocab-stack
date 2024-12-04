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
            stmt = select(Vocab).where(or_(
                col(Vocab.word).icontains(search),
                col(Vocab.context).icontains(search),
                col(Vocab.source).icontains(search),
            ))
        else:
            stmt = select(Vocab)
        vocabs_set = session.exec(stmt).all()
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


async def vocabs_view(request: Request):
    vid = request.path_params['vocab_id']
    # use .get() on path_params to handle None exception ?
    with Session(engine) as session:
        v = session.get(Vocab, vid)
    return templates.TemplateResponse(request, 'show.html', {'vocab': v})


async def vocabs_edit_get(request: Request):
    vid = request.path_params['vocab_id']
    # use .get() on path_params to handle None exception ?
    with Session(engine) as session:
        v = session.get(Vocab, vid)
    return templates.TemplateResponse(request, 'edit.html', {'vocab': v})


async def vocabs_edit_post(request: Request):
    vid = request.path_params['vocab_id']
    async with request.form() as form:
        with Session(engine) as session:
            v = session.get(Vocab, vid)
            v.word = form.get('word')
            v.context = form.get('context')
            v.source = form.get('source')
            try:
                session.add(v)
                session.commit()
                # IMPLEMENT flash('Updated Vocab!')
                return RedirectResponse(url='/vocabs/'+str(vid), status_code=303)
            except Exception as e:
                session.rollback()
                print(f'An error occurred: {e}')
                return templates.TemplateResponse(request, 'edit.html', {'vocab': v})


routes = [
    Route('/', homepage),
    Route('/vocabs', vocabs),
    Route('/vocabs/new', vocabs_new_get, methods=['GET']),
    Route('/vocabs/new', vocabs_new, methods=['POST']),
    Route('/vocabs/{vocab_id:int}', vocabs_view),
    Route('/vocabs/{vocab_id:int}/edit', vocabs_edit_get, methods=['GET']),
    Route('/vocabs/{vocab_id:int}/edit', vocabs_edit_post, methods=['POST']),
    Mount('/static', StaticFiles(directory='static'), name='static'),
]

on_startup = [
    create_db_and_tables,
]

app = Starlette(debug=True, routes=routes, on_startup=on_startup)