"""
generate_qbo_data.py
Generates 24 months of synthetic QBO data and loads it into Azure SQL.
Designed to produce a specific narrative for demo purposes.
Random seed 42 ensures reproducibility — same data every run.

Run from project root:
    python synthetic_data/generate_qbo_data.py
"""

import os
import random
import numpy as np
import pandas as pd
from faker import Faker
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

# Reproducibility — set before any random operation
random.seed(42)
np.random.seed(42)
fake = Faker()
Faker.seed(42)

load_dotenv()

# ── Database connection ────────────────────────────────────────────────────────
server   = os.getenv("AZURE_SQL_SERVER")
database = os.getenv("AZURE_SQL_DATABASE")
username = os.getenv("AZURE_SQL_USERNAME")
password = os.getenv("AZURE_SQL_PASSWORD")

conn_str = (
    f"mssql+pyodbc://{username}:{password}@{server}/{database}"
    f"?driver=ODBC+Driver+18+for+SQL+Server"
)
engine = create_engine(conn_str)

# ── Constants ─────────────────────────────────────────────────────────────────
START_DATE      = date(2023, 1, 1)
END_DATE        = date(2024, 12, 31)
N_CUSTOMERS     = 70
N_INVOICES      = 600
TODAY           = date(2024, 12, 31)   # Fix "today" so aging buckets are stable

def generate_customers(n=70):
    """
    Generate n customers with realistic geographic distribution.
    Top 10 customers will be assigned higher invoice volumes in generate_invoices().
    """
    country_choices = (
        ['Canada'] * 55 + ['United States'] * 35 +
        ['United Kingdom'] * 5 + ['Australia'] * 5
    )

    customers = []
    for i in range(1, n + 1):
        country = random.choice(country_choices)

        # Use locale-appropriate fake data
        if country == 'Canada':
            city = fake.city()
        elif country == 'United States':
            city = fake.city()
        else:
            city = fake.city()

        customers.append({
            'customer_id':   str(1000 + i),
            'display_name':  fake.company(),
            'email':         fake.company_email() if random.random() > 0.1 else None,
            'city':          city,
            'country':       country,
            'balance':       0.0,         # Recalculated after invoices are generated
            'created_date':  fake.date_between(
                                 start_date=date(2021, 1, 1),
                                 end_date=date(2023, 3, 1)
                             ),
            'loaded_at':     pd.Timestamp.now(),
        })

    return pd.DataFrame(customers)

def monthly_revenue_target(invoice_date: date) -> float:
    """
    Returns the target total monthly revenue for a given month.
    Encodes the four-phase narrative:
      Phase 1 (Jan–Jun 2023): stable ~120K
      Phase 2 (Jul–Sep 2023): dip to ~80K
      Phase 3 (Oct–Dec 2023): recovery to ~120K
      Phase 4 (Jan–Dec 2024): growth from ~130K to ~180K
    """
    yr, mo = invoice_date.year, invoice_date.month

    if yr == 2023:
        if mo <= 6:
            base = 120_000
        elif mo <= 9:
            # Smooth dip using a cosine curve
            t = (mo - 6) / 3          # 0 → 1 over three months
            base = 120_000 - 40_000 * np.sin(t * np.pi)
        else:
            # Recovery
            t = (mo - 9) / 3
            base = 80_000 + 40_000 * np.sin(t * np.pi / 2 + np.pi / 2) - 40_000 * np.sin(np.pi / 2) + 40_000
            base = min(base, 120_000)
    else:
        # 2024: linear growth from 130K to 180K
        base = 130_000 + (mo - 1) * (50_000 / 11)

    # Add ±8% noise so the chart doesn't look perfectly smooth
    noise = np.random.normal(0, base * 0.08)
    return max(base + noise, 20_000)


