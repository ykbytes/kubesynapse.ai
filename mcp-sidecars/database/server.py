"""MCP Database sidecar — query SQL databases, list tables, describe schemas."""

import logging
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "base"))
from mcp_base import create_mcp_server, run_server

log = logging.getLogger("mcp-database")

server = create_mcp_server(
    "mcp-database",
    "Query SQL databases (PostgreSQL/MySQL/SQLite), list tables, and describe schemas.",
)

MAX_ROWS = 50
MAX_OUTPUT_CHARS = 12000
MAX_QUERY_CHARS = 4096

# Connection string is read from environment only — never from user input.
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()

# SQL keywords that indicate a destructive or write operation.
_DANGEROUS_SQL_PATTERN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE|REPLACE|GRANT|REVOKE|EXEC|EXECUTE|MERGE|CALL|COPY)\b",
    re.IGNORECASE,
)

# PostgreSQL-specific dangerous functions that can read/write the filesystem
# or export large objects even within a SELECT query.
_DANGEROUS_FUNCTION_PATTERN = re.compile(
    r"\b(pg_read_file|pg_read_binary_file|pg_write_file|lo_export|lo_import|lo_get"
    r"|pg_ls_dir|pg_stat_file|dblink|dblink_exec|dblink_connect)\s*\(",
    re.IGNORECASE,
)

# Regex to strip SQL-style comments (both block /* */ and line --) before keyword validation.
_SQL_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_SQL_LINE_COMMENT = re.compile(r"--[^\n]*")


def _get_default_engine():
    """Create a SQLAlchemy engine from the DATABASE_URL environment variable."""
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL environment variable is not configured")
    from sqlalchemy import create_engine
    return create_engine(DATABASE_URL, pool_pre_ping=True)


def _validate_query(query: str) -> str | None:
    """Return an error message if the query is not safe, else None."""
    if not query or not query.strip():
        return "Query must not be empty"
    if len(query) > MAX_QUERY_CHARS:
        return f"Query exceeds maximum length of {MAX_QUERY_CHARS} characters"
    stripped = query.strip()
    # Must start with SELECT or WITH (for CTEs)
    if not re.match(r"^\s*(SELECT|WITH)\b", stripped, re.IGNORECASE):
        return "Only SELECT queries are allowed (query must start with SELECT or WITH)"
    # Strip SQL comments before keyword checking to prevent bypass via /* INSERT */
    decommented = _SQL_BLOCK_COMMENT.sub(" ", stripped)
    decommented = _SQL_LINE_COMMENT.sub(" ", decommented)
    # Check for dangerous keywords anywhere in the query (catches injection in subqueries)
    if _DANGEROUS_SQL_PATTERN.search(decommented):
        return "Query contains blocked SQL keywords (write/DDL operations are not allowed)"
    # Check for dangerous PostgreSQL functions that can read/write filesystem
    if _DANGEROUS_FUNCTION_PATTERN.search(decommented):
        return "Query contains blocked database functions (filesystem/network access not allowed)"
    # Block multiple statements (semicolons followed by non-whitespace)
    if re.search(r";\s*\S", decommented):
        return "Multiple SQL statements are not allowed"
    return None


@server.tool()
def query_sql(query: str) -> str:
    """Execute a read-only SQL SELECT query and return results as text.

    The database connection is configured server-side via DATABASE_URL.
    Only SELECT queries are allowed — write operations are blocked.
    """
    validation_err = _validate_query(query)
    if validation_err:
        return f"BLOCKED: {validation_err}"
    try:
        from sqlalchemy import text
        engine = _get_default_engine()
        with engine.connect() as conn:
            result = conn.execute(text(query))
            columns = list(result.keys())
            rows = result.fetchmany(MAX_ROWS)
            lines = ["\t".join(columns)]
            for row in rows:
                lines.append("\t".join(str(v) if v is not None else "NULL" for v in row))
            if result.fetchone():
                lines.append(f"... (truncated at {MAX_ROWS} rows)")
            return "\n".join(lines)[:MAX_OUTPUT_CHARS]
    except ImportError:
        return "ERROR: sqlalchemy not installed"
    except RuntimeError as e:
        return f"ERROR: {e}"
    except Exception as e:
        log.exception("query_sql failed")
        return "ERROR: Query failed"


@server.tool()
def list_tables() -> str:
    """List all tables in the database."""
    try:
        from sqlalchemy import inspect
        engine = _get_default_engine()
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        if not tables:
            return "(no tables found)"
        return "\n".join(tables)
    except RuntimeError as e:
        return f"ERROR: {e}"
    except Exception as e:
        log.exception("list_tables failed")
        return "ERROR: Failed to list tables"


@server.tool()
def describe_table(table_name: str) -> str:
    """Describe the columns and types of a table."""
    # Validate table name — alphanumeric + underscores only
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_.]{0,127}$", table_name):
        return "BLOCKED: Invalid table name"
    try:
        from sqlalchemy import inspect
        engine = _get_default_engine()
        inspector = inspect(engine)
        columns = inspector.get_columns(table_name)
        lines = [f"Table: {table_name}", ""]
        for col in columns:
            nullable = "NULL" if col.get("nullable", True) else "NOT NULL"
            lines.append(f"  {col['name']}: {col['type']} {nullable}")
        pk = inspector.get_pk_constraint(table_name)
        if pk and pk.get("constrained_columns"):
            lines.append(f"\n  PRIMARY KEY: {', '.join(pk['constrained_columns'])}")
        return "\n".join(lines)
    except RuntimeError as e:
        return f"ERROR: {e}"
    except Exception as e:
        log.exception("describe_table failed")
        return "ERROR: Failed to describe table"


if __name__ == "__main__":
    run_server(server)
