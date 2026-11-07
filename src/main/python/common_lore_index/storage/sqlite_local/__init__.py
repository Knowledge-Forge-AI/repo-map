"""SQLite Local graph authority: one database file per configured graph.

Parent-side only. The portable semantic worker never imports this package;
its import guard denies ``sqlite3`` outright. Writes happen only through the
explicit ``ops sqlite-init``, ``ops refresh-graph``/``refresh-enabled``,
``ops sqlite-restore`` and ``ops sqlite-upgrade`` parent commands (``ops
sqlite-backup`` only reads the live database, and ``ops sqlite-cleanup`` only
reads it while removing this graph's orphan temporaries beside it); MCP reads
open existing accepted databases read-only. Only ``ops sqlite-upgrade``
migrates a schema. Every writer serializes on the one graph lock owned by
:mod:`.locking` (platform-neutral; no ``fcntl`` import at package import).
"""