def generate_invoices(customers_df: pd.DataFrame) -> pd.DataFrame:
    """
    Generate ~600 invoices spanning Jan 2023 – Dec 2024.
    Monthly invoice counts and amounts are calibrated to hit the revenue curve.
    Customer assignment follows a power-law distribution (top 10 = ~60% of revenue).
    Payment terms and overdue rates vary by customer geography.
    """
    customer_ids = customers_df['customer_id'].tolist()
    country_map  = customers_df.set_index('customer_id')['country'].to_dict()

    # Power-law weights: top 10 customers get much higher probability
    weights = np.array([1.0 / (i + 1) ** 0.7 for i in range(N_CUSTOMERS)])
    weights = weights / weights.sum()

    invoices = []
    invoice_id = 5000
    all_months = pd.date_range(START_DATE, END_DATE, freq='MS')

    for month_start in all_months:
        month_date   = month_start.date()
        target_rev   = monthly_revenue_target(month_date)
        n_this_month = max(int(N_INVOICES / 24), 10)   # ~25/month

        # Sample customers for this month
        selected_customers = np.random.choice(
            customer_ids, size=n_this_month, replace=True, p=weights
        )

        # Distribute target revenue across invoices using log-normal amounts
        amounts = np.random.lognormal(mean=8.5, sigma=0.9, size=n_this_month)
        # Scale amounts to hit monthly revenue target
        amounts = amounts / amounts.sum() * target_rev

        for cust_id, amount in zip(selected_customers, amounts):
            amount = round(max(amount, 500), 2)
            country = country_map[cust_id]

            # Payment terms: 30 days standard, some Net-45 or Net-60
            terms = random.choices([30, 45, 60], weights=[0.70, 0.20, 0.10])[0]
            invoice_date = fake.date_between_dates(
                date_start=month_date,
                date_end=(month_date + relativedelta(months=1) - timedelta(days=1))
            )
            due_date = invoice_date + timedelta(days=terms)

            # Determine payment behaviour based on country and macro phase
            is_dip_period = (invoice_date.year == 2023 and 7 <= invoice_date.month <= 9)

            if country == 'Canada':
                overdue_prob = 0.10 if not is_dip_period else 0.18
                avg_days_late = 5
            elif country == 'United States':
                overdue_prob = 0.18 if not is_dip_period else 0.35
                avg_days_late = 18
            else:
                overdue_prob = 0.14 if not is_dip_period else 0.22
                avg_days_late = 12

            # Assign status
            rand = random.random()
            if rand < 0.60:
                status  = 'Paid'
                balance = 0.0
            elif rand < 0.60 + (1 - 0.60 - overdue_prob):
                status  = 'Open'
                balance = amount
            else:
                status  = 'Overdue'
                balance = round(amount * random.uniform(0.3, 1.0), 2)

            invoices.append({
                'invoice_id':   str(invoice_id),
                'customer_id':  cust_id,
                'invoice_date': invoice_date,
                'due_date':     due_date,
                'amount':       amount,
                'balance':      balance,
                'status':       status,
                'loaded_at':    pd.Timestamp.now(),
            })
            invoice_id += 1

    return pd.DataFrame(invoices)

def generate_payments(invoices_df: pd.DataFrame) -> pd.DataFrame:
    """
    Generate one payment per Paid invoice, plus partial payments on ~20% of Open invoices.
    Payment date = invoice_date + random(5, avg_days_late) days.
    Payment method follows the defined mix.
    """
    payment_methods = ['Bank Transfer', 'Credit Card', 'Cheque', 'E-Transfer']
    method_weights  = [0.40, 0.35, 0.15, 0.10]

    payments = []
    payment_id = 9000

    paid_invoices = invoices_df[invoices_df['status'] == 'Paid']
    open_invoices = invoices_df[invoices_df['status'] == 'Open']

    # Full payments for all Paid invoices
    for _, inv in paid_invoices.iterrows():
        days_to_pay = random.randint(5, 40)
        payment_date = inv['invoice_date'] + timedelta(days=days_to_pay)
        payment_date = min(payment_date, TODAY)

        payments.append({
            'payment_id':     str(payment_id),
            'customer_id':    inv['customer_id'],
            'payment_date':   payment_date,
            'amount':         inv['amount'],
            'payment_method': random.choices(payment_methods, weights=method_weights)[0],
            'loaded_at':      pd.Timestamp.now(),
        })
        payment_id += 1

    # Partial payments on ~20% of Open invoices
    partial_open = open_invoices.sample(frac=0.20, random_state=42)
    for _, inv in partial_open.iterrows():
        partial_amount = round(inv['amount'] * random.uniform(0.2, 0.6), 2)
        days_to_pay    = random.randint(10, 60)
        payment_date   = inv['invoice_date'] + timedelta(days=days_to_pay)
        payment_date   = min(payment_date, TODAY)

        payments.append({
            'payment_id':     str(payment_id),
            'customer_id':    inv['customer_id'],
            'payment_date':   payment_date,
            'amount':         partial_amount,
            'payment_method': random.choices(payment_methods, weights=method_weights)[0],
            'loaded_at':      pd.Timestamp.now(),
        })
        payment_id += 1

    return pd.DataFrame(payments)


