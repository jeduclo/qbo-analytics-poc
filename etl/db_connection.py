"""
db_connection.py
Shared SQLAlchemy engine for all scripts that connect to Azure SQL.

Usage in any script:
    from db_connection import get_engine
    engine = get_engine()

All credentials are read from environment variables.
Never hardcode credentials in this file or any other.
"""

import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()


def get_engine():
    """
    Build and return a SQLAlchemy engine connected to Azure SQL.

    Connection uses ODBC Driver 18 for SQL Server with encrypted transport.
    TrustServerCertificate=yes is required for Azure SQL serverless endpoints
    that use self-signed certificates during the auto-pause wake cycle.

    Raises EnvironmentError if any required credential is missing.
    Raises sqlalchemy.exc.OperationalError if the connection cannot be established.
    """
    server   = os.getenv("AZURE_SQL_SERVER")
    database = os.getenv("AZURE_SQL_DATABASE")
    username = os.getenv("AZURE_SQL_USERNAME")
    password = os.getenv("AZURE_SQL_PASSWORD")

    missing = [k for k, v in {
        "AZURE_SQL_SERVER":   server,
        "AZURE_SQL_DATABASE": database,
        "AZURE_SQL_USERNAME": username,
        "AZURE_SQL_PASSWORD": password,
    }.items() if not v]

    if missing:
        raise EnvironmentError(
            f"Missing required environment variables: {', '.join(missing)}\n"
            f"Check your .env file."
        )

    connection_string = (
        f"mssql+pyodbc://{username}:{password}@{server}/{database}"
        f"?driver=ODBC+Driver+18+for+SQL+Server"
        f"&Encrypt=yes"
        f"&TrustServerCertificate=yes"
        f"&Connection+Timeout=30"
    )

    return create_engine(
        connection_string,
        pool_pre_ping=True,       # Detects stale connections before use
        pool_recycle=3600,        # Recycle connections after 1 hour
        echo=False,               # Set to True temporarily to log all SQL
    )


def verify_connection(engine) -> bool:
    """
    Run a trivial query to confirm the engine can reach the database.
    Returns True on success, raises on failure.
    """
    with engine.connect() as conn:
        result = conn.execute(text("SELECT GETDATE() AS server_time"))
        row = result.fetchone()
        print(f"  Database connection verified. Server time: {row[0]}")
    return True


if __name__ == "__main__":
    print("Testing database connection...")
    eng = get_engine()
    verify_connection(eng)
    print("Connection test passed.")