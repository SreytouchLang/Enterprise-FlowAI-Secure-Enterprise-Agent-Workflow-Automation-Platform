from functools import lru_cache

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


@lru_cache
def get_engine():
    url = get_settings().database_url
    kwargs = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {"pool_pre_ping": True}
    engine = create_engine(url, **kwargs)
    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def enable_fk(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
    return engine


def session_factory():
    return sessionmaker(get_engine(), expire_on_commit=False)


def get_db():
    with session_factory()() as session:
        yield session


def set_scope(db: Session, user_id: str, department_ids: list[str]):
    db.info["principal_scope"] = (user_id, department_ids)
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        db.execute(text("SELECT set_config('app.user_id', :user_id, true), set_config('app.department_ids', :departments, true)"), {"user_id": user_id, "departments": ",".join(department_ids)})


@event.listens_for(Session, "after_begin")
def apply_scope(session, transaction, connection):
    scope = session.info.get("principal_scope")
    if scope and connection.dialect.name == "postgresql":
        connection.execute(text("SELECT set_config('app.user_id', :u, true), set_config('app.department_ids', :d, true)"), {"u": scope[0], "d": ",".join(scope[1])})