def generate_coa_mapping() -> pd.DataFrame:
    """
    Returns the standard QBO chart of accounts for Professional Services.
    Extend this list to cover every account in your target client's CoA.
    The structure here matches the table definition in Workshop 3.
    """
    rows = [
        # gl_account, account_name, fs_line_item, statement, section,
        # subsection, display_order, sign, is_wc, is_non_cash, cf_category,
        # is_kpi_num, is_kpi_den, benchmark_sector
        ('4000','Product Revenue','Revenue','P&L','Income','Product',1,'Positive',0,0,'Operating',1,0,'Professional Services'),
        ('4100','Service Revenue','Revenue','P&L','Income','Services',2,'Positive',0,0,'Operating',1,0,'Professional Services'),
        ('4200','Other Income','Revenue','P&L','Income','Other',3,'Positive',0,0,'Operating',0,0,'Professional Services'),
        ('5000','COGS — Materials','Cost of Goods Sold','P&L','COGS','Direct',4,'Negative',0,0,'Operating',0,0,'Professional Services'),
        ('5100','COGS — Direct Labour','Cost of Goods Sold','P&L','COGS','Direct',5,'Negative',0,0,'Operating',0,0,'Professional Services'),
        ('6000','Salaries & Wages','Operating Expenses','P&L','OpEx','Payroll',6,'Negative',0,0,'Operating',0,0,'Professional Services'),
        ('6100','Depreciation','Operating Expenses','P&L','OpEx','Non-Cash',7,'Negative',0,1,'Operating',0,0,'Professional Services'),
        ('6200','Amortisation','Operating Expenses','P&L','OpEx','Non-Cash',8,'Negative',0,1,'Operating',0,0,'Professional Services'),
        ('6300','Rent & Occupancy','Operating Expenses','P&L','OpEx','Facilities',9,'Negative',0,0,'Operating',0,0,'Professional Services'),
        ('6400','Marketing & Advertising','Operating Expenses','P&L','OpEx','Marketing',10,'Negative',0,0,'Operating',0,0,'Professional Services'),
        ('6500','Professional Fees','Operating Expenses','P&L','OpEx','Professional',11,'Negative',0,0,'Operating',0,0,'Professional Services'),
        ('6600','Software & Subscriptions','Operating Expenses','P&L','OpEx','Technology',12,'Negative',0,0,'Operating',0,0,'Professional Services'),
        ('6700','Travel & Entertainment','Operating Expenses','P&L','OpEx','Travel',13,'Negative',0,0,'Operating',0,0,'Professional Services'),
        ('6800','Insurance','Operating Expenses','P&L','OpEx','Insurance',14,'Negative',0,0,'Operating',0,0,'Professional Services'),
        ('6900','Bank Charges & Interest','Operating Expenses','P&L','OpEx','Finance',15,'Negative',0,0,'Operating',0,0,'Professional Services'),
        ('1000','Cash & Equivalents','Current Assets','Balance Sheet','Current Assets','Cash',1,'Positive',0,0,'N/A',1,0,'Professional Services'),
        ('1200','Accounts Receivable','Current Assets','Balance Sheet','Current Assets','Receivable',2,'Positive',1,0,'Operating',1,0,'Professional Services'),
        ('1300','Prepaid Expenses','Current Assets','Balance Sheet','Current Assets','Prepaid',3,'Positive',1,0,'Operating',0,0,'Professional Services'),
        ('1400','Inventory','Current Assets','Balance Sheet','Current Assets','Inventory',4,'Positive',1,0,'Operating',0,0,'Professional Services'),
        ('1500','Equipment','Non-Current Assets','Balance Sheet','Non-Current Assets','Fixed',5,'Positive',0,0,'Investing',0,0,'Professional Services'),
        ('1600','Accumulated Depreciation','Non-Current Assets','Balance Sheet','Non-Current Assets','Fixed',6,'Negative',0,0,'Investing',0,0,'Professional Services'),
        ('1700','Intangible Assets','Non-Current Assets','Balance Sheet','Non-Current Assets','Intangible',7,'Positive',0,0,'Investing',0,0,'Professional Services'),
        ('2000','Accounts Payable','Current Liabilities','Balance Sheet','Current Liabilities','Payables',8,'Positive',1,0,'Operating',0,1,'Professional Services'),
        ('2100','Accrued Liabilities','Current Liabilities','Balance Sheet','Current Liabilities','Accrued',9,'Positive',1,0,'Operating',0,0,'Professional Services'),
        ('2200','Deferred Revenue','Current Liabilities','Balance Sheet','Current Liabilities','Deferred',10,'Positive',1,0,'Operating',0,0,'Professional Services'),
        ('2300','Income Tax Payable','Current Liabilities','Balance Sheet','Current Liabilities','Tax',11,'Positive',0,0,'Operating',0,0,'Professional Services'),
        ('2500','Long-Term Debt','Non-Current Liabilities','Balance Sheet','Non-Current Liabilities','Debt',12,'Positive',0,0,'Financing',0,1,'Professional Services'),
        ('2600','Deferred Tax Liability','Non-Current Liabilities','Balance Sheet','Non-Current Liabilities','Tax',13,'Positive',0,0,'N/A',0,0,'Professional Services'),
        ('3000','Share Capital','Equity','Balance Sheet','Equity','Capital',14,'Positive',0,0,'Financing',0,0,'Professional Services'),
        ('3100','Retained Earnings','Equity','Balance Sheet','Equity','Retained',15,'Positive',0,0,'N/A',0,0,'Professional Services'),
        ('3200','Current Year Earnings','Equity','Balance Sheet','Equity','Current',16,'Positive',0,0,'N/A',0,0,'Professional Services'),
    ]

    columns = [
        'gl_account','account_name','fs_line_item','statement','section',
        'subsection','display_order','sign','is_working_capital','is_non_cash',
        'cash_flow_category','is_kpi_numerator','is_kpi_denominator','benchmark_sector'
    ]
    return pd.DataFrame(rows, columns=columns)


