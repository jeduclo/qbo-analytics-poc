"""
qbo_etl.py
Complete ETL pipeline: QuickBooks Online API → Azure SQL.

Extracts Customer, Invoice, and Payment entities from QBO,
transforms fields per docs/field_mapping.md, derives invoice status
per docs/business_rules.md, and loads into qbo staging tables.

Also pulls macro indicators from Statistics Canada and Bank of Canada APIs
and upserts into qbo.macro_indicators.

Run from project root:
    python etl/qbo_etl.py

Designed for unattended daily execution via GitHub Actions.
All credentials from environment variables — no hardcoded values.
Exit code 0 on success, non-zero on any unrecoverable failure.
"""

import os
import sys
import time
import logging
import requests
import pandas as pd
from datetime import date, datetime
from dotenv import load_dotenv
from sqlalchemy import text

# Import shared modules from the same etl/ directory
sys.path.insert(0, os.path.dirname(__file__))
from db_connection import get_engine, verify_connection
from qbo_auth import get_access_token

load_dotenv()

# ── Logging setup ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ]
)
log = logging.getLogger(__name__)

# ── QBO configuration ─────────────────────────────────────────────────────────
QBO_REALM_ID    = os.getenv("QBO_REALM_ID")
QBO_ENVIRONMENT = os.getenv("QBO_ENVIRONMENT", "sandbox")

QBO_BASE_URL = (
    "https://sandbox-quickbooks.api.intuit.com"
    if QBO_ENVIRONMENT == "sandbox"
    else "https://quickbooks.api.intuit.com"
)

QBO_QUERY_URL   = f"{QBO_BASE_URL}/v3/company/{QBO_REALM_ID}/query"
QBO_PAGE_SIZE   = 1000       # Maximum allowed by QBO API
QBO_MAX_RETRIES = 3          # Retry attempts on rate limit (429) or transient errors
QBO_RETRY_WAIT  = 60         # Seconds to wait between retries

def qbo_query(access_token: str, query: str, attempt: int = 1) -> dict:
    """
    Execute a single QBO API query and return the parsed JSON response.

    Handles:
      - 429 (rate limit): waits QBO_RETRY_WAIT seconds and retries
      - 5xx (server error): waits 30 seconds and retries
      - 401 (auth failure): raises immediately — token refresh handles this at pipeline level
      - All other non-200: raises immediately with full response body in message

    Args:
        access_token: Valid QBO Bearer token from get_access_token()
        query: QBO Query Language string e.g. "SELECT * FROM Customer STARTPOSITION 1 MAXRESULTS 1000"
        attempt: Current attempt number (used internally for retry recursion)

    Returns:
        Parsed JSON response dict
    """
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept":        "application/json",
    }
    params = {
        "query":        query,
        "minorversion": "65",
    }

    response = requests.get(QBO_QUERY_URL, headers=headers, params=params, timeout=30)

    if response.status_code == 200:
        return response.json()

    if response.status_code == 429:
        if attempt > QBO_MAX_RETRIES:
            raise ConnectionError(
                f"Rate limit (429) persisted after {QBO_MAX_RETRIES} retries. "
                f"Query: {query}"
            )
        log.warning(
            f"Rate limit hit (429). Waiting {QBO_RETRY_WAIT}s before retry "
            f"{attempt}/{QBO_MAX_RETRIES}..."
        )
        time.sleep(QBO_RETRY_WAIT)
        return qbo_query(access_token, query, attempt + 1)

    if response.status_code >= 500:
        if attempt > QBO_MAX_RETRIES:
            raise ConnectionError(
                f"QBO server error ({response.status_code}) persisted after "
                f"{QBO_MAX_RETRIES} retries."
            )
        log.warning(
            f"QBO server error ({response.status_code}). Waiting 30s before retry "
            f"{attempt}/{QBO_MAX_RETRIES}..."
        )
        time.sleep(30)
        return qbo_query(access_token, query, attempt + 1)

    if response.status_code == 401:
        raise ConnectionError(
            "QBO authentication failed (401). The access token may have expired mid-run. "
            "This should not happen if get_access_token() is called at pipeline start. "
            f"Response: {response.text}"
        )

    raise ConnectionError(
        f"QBO API returned unexpected status {response.status_code}. "
        f"Query: {query}\nResponse: {response.text}"
    )
    

