from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from .models import Base


class Database:
    def __init__(self, url):
        options = {}
        if url.startswith("sqlite"):
            options["connect_args"] = {"check_same_thread": False, "timeout": 30}
            if ":memory:" in url:
                options["poolclass"] = StaticPool
        self.engine = create_engine(url, **options)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)
        if url.startswith("sqlite"):

            @event.listens_for(self.engine, "connect")
            def configure(connection, _):
                connection.execute("PRAGMA foreign_keys=ON")
                connection.execute("PRAGMA journal_mode=WAL")

    def create_schema(self):
        Base.metadata.create_all(self.engine)

    @contextmanager
    def transaction(self):
        with self.sessions() as session:
            if self.engine.dialect.name == "sqlite":
                # Serialize writes in local development; PostgreSQL uses row locks below.
                session.connection().exec_driver_sql("BEGIN IMMEDIATE")
            try:
                yield session
                session.commit()
            except BaseException:
                session.rollback()
                raise