def generate_macro_indicators() -> pd.DataFrame:
    """
    Generates 24 monthly rows of macro data aligned to the revenue narrative.
    Bank of Canada rate rises into the dip period, then stabilises.
    CPI elevated during dip, moderates in 2024.
    """
    months = pd.date_range(START_DATE, END_DATE, freq='MS')
    records = []

    for i, month in enumerate(months):
        yr, mo = month.year, month.month

        # Bank of Canada rate: rises Jan–Sep 2023, holds, slight cut 2024
        if yr == 2023:
            if mo <= 6:
                bank_rate = 0.0425 + i * 0.0025          # Rising from 4.25%
            elif mo <= 9:
                bank_rate = 0.0500                        # Peak at 5.00%
            else:
                bank_rate = 0.0500                        # Holds
        else:
            if mo <= 6:
                bank_rate = 0.0500                        # Holds into 2024
            else:
                bank_rate = 0.0500 - (mo - 6) * 0.0025   # Gradual cuts

        bank_rate = round(max(bank_rate, 0.0300), 4)

        # CPI: elevated during dip, moderating 2024
        if yr == 2023 and 6 <= mo <= 10:
            cpi = round(np.random.normal(155.0, 0.5), 2)
        elif yr == 2024:
            cpi = round(np.random.normal(150.0 - mo * 0.2, 0.4), 2)
        else:
            cpi = round(np.random.normal(148.0, 0.6), 2)

        # GDP growth: quarterly, forward-filled monthly
        gdp_growth = round(np.random.normal(0.012 if yr == 2024 else 0.008, 0.003), 4)

        # USD/CAD: slightly elevated during rate peak
        usd_cad = round(np.random.normal(1.34 if bank_rate >= 0.05 else 1.36, 0.008), 4)

        # Sector index and consumer confidence
        sector_index       = round(np.random.normal(105 if yr == 2024 else 98, 2.0), 2)
        consumer_confidence = round(np.random.normal(58 if bank_rate >= 0.05 else 64, 1.5), 2)

        records.append({
            'indicator_date':      month.date(),
            'bank_rate':           bank_rate,
            'cpi':                 cpi,
            'gdp_growth':          gdp_growth,
            'usd_cad':             usd_cad,
            'sector_index':        sector_index,
            'consumer_confidence': consumer_confidence,
            'loaded_at':           pd.Timestamp.now(),
        })

    return pd.DataFrame(records)