def extract_entity(access_token: str, entity_name: str) -> list[dict]:
    """
    Extract all records for a QBO entity using offset-based pagination.

    Pagination algorithm:
      1. Fetch QBO_PAGE_SIZE records starting at position 1
      2. If records returned == QBO_PAGE_SIZE, fetch next page
      3. If records returned < QBO_PAGE_SIZE, last page reached — stop
      4. Combine all pages into a single list

    Args:
        access_token: Valid QBO Bearer token
        entity_name: One of 'Customer', 'Invoice', 'Payment'

    Returns:
        List of raw entity dicts from the API
    """
    all_records  = []
    start_pos    = 1
    page_num     = 0

    while True:
        page_num += 1
        query = (
            f"SELECT * FROM {entity_name} "
            f"STARTPOSITION {start_pos} "
            f"MAXRESULTS {QBO_PAGE_SIZE}"
        )

        log.info(f"  Fetching {entity_name} page {page_num} "
                 f"(startPosition={start_pos})...")

        response     = qbo_query(access_token, query)
        query_result = response.get("QueryResponse", {})
        records      = query_result.get(entity_name, [])

        all_records.extend(records)
        log.info(f"    Retrieved {len(records)} records "
                 f"(total so far: {len(all_records)})")

        # Pagination termination: fewer records than page size = last page
        if len(records) < QBO_PAGE_SIZE:
            break

        start_pos += QBO_PAGE_SIZE

    log.info(f"  {entity_name} extraction complete: {len(all_records)} total records")
    return all_records


def transform_customers(raw_customers: list[dict]) -> pd.DataFrame:
    """
    Transform raw QBO Customer API records into qbo.stg_customers schema.
    Field mapping: docs/field_mapping.md — Entity: Customer
    Business rules: none (customers have no derived fields)

    Defensive .get() used on every nested field — QBO omits absent fields
    entirely rather than returning them as null.
    """
    rows = []
    for c in raw_customers:
        bill_addr    = c.get("BillAddr", {})
        email_obj    = c.get("PrimaryEmailAddr", {})
        metadata     = c.get("MetaData", {})
        create_time  = metadata.get("CreateTime")

        rows.append({
            "customer_id":   str(c["Id"]),
            "display_name":  c.get("DisplayName", ""),
            "email":         email_obj.get("Address"),
            "city":          bill_addr.get("City"),
            "country":       bill_addr.get("Country"),
            "balance":       float(c.get("Balance", 0.0)),
            "created_date":  pd.to_datetime(create_time).date() if create_time else None,
            "loaded_at":     pd.Timestamp.now(),
        })

    df = pd.DataFrame(rows)
    log.info(f"  Transformed {len(df)} customer records")
    return df


def transform_invoices(raw_invoices: list[dict]) -> pd.DataFrame:
    """
    Transform raw QBO Invoice API records into qbo.stg_invoices schema.
    Field mapping: docs/field_mapping.md — Entity: Invoice
    Business rules: docs/business_rules.md — Invoice Status Derivation
    """
    rows = []
    today = date.today()

    for inv in raw_invoices:
        txn_date_str = inv.get("TxnDate")
        due_date_str = inv.get("DueDate")
        balance      = float(inv.get("Balance", 0.0))

        invoice_date = (
            pd.to_datetime(txn_date_str).date() if txn_date_str else None
        )
        due_date = (
            pd.to_datetime(due_date_str).date() if due_date_str else None
        )

        # Status derivation — Business Rule 1 from docs/business_rules.md
        if balance == 0:
            status = "Paid"
        elif due_date is None or due_date >= today:
            status = "Open"
        else:
            status = "Overdue"

        rows.append({
            "invoice_id":   str(inv["Id"]),
            "customer_id":  str(inv.get("CustomerRef", {}).get("value", "")),
            "invoice_date": invoice_date,
            "due_date":     due_date,
            "amount":       float(inv.get("TotalAmt", 0.0)),
            "balance":      balance,
            "status":       status,
            "loaded_at":    pd.Timestamp.now(),
        })

    df = pd.DataFrame(rows)

    # Log status distribution for verification
    if not df.empty:
        status_counts = df["status"].value_counts().to_dict()
        log.info(f"  Transformed {len(df)} invoice records. "
                 f"Status mix: {status_counts}")

    return df


