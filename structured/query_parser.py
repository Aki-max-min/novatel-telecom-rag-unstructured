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


# --- word-boundary matching -------------------------------------------------------------------
# Bare substring tests (`kw in q_lower`) matched inside other words: "important"/"support"/"report" hit
# "port", "postpaid" hit "paid", "inactive" hit "active", "website" hit "site", ... A plain kw is NOT
# the fix: "_" is a regex word character, so "recharge_transactions" would stop matching "recharge".
# Rule used instead: the keyword must not be glued to a letter or digit on either side (underscores,
# spaces, hyphens and punctuation are separators), and keywords may carry an inflection s/es/ed/ing.
_B_BEFORE = r"(?<![a-z0-9])"
_B_AFTER = r"(?![a-z0-9])"


def _keyword_regex(keyword, inflect=True):
    parts = [re.escape(p) for p in re.split(r"\s+", keyword.lower().strip())]
    suffix = r"(?:s|es|ed|ing)?" if inflect else ""
    return re.compile(_B_BEFORE + r"\s+".join(parts) + suffix + _B_AFTER)


_KEYWORD_PATTERNS = {kw: _keyword_regex(kw) for kw in KEYWORD_TABLE_MAP}
_ALL_TABLES = sorted(set(KEYWORD_TABLE_MAP.values()) | set(STATUS_COLUMN_MAP) | set(TABLE_STATUS_VALUES))
_TABLE_NAME_PATTERNS = {t: _keyword_regex(t, inflect=False) for t in _ALL_TABLES}
EXACT_TABLE_SCORE = 100


def extract_status_value_for_table(question, table_name):
    """
    Find a status word in the question, returning the CORRECT casing
    for that specific table's real enum values (not the user's raw casing,
    and not a global casing guess). Whole-word match, no suffixes ("inactive" is not "Active",
    "postpaid" is not "Paid"); longer values are tried first.
    """
    if table_name is None:
        return None

    q_lower = question.lower()
    for status in sorted(TABLE_STATUS_VALUES.get(table_name, []), key=len, reverse=True):
        if _keyword_regex(status, inflect=False).search(q_lower):
            return status  # canonical casing, scoped to this table's own enum
    return None


def score_tables(question):
    """{table: score}. An exact table name in the question scores EXACT_TABLE_SCORE; otherwise the score is
    the number of DISTINCT keywords of that table found (not keyword length)."""
    q_lower = question.lower()
    scores = {}
    for table, pattern in _TABLE_NAME_PATTERNS.items():
        if pattern.search(q_lower):
            scores[table] = EXACT_TABLE_SCORE
    if scores:
        return scores
    for keyword, pattern in _KEYWORD_PATTERNS.items():
        if pattern.search(q_lower):
            table = KEYWORD_TABLE_MAP[keyword]
            scores[table] = scores.get(table, 0) + 1
    return scores


def detect_table_with_error(question):
    """(table, error). Highest score wins; a tie between different tables is never guessed:
    (None, "ambiguous: t1,t2")."""
    scores = score_tables(question)
    if not scores:
        return None, None
    best = max(scores.values())
    winners = sorted(t for t, sc in scores.items() if sc == best)
    if len(winners) > 1:
        return None, "ambiguous: " + ",".join(winners)
    return winners[0], None


def detect_table(question):
    """Find the most likely table (None if nothing matches or the match is ambiguous)."""
    return detect_table_with_error(question)[0]


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
    table, table_error = detect_table_with_error(question)
    customer_id = extract_customer_id(question)
    aggregate = is_aggregate_question(question)

    if table is None:
        return {"table": None, "method": None,
                "error": table_error or "Could not determine relevant table"}

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