def recalculate_customer_balances(customers_df: pd.DataFrame,
                                  invoices_df: pd.DataFrame) -> pd.DataFrame:
    """
    Update customer.balance to equal the sum of open invoice balances.
    QBO's Customer.Balance reflects total AR outstanding per customer.
    """
    ar_by_customer = (
        invoices_df[invoices_df['balance'] > 0]
        .groupby('customer_id')['balance']
        .sum()
        .reset_index()
        .rename(columns={'balance': 'calculated_balance'})
    )
    customers_df = customers_df.merge(ar_by_customer, on='customer_id', how='left')
    customers_df['balance'] = customers_df['calculated_balance'].fillna(0).round(2)
    customers_df = customers_df.drop(columns=['calculated_balance'])
    return customers_df

def load_to_sql(df: pd.DataFrame, table_name: str, schema: str = 'qbo') -> None:
    full_table = f"{schema}.{table_name}"
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE TABLE {full_table}"))
        print(f"  Truncated {full_table}")
    df.to_sql(
        name=table_name,
        con=engine,
        schema=schema,
        if_exists='append',
        index=False,
        chunksize=100,      # 8 cols × 100 rows = 800 params — well under 2100
    )
    print(f"  Loaded {len(df):,} rows → {full_table}")


def main():
    print("\n── Generating synthetic QBO data ─────────────────────────────────────")

    print("\n[1/6] Generating customers...")
    customers = generate_customers(N_CUSTOMERS)
    print(f"  {len(customers)} customers generated")

    print("\n[2/6] Generating invoices...")
    invoices = generate_invoices(customers)
    print(f"  {len(invoices)} invoices generated")
    print(f"  Date range: {invoices['invoice_date'].min()} → {invoices['invoice_date'].max()}")
    print(f"  Status mix:\n{invoices['status'].value_counts().to_string()}")

    print("\n[3/6] Recalculating customer balances...")
    customers = recalculate_customer_balances(customers, invoices)

    print("\n[4/6] Generating payments...")
    payments = generate_payments(invoices)
    print(f"  {len(payments)} payments generated")

    print("\n[5/6] Generating CoA mapping and macro indicators...")
    coa     = generate_coa_mapping()
    macro   = generate_macro_indicators()
    print(f"  {len(coa)} CoA accounts | {len(macro)} macro months")

    print("\n[6/6] Loading to Azure SQL...")
    load_to_sql(customers, 'stg_customers')
    load_to_sql(invoices,  'stg_invoices')
    load_to_sql(payments,  'stg_payments')
    load_to_sql(coa,       'coa_mapping')
    load_to_sql(macro,     'macro_indicators')

    print("\n── Data generation complete ───────────────────────────────────────────")
    print("Run infrastructure/sql/05_verification_queries.sql to verify results.")


if __name__ == '__main__':
    main()
    