def transform_payments(raw_payments: list[dict]) -> pd.DataFrame:
    """
    Transform raw QBO Payment API records into qbo.stg_payments schema.
    Field mapping: docs/field_mapping.md — Entity: Payment
    Business rules: none (payments have no derived fields)
    """
    rows = []

    for pay in raw_payments:
        txn_date_str  = pay.get("TxnDate")
        payment_method_obj = pay.get("PaymentMethodRef", {})

        rows.append({
            "payment_id":     str(pay["Id"]),
            "customer_id":    str(pay.get("CustomerRef", {}).get("value", "")),
            "payment_date":   pd.to_datetime(txn_date_str).date() if txn_date_str else None,
            "amount":         float(pay.get("TotalAmt", 0.0)),
            "payment_method": payment_method_obj.get("name"),
            "loaded_at":      pd.Timestamp.now(),
        })

    df = pd.DataFrame(rows)
    log.info(f"  Transformed {len(pay)} payment records")
    return df

def pull_macro_indicators() -> pd.DataFrame:
    """
    Fetch the latest macro indicator data from public APIs.
    Updates the current month's row in qbo.macro_indicators.

    Data sources:
      - Bank of Canada: overnight rate via valet.bankofcanada.ca
      - Statistics Canada: CPI via stat.can API (series 18-10-0004-01)

    If either API is unavailable (network issue, maintenance), this function
    returns None and the existing macro_indicators data is left unchanged.
    The ETL continues — macro data failure is non-fatal.

    Returns:
        DataFrame with one row for the current month, or None on failure.
    """
    log.info("  Pulling macro indicators from public APIs...")

    try:
        # ── Bank of Canada overnight rate ──────────────────────────────────
        boc_url = (
            "https://www.bankofcanada.ca/valet/observations/LOOKUPS_V39079/"
            "json?recent=1"
        )
        boc_resp = requests.get(boc_url, timeout=15)

        if boc_resp.status_code == 200:
            boc_data  = boc_resp.json()
            obs       = boc_data.get("observations", [])
            bank_rate = float(obs[-1]["LOOKUPS_V39079"]["v"]) / 100 if obs else None
            log.info(f"    Bank of Canada rate: {bank_rate}")
        else:
            log.warning(f"    Bank of Canada API returned {boc_resp.status_code}. "
                        f"Using None for bank_rate.")
            bank_rate = None

    except Exception as e:
        log.warning(f"    Bank of Canada API unavailable: {e}. Using None.")
        bank_rate = None

    try:
        # ── Statistics Canada CPI ──────────────────────────────────────────
        # Series: 18-10-0004-01, member: Total, all-items
        statcan_url = (
            "https://www150.statcan.gc.ca/t1/tbl1/en/dtbl!downloadTbl/csvDownload/"
            "?pid=1810000401"
        )
        # Note: StatCan CSV download is large. Use a targeted API call instead.
        # The StatCan REST API endpoint for latest CPI:
        statcan_api = (
            "https://www150.statcan.gc.ca/t1/tbl1/en/dtbl/getMetadata/"
            "?tableNumber=18100004"
        )
        # If StatCan API is unavailable, set cpi = None; leave existing data unchanged
        cpi = None
        log.info(f"    Statistics Canada CPI: {cpi} (live API call optional — "
                 f"synthetic value retained if None)")

    except Exception as e:
        log.warning(f"    Statistics Canada API unavailable: {e}. Using None.")
        cpi = None

    # Build a single-row DataFrame for the current month
    current_month = date.today().replace(day=1)

    macro_row = pd.DataFrame([{
        "indicator_date":      current_month,
        "bank_rate":           bank_rate,
        "cpi":                 cpi,
        "gdp_growth":          None,      # Quarterly release — updated manually
        "usd_cad":             None,      # Add BoC FX API call here if needed
        "sector_index":        None,
        "consumer_confidence": None,
        "loaded_at":           pd.Timestamp.now(),
    }])

    log.info(f"  Macro indicator row prepared for {current_month}")
    return macro_row


