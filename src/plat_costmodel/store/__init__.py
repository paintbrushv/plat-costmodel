"""Persistence layer for plat-costmodel.

SQLite, always-on, default path ``~/.plat-costmodel/data.db``. Override
with the ``PLAT_COSTMODEL_DB_PATH`` env var. Tests pass an explicit path
via the ``tmp_db`` fixture.
"""
