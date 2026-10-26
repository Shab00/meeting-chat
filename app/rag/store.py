from typing import Optional

from langchain_openai import OpenAIEmbeddings
from langchain_postgres import PGEngine, PGVectorStore
from psycopg.errors import DuplicateTable
from sqlalchemy.exc import ProgrammingError

from app.config import settings

TABLE = "meeting_embeddings"
VECTOR_SIZE = 1536  # text-embedding-3-small

# Module-level singletons so the connection pool and store are reused across
# requests. Created lazily so importing this module never touches the DB.
_engine: Optional[PGEngine] = None
_store: Optional[PGVectorStore] = None
_embeddings: Optional[OpenAIEmbeddings] = None


def get_engine() -> PGEngine:
    global _engine
    if _engine is None:
        _engine = PGEngine.from_connection_string(url=settings.vector_db_url)
    return _engine


def get_embeddings() -> OpenAIEmbeddings:
    global _embeddings
    if _embeddings is None:
        _embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
    return _embeddings


async def init_table() -> None:
    """Create the vector table if missing. Idempotent."""
    # langchain-postgres 0.0.19 issues a plain CREATE TABLE (no IF NOT
    # EXISTS), so a second startup would raise DuplicateTable.
    try:
        await get_engine().ainit_vectorstore_table(
            table_name=TABLE,
            vector_size=VECTOR_SIZE,
        )
    except ProgrammingError as e:
        if not isinstance(e.orig, DuplicateTable):
            raise


def get_store() -> PGVectorStore:
    global _store
    if _store is None:
        _store = PGVectorStore.create_sync(
            engine=get_engine(),
            table_name=TABLE,
            embedding_service=get_embeddings(),
        )
    return _store