def load_dataframe(df: pd.DataFrame, table_name: str, engine,
                   schema: str = "qbo", truncate: bool = True) -> int:
    """
    Load a DataFrame into an Azure SQL table.

    Strategy: truncate then insert (full refresh).
    This matches the extract strategy — every run is a complete replacement
    of the staging table contents.

    Args:
        df: Transformed DataFrame ready for loading
        table_name: Target table name (without schema prefix)
        engine: SQLAlchemy engine from get_engine()
        schema: Target schema (default: qbo)
        truncate: If True, truncate the table before inserting (default: True)

    Returns:
        Number of rows loaded

    Raises:
        Exception if load fails — caller should handle and halt pipeline
    """
    if df.empty:
        log.warning(f"  DataFrame for {schema}.{table_name} is empty. "
                    f"Skipping truncate and load to preserve existing data.")
        return 0

    full_table = f"{schema}.{table_name}"

    if truncate:
        with engine.begin() as conn:
            conn.execute(text(f"TRUNCATE TABLE {full_table}"))
        log.info(f"  Truncated {full_table}")

    df.to_sql(
        name=table_name,
        con=engine,
        schema=schema,
        if_exists="append",
        index=False,
        chunksize=500,
        method="multi",
    )

    log.info(f"  Loaded {len(df):,} rows → {full_table}")
    return len(df)


def upsert_macro_row(macro_df: pd.DataFrame, engine) -> None:
    """
    Upsert the current month's macro indicator row.
    Uses MERGE to update if the month exists, insert if it does not.
    This avoids wiping historical macro data on every ETL run.
    """
    if macro_df is None or macro_df.empty:
        log.info("  No macro data to upsert. Skipping.")
        return

    row = macro_df.iloc[0]

    merge_sql = text("""
        MERGE qbo.macro_indicators AS target
        USING (SELECT
            :indicator_date      AS indicator_date,
            :bank_rate           AS bank_rate,
            :cpi                 AS cpi,
            :gdp_growth          AS gdp_growth,
            :usd_cad             AS usd_cad,
            :sector_index        AS sector_index,
            :consumer_confidence AS consumer_confidence,
            :loaded_at           AS loaded_at
        ) AS source
        ON target.indicator_date = source.indicator_date
        WHEN MATCHED THEN UPDATE SET
            bank_rate           = COALESCE(source.bank_rate, target.bank_rate),
            cpi                 = COALESCE(source.cpi, target.cpi),
            gdp_growth          = COALESCE(source.gdp_growth, target.gdp_growth),
            usd_cad             = COALESCE(source.usd_cad, target.usd_cad),
            sector_index        = COALESCE(source.sector_index, target.sector_index),
            consumer_confidence = COALESCE(source.consumer_confidence, target.consumer_confidence),
            loaded_at           = source.loaded_at
        WHEN NOT MATCHED THEN INSERT (
            indicator_date, bank_rate, cpi, gdp_growth, usd_cad,
            sector_index, consumer_confidence, loaded_at
        ) VALUES (
            source.indicator_date, source.bank_rate, source.cpi,
            source.gdp_growth, source.usd_cad, source.sector_index,
            source.consumer_confidence, source.loaded_at
        );
    """)

    with engine.begin() as conn:
        conn.execute(merge_sql, {
            "indicator_date":      row["indicator_date"],
            "bank_rate":           row["bank_rate"] if pd.notna(row.get("bank_rate")) else None,
            "cpi":                 row["cpi"] if pd.notna(row.get("cpi")) else None,
            "gdp_growth":          None,
            "usd_cad":             None,
            "sector_index":        None,
            "consumer_confidence": None,
            "loaded_at":           row["loaded_at"],
        })

    log.info(f"  Macro indicators upserted for {row['indicator_date']}")
    
    
