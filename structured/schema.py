"""
Formal schema registry for all 28 structured tables in the NovaTel RAG system.
This is the single source of truth for column names, types, keys, and relationships.
"""

TABLE_SCHEMAS = {
    "customer_master": {
        "primary_key": "customer_id",
        "foreign_keys": {},
        "columns": {
            "customer_id": "integer", "msisdn": "text", "name": "text", "dob": "date",
            "email": "text", "address": "text", "circle": "text", "account_type": "categorical",
            "activation_date": "date", "kyc_status": "categorical", "status": "categorical"
        },
        "nullable": ["name", "dob", "email", "address", "circle", "activation_date"],
        "categorical_fields": ["account_type", "kyc_status", "status"],
        "text_fields": ["name", "email", "address"],
        "date_fields": ["dob", "activation_date"],
        "category_tag": "C01"
    },
    "plan_master": {
        "primary_key": "plan_id",
        "foreign_keys": {},
        "columns": {
            "plan_id": "integer", "plan_name": "text", "price": "numeric", "validity_days": "integer",
            "data_gb": "numeric", "voice_minutes": "text", "sms_limit": "integer",
            "ott_benefits": "text", "fiveg_eligible": "boolean", "auto_renew": "boolean"
        },
        "nullable": [],
        "categorical_fields": [],
        "text_fields": ["plan_name", "ott_benefits"],
        "numeric_fields": ["price", "data_gb"],
        "category_tag": "C02"
    },
    "subscriptions": {
        "primary_key": "subscription_id",
        "foreign_keys": {"customer_id": "customer_master", "plan_id": "plan_master"},
        "columns": {
            "subscription_id": "integer", "customer_id": "integer", "msisdn": "text",
            "plan_id": "integer", "activation_date": "date", "expiry_date": "date",
            "status": "categorical", "renewal_type": "categorical"
        },
        "nullable": [],
        "categorical_fields": ["status", "renewal_type"],
        "date_fields": ["activation_date", "expiry_date"],
        "category_tag": "C02"
    },
    "recharge_transactions": {
        "primary_key": "recharge_id",
        "foreign_keys": {"plan_id": "plan_master"},
        "columns": {
            "recharge_id": "integer", "msisdn": "text", "amount": "numeric", "plan_id": "integer",
            "channel": "categorical", "timestamp": "datetime", "status": "categorical",
            "balance_after": "numeric"
        },
        "nullable": ["channel", "balance_after"],
        "categorical_fields": ["channel", "status"],
        "numeric_fields": ["amount", "balance_after"],
        "datetime_fields": ["timestamp"],
        "category_tag": "C03"
    },
    "invoices": {
        "primary_key": "invoice_id",
        "foreign_keys": {"customer_id": "customer_master"},
        "columns": {
            "invoice_id": "integer", "customer_id": "integer", "billing_cycle_start": "date",
            "billing_cycle_end": "date", "plan_charge": "numeric", "usage_charge": "numeric",
            "vas_charge": "numeric", "tax_gst": "numeric", "late_fee": "numeric",
            "total_amount": "numeric", "due_date": "date", "payment_status": "categorical"
        },
        "nullable": [],
        "categorical_fields": ["payment_status"],
        "numeric_fields": ["plan_charge", "usage_charge", "vas_charge", "tax_gst", "late_fee", "total_amount"],
        "date_fields": ["billing_cycle_start", "billing_cycle_end", "due_date"],
        "category_tag": "C04"
    },
    "payment_transactions": {
        "primary_key": "transaction_id",
        "foreign_keys": {"invoice_id": "invoices", "customer_id": "customer_master"},
        "columns": {
            "transaction_id": "integer", "invoice_id": "integer", "customer_id": "integer",
            "amount": "numeric", "payment_method": "categorical", "status": "categorical",
            "timestamp": "datetime", "gateway_reference": "text"
        },
        "nullable": ["gateway_reference"],
        "categorical_fields": ["payment_method", "status"],
        "numeric_fields": ["amount"],
        "datetime_fields": ["timestamp"],
        "category_tag": "C05"
    },
    "sim_inventory": {
        "primary_key": "sim_id",
        "foreign_keys": {},
        "columns": {
            "sim_id": "integer", "iccid": "text", "msisdn": "text", "sim_type": "categorical",
            "status": "categorical", "issue_date": "date"
        },
        "nullable": ["msisdn", "issue_date"],
        "categorical_fields": ["sim_type", "status"],
        "category_tag": "C06"
    },
    "esim_profiles": {
        "primary_key": "profile_id",
        "foreign_keys": {"customer_id": "customer_master"},
        "columns": {
            "profile_id": "integer", "customer_id": "integer", "qr_code": "text",
            "activation_status": "categorical"
        },
        "nullable": [],
        "categorical_fields": ["activation_status"],
        "category_tag": "C07"
    },
    "network_sites": {
        "primary_key": "site_id",
        "foreign_keys": {},
        "columns": {
            "site_id": "integer", "latitude": "numeric", "longitude": "numeric",
            "technology": "categorical", "status": "categorical"
        },
        "nullable": [],
        "categorical_fields": ["technology", "status"],
        "category_tag": "C08"
    },
    "network_alarms": {
        "primary_key": "alarm_id",
        "foreign_keys": {"site_id": "network_sites"},
        "columns": {
            "alarm_id": "integer", "site_id": "integer", "alarm_type": "text", "severity": "categorical",
            "raised_at": "datetime", "cleared_at": "datetime", "root_cause": "text"
        },
        "nullable": ["cleared_at", "root_cause"],
        "categorical_fields": ["severity"],
        "text_fields": ["alarm_type", "root_cause"],
        "datetime_fields": ["raised_at", "cleared_at"],
        "category_tag": "C08"
    },
    "tickets": {
        "primary_key": "ticket_id",
        "foreign_keys": {"customer_id": "customer_master"},
        "columns": {
            "ticket_id": "integer", "customer_id": "integer", "category": "categorical",
            "subcategory": "categorical", "description": "text", "created_at": "datetime",
            "sla_due_at": "datetime", "status": "categorical", "assigned_to": "text",
            "resolution_notes": "text"
        },
        "nullable": ["subcategory", "description", "assigned_to", "resolution_notes"],
        "categorical_fields": ["category", "subcategory", "status"],
        "text_fields": ["description", "resolution_notes"],  # candidates for semantic search
        "datetime_fields": ["created_at", "sla_due_at"],
        "category_tag": "C11"
    },
    "cdr": {
        "primary_key": "cdr_id",
        "foreign_keys": {},
        "columns": {
            "cdr_id": "integer", "msisdn": "text", "call_type": "categorical",
            "start_time": "datetime", "duration_sec": "integer", "destination": "text",
            "circle": "text", "roaming_flag": "boolean", "charged_amount": "numeric"
        },
        "nullable": ["destination"],
        "categorical_fields": ["call_type"],
        "numeric_fields": ["charged_amount"],
        "datetime_fields": ["start_time"],
        "category_tag": "C27"
    },
    "roaming_usage": {
        "primary_key": "roam_id",
        "foreign_keys": {"customer_id": "customer_master"},
        "columns": {
            "roam_id": "integer", "customer_id": "integer", "country": "categorical",
            "start_date": "date", "end_date": "date", "voice_minutes": "integer",
            "data_mb": "integer", "sms_count": "integer"
        },
        "nullable": [],
        "categorical_fields": ["country"],
        "date_fields": ["start_date", "end_date"],
        "category_tag": "C10"
    },
    "kyc_records": {
        "primary_key": "kyc_id",
        "foreign_keys": {"customer_id": "customer_master"},
        "columns": {
            "kyc_id": "integer", "customer_id": "integer", "kyc_type": "categorical",
            "status": "categorical", "last_updated": "date"
        },
        "nullable": ["last_updated"],
        "categorical_fields": ["kyc_type", "status"],
        "category_tag": "C17"
    },
    "porting_requests": {
        "primary_key": "port_id",
        "foreign_keys": {"customer_id": "customer_master"},
        "columns": {
            "port_id": "integer", "customer_id": "integer", "old_circle": "categorical",
            "new_circle": "categorical", "request_date": "date", "status": "categorical"
        },
        "nullable": [],
        "categorical_fields": ["old_circle", "new_circle", "status"],
        "category_tag": "C18"
    },
    "orders": {
        "primary_key": "order_id",
        "foreign_keys": {"customer_id": "customer_master"},
        "columns": {
            "order_id": "integer", "customer_id": "integer", "order_type": "categorical",
            "order_date": "datetime", "status": "categorical", "amount": "numeric"
        },
        "nullable": [],
        "categorical_fields": ["order_type", "status"],
        "numeric_fields": ["amount"],
        "datetime_fields": ["order_date"],
        "category_tag": "C25"
    },
    "corporate_accounts": {
        "primary_key": "corp_id",
        "foreign_keys": {},
        "columns": {
            "corp_id": "integer", "company_name": "text", "contact_person": "text",
            "contact_phone": "text", "segment": "categorical", "created_at": "date"
        },
        "nullable": ["contact_person", "contact_phone", "created_at"],
        "categorical_fields": ["segment"],
        "category_tag": "C21"
    },
    "device_config": {
        "primary_key": "device_id",
        "foreign_keys": {},
        "columns": {
            "device_id": "integer", "brand": "categorical", "model": "categorical",
            "imei": "text", "fiveg_supported": "boolean"
        },
        "nullable": ["imei"],
        "categorical_fields": ["brand", "model"],
        "category_tag": "C24"
    },
    "device_registry": {
        "primary_key": "registry_id",
        "foreign_keys": {"customer_id": "customer_master", "device_id": "device_config"},
        "columns": {
            "registry_id": "integer", "customer_id": "integer", "device_id": "integer",
            "registered_at": "date"
        },
        "nullable": [],
        "date_fields": ["registered_at"],
        "category_tag": "C24"
    },
    "retail_outlets": {
        "primary_key": "outlet_id",
        "foreign_keys": {},
        "columns": {
            "outlet_id": "integer", "name": "text", "city": "categorical",
            "address": "text", "phone": "text"
        },
        "nullable": ["address", "phone"],
        "categorical_fields": ["city"],
        "category_tag": "C23"
    },
    "technicians": {
        "primary_key": "tech_id",
        "foreign_keys": {},
        "columns": {
            "tech_id": "integer", "name": "text", "skill": "categorical", "phone": "text"
        },
        "nullable": ["phone"],
        "categorical_fields": ["skill"],
        "category_tag": "C23"
    },
    "ott_subscriptions": {
        "primary_key": "ott_id",
        "foreign_keys": {"customer_id": "customer_master"},
        "columns": {
            "ott_id": "integer", "customer_id": "integer", "service_name": "categorical",
            "start_date": "date", "end_date": "date"
        },
        "nullable": [],
        "categorical_fields": ["service_name"],
        "date_fields": ["start_date", "end_date"],
        "category_tag": "C14"
    },
    "offers": {
        "primary_key": "offer_id",
        "foreign_keys": {},
        "columns": {
            "offer_id": "integer", "offer_name": "text", "discount_percent": "integer",
            "valid_from": "date", "valid_to": "date"
        },
        "nullable": [],
        "date_fields": ["valid_from", "valid_to"],
        "category_tag": "C15"
    },
    "fraud_cases": {
        "primary_key": "case_id",
        "foreign_keys": {"customer_id": "customer_master"},
        "columns": {
            "case_id": "integer", "customer_id": "integer", "case_type": "categorical",
            "reported_at": "datetime", "status": "categorical"
        },
        "nullable": [],
        "categorical_fields": ["case_type", "status"],
        "datetime_fields": ["reported_at"],
        "category_tag": "C16"
    },
    "vas_subscriptions": {
        "primary_key": "vas_id",
        "foreign_keys": {"customer_id": "customer_master"},
        "columns": {
            "vas_id": "integer", "customer_id": "integer", "service_name": "categorical",
            "start_date": "date", "end_date": "date"
        },
        "nullable": [],
        "categorical_fields": ["service_name"],
        "date_fields": ["start_date", "end_date"],
        "category_tag": "C26"
    },
    "coverage_5g": {
        "primary_key": "coverage_id",
        "foreign_keys": {},
        "columns": {
            "coverage_id": "integer", "region": "categorical", "coverage_percent": "numeric",
            "last_updated": "date"
        },
        "nullable": [],
        "categorical_fields": ["region"],
        "numeric_fields": ["coverage_percent"],
        "category_tag": "C28"
    },
    "fiber_inventory": {
        "primary_key": "fiber_id",
        "foreign_keys": {"customer_id": "customer_master"},
        "columns": {
            "fiber_id": "integer", "customer_id": "integer", "installation_date": "date",
            "status": "categorical", "speed_mbps": "integer"
        },
        "nullable": [],
        "categorical_fields": ["status"],
        "date_fields": ["installation_date"],
        "category_tag": "C12"
    },
    "escalation_cases": {
        "primary_key": "escalation_id",
        "foreign_keys": {"ticket_id": "tickets"},
        "columns": {
            "escalation_id": "integer", "ticket_id": "integer", "escalated_at": "datetime",
            "level": "categorical", "status": "categorical"
        },
        "nullable": [],
        "categorical_fields": ["level", "status"],
        "datetime_fields": ["escalated_at"],
        "category_tag": "C29"
    },
}

def get_schema(table_name):
    """Return schema dict for a given table, or None if not found."""
    return TABLE_SCHEMAS.get(table_name)

def list_tables():
    """Return all registered table names."""
    return list(TABLE_SCHEMAS.keys())

def get_tables_by_category(category_tag):
    """Return all tables tagged with a given customer-question category (e.g. 'C04')."""
    return [t for t, s in TABLE_SCHEMAS.items() if s.get("category_tag") == category_tag]

if __name__ == "__main__":
    print(f"Registered tables: {len(TABLE_SCHEMAS)}")
    for t in list_tables():
        print(f"  - {t} (PK: {TABLE_SCHEMAS[t]['primary_key']}, category: {TABLE_SCHEMAS[t].get('category_tag')})")