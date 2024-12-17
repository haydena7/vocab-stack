import json
from datetime import date
from functools import partial
from typing import Optional

from sqlmodel import (
    Field,
    Session,
    SQLModel,
    and_,
    col,
    create_engine,
    func,
    or_,
    select,
)
from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import FileResponse, PlainTextResponse, RedirectResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates
from wordfreq import zipf_frequency

from archiver_mock import Archiver

PAGE_SIZE = 5
LANG = 'es'


zipf = partial(zipf_frequency, lang=LANG)


class Vocab(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    word: str = Field(unique=True, index=True)
    context: Optional[str] = None
    source: Optional[str] = None
    freq: float = Field(index=True)
    created_at: date = Field(default_factory=date.today)


sqlite_fname = 'database.db'
sqlite_url = f'sqlite:///{sqlite_fname}'

engine = create_engine(sqlite_url, echo=True)


def create_db_and_tables():
    SQLModel.metadata.create_all(engine)


def search_db(session: Session, search_term: str):
    # TODO: make search "accent-insensitive" (¿"collation"?)
    stmt = select(Vocab).where(or_(
                col(Vocab.word).icontains(search_term),
                col(Vocab.context).icontains(search_term),
                col(Vocab.source).icontains(search_term),
            )).order_by(col(Vocab.freq).desc())
    vocabs_set = session.exec(stmt).all()
    return vocabs_set


def get_page(session: Session, cursor: tuple = None):
    stmt = select(Vocab).order_by(col(Vocab.freq).desc(), Vocab.id)
    if cursor:
        last_freq, last_id = cursor
        stmt = stmt.where(or_(
            Vocab.freq < last_freq,
            and_(Vocab.freq == last_freq, Vocab.id < last_id)
        ))
    results = session.exec(stmt.limit(PAGE_SIZE + 1)).all()
    has_more  = True if len(results) > PAGE_SIZE else False
    page = results[:PAGE_SIZE]
    context = {'vocabs': page, 'has_more': has_more}
    return context


def validate_uniqueness(session: Session, candidate: Vocab):
    stmt = select(Vocab).where(Vocab.word == candidate.word)
    if candidate.id is not None:
        # edit (not new) validation
        stmt = stmt.where(Vocab.id != candidate.id)
    existing = session.exec(stmt).first()
    unique = existing is None
    context = {
        'candidate': candidate,
        'unique': unique,
        'invalid': 'false' if unique else 'true',
        'helper': '' if unique else 'Word must be unique!',
    }
    return context


def count_rows(session: Session, model_class: SQLModel):
    stmt = select(func.count()).select_from(model_class)
    count = session.exec(stmt).first()
    return count


def archive_to_json(session: Session, out_file: str = 'vocabs.json'):
    # TODO: ¿ make async ?
    rows = session.exec(select(Vocab)).all()
    rows_dicts = [r.model_dump(mode='json') for r in rows]
    with open(out_file, 'w', encoding='utf-8') as f:
        # preserve human-readable int'l chars
        json.dump(rows_dicts, f, indent=2, ensure_ascii=False)
    raise NotImplementedError


templates = Jinja2Templates(directory='templates')


async def homepage(request: Request):
    return RedirectResponse(url='/vocabs', status_code=301)


async def vocabs(request: Request):
    search_term = request.query_params.get('q')
    with Session(engine) as session:
        if search_term is not None:
            vocabs_set = search_db(session, search_term)
            context = {'vocabs': vocabs_set, 'has_more': False}
            context['archiver'] = Archiver.get()
            if request.headers.get('HX-Trigger') == 'search':
                # triggered by "active search"
                return templates.TemplateResponse(request, 'vocab_rows.html', context)
            else:
                # triggered by traditional search
                return templates.TemplateResponse(request, 'index.html', context)
        if request.headers.get('HX-Trigger') == 'load-more':
            # triggered by "click to load"
            last_freq = request.query_params.get('last_freq')
            last_id = request.query_params.get('last_id')
            cursor = (float(last_freq), int(last_id))
            context = get_page(session, cursor)
            return templates.TemplateResponse(request, 'vocab_rows.html', context)
        context = get_page(session)
        context['archiver'] = Archiver.get()
    return templates.TemplateResponse(request, 'index.html', context)


async def vocabs_new_get(request: Request):
    return templates.TemplateResponse(request, 'new.html', {'vocab': Vocab()})


async def vocabs_new_post(request: Request):
    async with request.form() as form:
        new_fields = {k: v for k, v in form.items() if v}
    if 'word' in new_fields:
        # TODO: fix once validation strategy determined
        new_fields['freq'] = zipf(new_fields['word'])
    new_vocab = Vocab(**new_fields)
    with Session(engine) as session:
        try:
            session.add(new_vocab)
            session.commit()
            # TODO: flash('Created New Vocab!')
            return RedirectResponse(url='/vocabs', status_code=303)
        except Exception as e:
            session.rollback()
            print(f'An error occurred: {e}')
            return templates.TemplateResponse(request, 'new.html', {'vocab': new_vocab})


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
    vocab_id = request.path_params['vocab_id']
    async with request.form() as form:
        edit_fields = {key: form[key] for key in form.keys()}
        # TODO: validate `edit_fields` by constructing model instance ?
    with Session(engine) as session:
        db_vocab = session.get(Vocab, vocab_id)
        if not db_vocab:
            raise HTTPException(status_code=404, detail='Vocab not found')
        if db_vocab.word != edit_fields['word']:
            # word changed; update frequency
            edit_fields['freq'] = zipf((edit_fields['word']))
        db_vocab.sqlmodel_update(edit_fields)
        # TODO: implement error messages / exception handling
        try:
            session.add(db_vocab)
            session.commit()
            # TODO: flash('Updated Vocab!')
            return RedirectResponse(url=f'/vocabs/{vocab_id}', status_code=303)
        except Exception as e:
            session.rollback()
            print(f'An error occurred: {e}')
            return templates.TemplateResponse(request, 'edit.html', {'vocab': db_vocab})


async def vocabs_delete(request: Request):
    vid = request.path_params['vocab_id']
    with Session(engine) as session:
        v = session.get(Vocab, vid)
        if not v:
            raise HTTPException(status_code=404, detail='Vocab not found')
        session.delete(v)
        session.commit()
        if request.headers.get('HX-Trigger') == 'delete-btn':
            # issued by delete button in edit view
            # TODO implement flash('Deleted Vocab!')
            return RedirectResponse(url='/vocabs', status_code=303)
        else:
            # issued by inline delete link in index view
            return PlainTextResponse('')


async def vocab_word_validation(request: Request):
    """
    Checks current value of `word` field for uniqueness;
    flags as invalid if duplicate detected.
    """
    word = request.query_params.get('word')
    vid = request.path_params.get('vocab_id')
    candidate = Vocab(id=vid, word=word)
    with Session(engine) as session:
        context = validate_uniqueness(session, candidate)
    return templates.TemplateResponse(request, 'word_validation.html', context)


async def vocabs_count(request: Request):
    # TODO does not update with inline delete functionality
    with Session(engine) as session:
        count = count_rows(session, Vocab)
    return PlainTextResponse(f'({count} total Vocabs)')


async def vocabs_delete_bulk(request: Request):
    vocab_ids = request.query_params.getlist('checked_vocabs_ids')
    with Session(engine) as session:
        for vocab_id in vocab_ids:
            vocab = session.get(Vocab, vocab_id)
            if not vocab:
                raise HTTPException(status_code=404, detail='Vocab not found')
            session.delete(vocab)
            session.commit()
        # TODO flash('Deleted Vocabs!')
        context = get_page(session)
        context['archiver'] = Archiver.get()
    return templates.TemplateResponse(request, 'index.html', context)


async def start_archive(request: Request):
    """
    start the (async) archive process and pass {it /
    its status} into the archive_ui template response
    """
    archiver = Archiver.get()
    archiver.run()
    return templates.TemplateResponse(request, 'archive_ui.html', {'archiver': archiver})


async def archive_status(request: Request):
    """
    re-render archive_ui.html with the archive process status
    """
    archiver = Archiver.get()
    return templates.TemplateResponse(request, 'archive_ui.html', {'archiver': archiver})


async def archive_content(request: Request):
    """
    send the file the archiver created down to the client
    """
    archiver = Archiver.get()
    path = archiver.archive_file()
    return FileResponse(path, filename='archive.json', content_disposition_type='attachment')


async def reset_archive(request: Request):
    """
    reset the archive process and re-render archive_ui.html
    """
    raise NotImplementedError


routes = [
    Route('/', homepage),
    Route('/vocabs', vocabs),
    Route('/vocabs/new', vocabs_new_get, methods=['GET']),
    Route('/vocabs/new', vocabs_new_post, methods=['POST']),
    Route('/vocabs/{vocab_id:int}', vocabs_view),
    Route('/vocabs/{vocab_id:int}/edit', vocabs_edit_get, methods=['GET']),
    Route('/vocabs/{vocab_id:int}/edit', vocabs_edit_post, methods=['POST']),
    Route('/vocabs/{vocab_id:int}', vocabs_delete, methods=['DELETE']),
    Route('/vocabs/{vocab_id:int}/word', vocab_word_validation),
    Route('/vocabs/count', vocabs_count),
    Route('/vocabs', vocabs_delete_bulk, methods=['DELETE']),
    Route('/vocabs/new/word', vocab_word_validation),
    Route('/vocabs/archive', start_archive, methods=['POST']),
    Route('/vocabs/archive', archive_status, methods=['GET']),
    Route('/vocabs/archive', reset_archive, methods=['DELETE']),
    Route('/vocabs/archive/file', archive_content),
    Mount('/static', StaticFiles(directory='static'), name='static'),
]

on_startup = [
    create_db_and_tables,
]

app = Starlette(debug=True, routes=routes, on_startup=on_startup)