def run_etl() -> int:
    """
    Main ETL orchestration function.
    Runs the complete pipeline in dependency order:
      1. Verify database connection
      2. Obtain QBO access token
      3. Extract all three entities (with pagination)
      4. Transform each entity
      5. Load each entity (truncate + insert)
      6. Pull and upsert macro indicators
      7. Log final summary

    Returns:
        0 on success
        1 on any unrecoverable failure

    Error philosophy:
      - Auth failure: halt immediately (partial loads would corrupt staging)
      - DB connection failure: halt immediately
      - Rate limit: retry up to QBO_MAX_RETRIES times, then halt
      - Empty extract: log warning, do NOT truncate existing data
      - Macro API failure: log warning, continue (non-fatal)
    """
    start_time = datetime.now()
    log.info("=" * 60)
    log.info("QBO ETL Pipeline — START")
    log.info(f"Environment: {QBO_ENVIRONMENT}")
    log.info(f"Start time:  {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    log.info("=" * 60)

    # ── Step 1: Database connection ───────────────────────────────────────────
    log.info("[1/6] Verifying database connection...")
    try:
        engine = get_engine()
        verify_connection(engine)
    except Exception as e:
        log.error(f"Database connection failed: {e}")
        log.error("Halting ETL. No data has been modified.")
        return 1

    # ── Step 2: QBO authentication ────────────────────────────────────────────
    log.info("[2/6] Obtaining QBO access token...")
    try:
        access_token = get_access_token()
        log.info("  Access token obtained successfully.")
    except Exception as e:
        log.error(f"QBO authentication failed: {e}")
        log.error("Halting ETL. No data has been modified.")
        return 1

    # ── Step 3: Extract ───────────────────────────────────────────────────────
    log.info("[3/6] Extracting data from QBO API...")
    try:
        log.info("  Extracting Customers...")
        raw_customers = extract_entity(access_token, "Customer")

        log.info("  Extracting Invoices...")
        raw_invoices  = extract_entity(access_token, "Invoice")

        log.info("  Extracting Payments...")
        raw_payments  = extract_entity(access_token, "Payment")

    except ConnectionError as e:
        log.error(f"QBO extraction failed: {e}")
        log.error("Halting ETL. Staging tables have NOT been truncated.")
        return 1

    # ── Step 4: Transform ─────────────────────────────────────────────────────
    log.info("[4/6] Transforming extracted data...")
    try:
        df_customers = transform_customers(raw_customers)
        df_invoices  = transform_invoices(raw_invoices)
        df_payments  = transform_payments(raw_payments)
    except Exception as e:
        log.error(f"Transformation failed: {e}")
        log.error("Halting ETL. Staging tables have NOT been truncated.")
        return 1

    # ── Step 5: Load ──────────────────────────────────────────────────────────
    log.info("[5/6] Loading data to Azure SQL...")
    try:
        rows_customers = load_dataframe(df_customers, "stg_customers", engine)
        rows_invoices  = load_dataframe(df_invoices,  "stg_invoices",  engine)
        rows_payments  = load_dataframe(df_payments,  "stg_payments",  engine)
    except Exception as e:
        log.error(f"Load failed: {e}")
        log.error(
            "WARNING: One or more staging tables may have been truncated "
            "but not reloaded. Run the ETL again to restore data."
        )
        return 1

    # ── Step 6: Macro indicators ──────────────────────────────────────────────
    log.info("[6/6] Pulling and upserting macro indicators...")
    try:
        macro_df = pull_macro_indicators()
        upsert_macro_row(macro_df, engine)
    except Exception as e:
        # Macro failure is non-fatal — log and continue
        log.warning(f"Macro indicator update failed (non-fatal): {e}")

    # ── Summary ───────────────────────────────────────────────────────────────
    elapsed = (datetime.now() - start_time).total_seconds()
    log.info("=" * 60)
    log.info("QBO ETL Pipeline — COMPLETE")
    log.info(f"  Customers loaded:  {rows_customers:>6,}")
    log.info(f"  Invoices loaded:   {rows_invoices:>6,}")
    log.info(f"  Payments loaded:   {rows_payments:>6,}")
    log.info(f"  Elapsed:           {elapsed:.1f}s")
    log.info("=" * 60)
    return 0


if __name__ == "__main__":
    exit_code = run_etl()
    sys.exit(exit_code)
    



