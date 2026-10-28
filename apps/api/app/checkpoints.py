"""LangGraph checkpoint stores contain identifiers only, never retrieved document text."""
from contextlib import asynccontextmanager
from pathlib import Path

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.core.config import get_settings


@asynccontextmanager
async def checkpointer():
    url = get_settings().database_url
    if url.startswith("postgresql"):
        async with AsyncPostgresSaver.from_conn_string(url.replace("postgresql+psycopg://", "postgresql://")) as saver:
            yield saver  # Tables are created with migration credentials by Alembic.
    else:
        path = Path(get_settings().storage_path).parent / ".local" / "agent-checkpoints.sqlite"
        path.parent.mkdir(parents=True, exist_ok=True)
        async with AsyncSqliteSaver.from_conn_string(str(path)) as saver:
            await saver.setup()
            yield saver
