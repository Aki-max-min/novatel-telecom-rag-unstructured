import sqlite3
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.normpath(os.path.join(SCRIPT_DIR, "..", "data", "processed", "structured", "novatel_structured.db"))

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

# (index_name, table, columns) -- matches the Schema & Storage Plan document exactly
INDEXES = [
    ("idx_customer_msisdn", "customer_master", "msisdn"),
    ("idx_subscriptions_customer", "subscriptions", "customer_id"),
    ("idx_subscriptions_plan", "subscriptions", "plan_id"),
    ("idx_recharge_msisdn", "recharge_transactions", "msisdn"),
    ("idx_recharge_timestamp", "recharge_transactions", "timestamp"),
    ("idx_recharge_status", "recharge_transactions", "status"),
    ("idx_invoices_customer", "invoices", "customer_id"),
    ("idx_invoices_due_date", "invoices", "due_date"),
    ("idx_invoices_payment_status", "invoices", "payment_status"),
    ("idx_payment_invoice", "payment_transactions", "invoice_id"),
    ("idx_payment_customer", "payment_transactions", "customer_id"),
    ("idx_payment_status", "payment_transactions", "status"),
    ("idx_sim_msisdn", "sim_inventory", "msisdn"),
    ("idx_sim_status", "sim_inventory", "status"),
    ("idx_esim_customer", "esim_profiles", "customer_id"),
    ("idx_alarms_site", "network_alarms", "site_id"),
    ("idx_alarms_raised_at", "network_alarms", "raised_at"),
    ("idx_alarms_severity", "network_alarms", "severity"),
    ("idx_tickets_customer", "tickets", "customer_id"),
    ("idx_tickets_category", "tickets", "category"),
    ("idx_tickets_status", "tickets", "status"),
    ("idx_cdr_msisdn", "cdr", "msisdn"),
    ("idx_cdr_start_time", "cdr", "start_time"),
    ("idx_cdr_destination", "cdr", "destination"),
    ("idx_roaming_customer", "roaming_usage", "customer_id"),
    ("idx_kyc_customer", "kyc_records", "customer_id"),
    ("idx_kyc_status", "kyc_records", "status"),
    ("idx_porting_customer", "porting_requests", "customer_id"),
    ("idx_porting_status", "porting_requests", "status"),
    ("idx_orders_customer", "orders", "customer_id"),
    ("idx_orders_status", "orders", "status"),
    ("idx_device_registry_customer", "device_registry", "customer_id"),
    ("idx_device_registry_device", "device_registry", "device_id"),
    ("idx_ott_customer", "ott_subscriptions", "customer_id"),
    ("idx_fraud_customer", "fraud_cases", "customer_id"),
    ("idx_fraud_case_type", "fraud_cases", "case_type"),
    ("idx_vas_customer", "vas_subscriptions", "customer_id"),
    ("idx_fiber_customer", "fiber_inventory", "customer_id"),
    ("idx_escalation_ticket", "escalation_cases", "ticket_id"),
]

created = 0
for idx_name, table, column in INDEXES:
    try:
        cursor.execute(f"CREATE INDEX IF NOT EXISTS {idx_name} ON {table}({column});")
        created += 1
        print(f"Created index: {idx_name} on {table}({column})")
    except sqlite3.OperationalError as e:
        print(f"FAILED: {idx_name} on {table}({column}) -- {e}")

conn.commit()
conn.close()
print(f"\nDone. {created}/{len(INDEXES)} indexes created successfully.")