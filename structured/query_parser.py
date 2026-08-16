"""
Rule-based query parser: converts a natural-language question into
a structured intent (table, retrieval method, filters) the retriever can execute.
"""

import re

# Maps keywords in the question to the table they most likely refer to
KEYWORD_TABLE_MAP = {
    "plan": "subscriptions",
    "account": "customer_master",
    "profile": "customer_master",
    "subscription": "subscriptions",
    "bill": "invoices",
    "invoice": "invoices",
    "recharge": "recharge_transactions",
    "top-up": "recharge_transactions",
    "payment": "payment_transactions",
    "paid": "payment_transactions",
    "sim": "sim_inventory",
    "esim": "esim_profiles",
    "outage": "network_alarms",
    "network alarm": "network_alarms",
    "tower": "network_sites",
    "site": "network_sites",
    "ticket": "tickets",
    "complaint": "tickets",
    "call": "cdr",
    "cdr": "cdr",
    "roaming": "roaming_usage",
    "kyc": "kyc_records",
    "port": "porting_requests",
    "porting": "porting_requests",
    "order": "orders",
    "corporate": "corporate_accounts",
    "device": "device_config",
    "outlet": "retail_outlets",
    "store": "retail_outlets",
    "technician": "technicians",
    "ott": "ott_subscriptions",
    "offer": "offers",
    "fraud": "fraud_cases",
    "vas": "vas_subscriptions",
    "5g coverage": "coverage_5g",
    "fiber": "fiber_inventory",
    "broadband": "fiber_inventory",
    "escalation": "escalation_cases",
}

# Words that suggest the question wants a COUNT/aggregate rather than a specific record
AGGREGATE_KEYWORDS = ["how many", "count of", "total number", "number of"]

# Maps each table to the ACTUAL column name that holds its status-like field
# (not every table calls it "status" -- e.g. invoices uses "payment_status")
STATUS_COLUMN_MAP = {
    "customer_master": "status",
    "subscriptions": "status",
    "recharge_transactions": "status",
    "invoices": "payment_status",
    "payment_transactions": "status",
    "sim_inventory": "status",
    "esim_profiles": "activation_status",
    "network_sites": "status",
    "tickets": "status",
    "kyc_records": "status",
    "porting_requests": "status",
    "orders": "status",
    "fraud_cases": "status",
    "fiber_inventory": "status",
    "escalation_cases": "status",
}

# Maps each table to its ACTUAL set of valid status values, with the EXACT
# casing used in the real data. This is what lets us resolve a lowercase,
# natural-language word like "overdue" into the correct "Overdue" stored
# in the database -- and resolve it correctly even when the same lowercase
# word means different casing in different tables (e.g. "pending" is
# "PENDING" in recharge_transactions but "Pending" in kyc_records).
TABLE_STATUS_VALUES = {
    "customer_master": ["Active", "Suspended"],
    "subscriptions": ["Active", "Expired"],
    "recharge_transactions": ["SUCCESS", "FAILED", "PENDING", "REFUNDED"],
    "invoices": ["Unpaid", "Paid", "Overdue"],
    "payment_transactions": ["SUCCESS", "FAILED", "PENDING"],
    "sim_inventory": ["Active", "Inactive", "Blocked"],
    "esim_profiles": ["Active", "Inactive"],
    "network_sites": ["Operational", "Outage"],
    "tickets": ["Open", "InProgress", "Closed"],
    "kyc_records": ["Complete", "Pending", "Expired"],
    "porting_requests": ["Accepted", "Rejected", "Pending"],
    "orders": ["Pending", "Fulfilled", "Cancelled"],
    "fraud_cases": ["Investigating", "Resolved"],
    "fiber_inventory": ["Active", "Suspended"],
    "escalation_cases": ["Open", "Closed"],
}


def extract_customer_id(question):
    """Look for patterns like 'customer 1001', 'customer_id 1001', or a bare 4-digit ID."""
    match = re.search(r"customer[_\s]?(?:id)?\s*[:=]?\s*(\d{4,})", question, re.IGNORECASE)
    if match:
        return int(match.group(1))
    return None


def get_status_column(table_name):
    """Return the correct status-like column name for a given table."""
    return STATUS_COLUMN_MAP.get(table_name, "status")


def extract_status_value_for_table(question, table_name):
    """
    Find a status word in the question, returning the CORRECT casing
    for that specific table's real enum values (not the user's raw casing,
    and not a global casing guess).
    """
    if table_name is None:
        return None

    q_lower = question.lower()
    for status in TABLE_STATUS_VALUES.get(table_name, []):
        if status.lower() in q_lower:
            return status  # canonical casing, scoped to this table's own enum
    return None


def detect_table(question):
    """Find the most likely table based on keyword matches."""
    q_lower = question.lower()
    for keyword, table in KEYWORD_TABLE_MAP.items():
        if keyword in q_lower:
            return table
    return None


def is_aggregate_question(question):
    q_lower = question.lower()
    return any(kw in q_lower for kw in AGGREGATE_KEYWORDS)


def parse_query(question):
    """
    Main entry point. Returns a dict describing what the retriever should do:
    {
        "table": "...",
        "method": "exact_lookup" | "exact_filter" | "aggregate",
        "filter_column": ... or None,
        "filter_value": ... or None
    }
    """
    table = detect_table(question)
    customer_id = extract_customer_id(question)
    aggregate = is_aggregate_question(question)

    if table is None:
        return {"table": None, "method": None, "error": "Could not determine relevant table"}

    status_col = get_status_column(table)
    status_value = extract_status_value_for_table(question, table)

    if aggregate:
        return {
            "table": table,
            "method": "aggregate",
            "filter_column": status_col if status_value else None,
            "filter_value": status_value
        }

    if customer_id is not None:
        return {
            "table": table,
            "method": "exact_filter",
            "filter_column": "customer_id",
            "filter_value": customer_id
        }

    if status_value is not None:
        return {
            "table": table,
            "method": "exact_filter",
            "filter_column": status_col,
            "filter_value": status_value
        }

    return {"table": table, "method": "exact_filter_unresolved", "error": "No specific filter identified"}


if __name__ == "__main__":
    test_questions = [
        "What plan is customer 1001 on?",
        "Show invoices for customer 1009",
        "How many recharge_transactions have status FAILED?",
        "List all overdue invoices",
        "Is there a network outage?",
        "What is customer 1001's account status?",
        "Show all open tickets",
        "Show sim_inventory with status Blocked",
        "Show kyc_records with status Pending",
        "Show porting_requests with status Rejected",
        "Show orders with status Cancelled",
        "Show fraud_cases with status Investigating",
    ]

    for q in test_questions:
        parsed = parse_query(q)
        print(f"Q: {q}")
        print(f"   -> {parsed}\n")