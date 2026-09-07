"""Tests that the Alembic chain actually runs, and agrees with the ORM models.

Every other test builds its schema with ``Base.metadata.create_all``, which is
why the chain was able to sit broken and unnoticed: revision 57b7a3936ceb used
``op.create_unique_constraint`` directly, which SQLite cannot do, so
``alembic upgrade head`` raised NotImplementedError and no test ran it.
"""

from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from alembic import command
from app.core.db import Base

SERVER_DIR = Path(__file__).resolve().parent.parent


@pytest.fixture
def alembic_config(tmp_path: Path) -> Config:
    """Alembic pointed at a throwaway SQLite file, never the dev database.

    The URL goes in ``attributes``, which is the hook ``alembic/env.py``
    honours — ``set_main_option`` alone is overwritten by the settings-derived
    URL when env.py runs.
    """
    config = Config(str(SERVER_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(SERVER_DIR / "alembic"))
    database_url = f"sqlite:///{(tmp_path / 'migrations.db').as_posix()}"
    config.set_main_option("sqlalchemy.url", database_url)
    config.attributes["sqlalchemy_url"] = database_url
    return config


def _url(config: Config) -> str:
    return str(config.attributes["sqlalchemy_url"])


def test_upgrade_head_runs_from_an_empty_database(alembic_config: Config):
    """The whole chain applies to a fresh SQLite file."""
    command.upgrade(alembic_config, "head")

    tables = set(inspect(create_engine(_url(alembic_config))).get_table_names())
    assert "alembic_version" in tables
    assert {"datasets", "feedback_items", "conversations", "chat_messages"} <= tables


def test_migrated_schema_matches_the_orm_models(alembic_config: Config):
    """Guards against migration/model drift in either direction."""
    command.upgrade(alembic_config, "head")

    migrated = inspect(create_engine(_url(alembic_config)))
    expected = inspect(create_engine("sqlite:///:memory:"))
    Base.metadata.create_all(expected.engine)

    migrated_tables = set(migrated.get_table_names()) - {"alembic_version"}
    assert migrated_tables == set(expected.get_table_names())

    for table in sorted(migrated_tables):
        assert {column["name"] for column in migrated.get_columns(table)} == {
            column["name"] for column in expected.get_columns(table)
        }, f"column drift in {table}"


def test_batch_mode_rebuild_preserves_cluster_assignment_constraints(alembic_config: Config):
    """SQLite batch mode recreates the table; the FKs must survive that.

    Adding the unique constraint copies cluster_assignments to a new table, so
    a reflection gap there would silently drop ON DELETE CASCADE.
    """
    command.upgrade(alembic_config, "head")

    migrated = inspect(create_engine(_url(alembic_config)))

    assert [
        (u["name"], u["column_names"])
        for u in migrated.get_unique_constraints("cluster_assignments")
    ] == [("uq_cluster_assignments_run_item", ["run_id", "feedback_item_id"])]

    assert sorted(
        (fk["referred_table"], fk["options"].get("ondelete"))
        for fk in migrated.get_foreign_keys("cluster_assignments")
    ) == [
        ("clustering_runs", "CASCADE"),
        ("clusters", "CASCADE"),
        ("feedback_items", "CASCADE"),
    ]


def test_downgrade_unwinds_the_whole_chain(alembic_config: Config):
    """A reversible chain — every revision's downgrade has to work too."""
    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, "base")

    tables = set(inspect(create_engine(_url(alembic_config))).get_table_names())
    assert tables <= {"alembic_version"}
