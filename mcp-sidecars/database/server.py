"""MCP Database sidecar — query SQL databases, list tables, describe schemas."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "base"))
from mcp_base import create_mcp_server, run_server

server = create_mcp_server(
    "mcp-database",
    "Query SQL databases (PostgreSQL/MySQL/SQLite), list tables, and describe schemas.",
)

MAX_ROWS = 50
MAX_OUTPUT_CHARS = 12000


def _get_engine(connection_string: str):
    """Create a SQLAlchemy engine from a connection string."""
    from sqlalchemy import create_engine
    return create_engine(connection_string, pool_pre_ping=True)


@server.tool()
def query_sql(connection_string: str, query: str) -> str:
    """Execute a read-only SQL query and return results as text.

    connection_string: SQLAlchemy-style, e.g. sqlite:///data.db or postgresql://user:pass@host/db
    query: SQL SELECT statement to execute.
    """
    try:
        from sqlalchemy import text
        engine = _get_engine(connection_string)
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
    except Exception as e:
        return f"ERROR: Query failed: {e}"


@server.tool()
def list_tables(connection_string: str) -> str:
    """List all tables in the database."""
    try:
        from sqlalchemy import inspect
        engine = _get_engine(connection_string)
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        if not tables:
            return "(no tables found)"
        return "\n".join(tables)
    except Exception as e:
        return f"ERROR: Failed to list tables: {e}"


@server.tool()
def describe_table(connection_string: str, table_name: str) -> str:
    """Describe the columns and types of a table."""
    try:
        from sqlalchemy import inspect
        engine = _get_engine(connection_string)
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
    except Exception as e:
        return f"ERROR: Failed to describe table: {e}"


if __name__ == "__main__":
    run_server(server)
