"""Generates structured/tests/join_cases.json: foreign-key-follow cases with ids chosen BY SQL from the database
(nothing about the data is typed by hand except the two questions the task named: invoice 5001 / ticket 11011).
Expected rows are not stored - the test recomputes them from the database. Run: python structured/tests/build_join_cases.py"""

import json
import os
import sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.abspath(os.path.join(HERE, "..", "..", "data", "processed", "structured", "novatel_structured.db"))
db = sqlite3.connect(f"file:{DB.replace(os.sep, '/')}?mode=ro", uri=True)


def one(sql, *p):
    return db.execute(sql, p).fetchone()


def case(name, question, customer_id, parent_table, parent_id, child_table, expect, **extra):
    d = {"name": name, "question": question, "customer_id": customer_id, "parent_table": parent_table,
         "parent_id": parent_id, "child_table": child_table, "expect": expect}
    d.update(extra)
    return d


cases = []
# 1. named task case: invoice 5001 (customer 1001) and its payment transactions
cust = one("SELECT customer_id FROM invoices WHERE invoice_id = '5001'")[0]
cases.append(case("invoice_with_payments",
                  f"For customer {cust}, what is the payment status of invoice 5001 and which payment transactions were made against it?",
                  int(cust), "invoices", "5001", "payment_transactions", "rows"))
# 2. named task case: ticket 11011 (customer 2738) and its escalation case
cust = one("SELECT customer_id FROM tickets WHERE ticket_id = '11011'")[0]
cases.append(case("ticket_with_escalation",
                  f"For customer {cust}, what is the status of ticket 11011 and what level and status does its escalation case have?",
                  int(cust), "tickets", "11011", "escalation_cases", "rows"))
# 3. invoice that belongs to a DIFFERENT customer
other = one("SELECT customer_id FROM customer_master WHERE customer_id <> ? ORDER BY CAST(customer_id AS INTEGER) LIMIT 1",
            str(cases[0]["customer_id"]))[0]
cases.append(case("invoice_of_another_customer",
                  f"For customer {other}, what is the payment status of invoice 5001 and which payment transactions were made against it?",
                  int(other), "invoices", "5001", "payment_transactions", "empty_foreign_parent"))
# 4. ticket that belongs to a different customer
cases.append(case("ticket_of_another_customer",
                  f"For customer {other}, what is the status of ticket 11011 and what level does its escalation case have?",
                  int(other), "tickets", "11011", "escalation_cases", "empty_foreign_parent"))
# 5. unknown parent id
cases.append(case("unknown_invoice_id", "For customer 1001, show invoice 99999999 and which payment transactions were made against it?",
                  1001, "invoices", "99999999", "payment_transactions", "empty_unknown_parent"))
# 6. parent with no children: an invoice with zero payments
r = one("SELECT i.invoice_id, i.customer_id FROM invoices i WHERE NOT EXISTS "
        "(SELECT 1 FROM payment_transactions p WHERE p.invoice_id = i.invoice_id) ORDER BY CAST(i.invoice_id AS INTEGER) LIMIT 1")
if r:   # (in this database every invoice has at least one payment, so this case is skipped)
    cases.append(case("invoice_without_payments",
                      f"For customer {r[1]}, what is the payment status of invoice {r[0]} and which payment transactions were made against it?",
                      int(r[1]), "invoices", r[0], "payment_transactions", "parent_only"))
# 7. a ticket with no escalation case
r = one("SELECT t.ticket_id, t.customer_id FROM tickets t WHERE NOT EXISTS "
        "(SELECT 1 FROM escalation_cases e WHERE e.ticket_id = t.ticket_id) ORDER BY CAST(t.ticket_id AS INTEGER) LIMIT 1")
cases.append(case("ticket_without_escalation",
                  f"For customer {r[1]}, what is the status of ticket {r[0]} and what level and status does its escalation case have?",
                  int(r[1]), "tickets", r[0], "escalation_cases", "parent_only"))
# 8. a table pair with NO foreign key (tickets are not children of invoices)
cases.append(case("pair_without_foreign_key", "For customer 1001, show invoice 5001 and the tickets raised against it",
                  1001, "invoices", "5001", "tickets", "empty_no_fk"))
# 9. a ticket with several escalation cases, if any
r = one("SELECT e.ticket_id, t.customer_id, COUNT(*) c FROM escalation_cases e JOIN tickets t ON t.ticket_id = e.ticket_id "
        "GROUP BY e.ticket_id HAVING c > 1 ORDER BY CAST(e.ticket_id AS INTEGER) LIMIT 1")
if r:
    cases.append(case("ticket_with_several_escalations",
                      f"For customer {r[1]}, what is the status of ticket {r[0]} and what level and status do its escalation cases have?",
                      int(r[1]), "tickets", r[0], "escalation_cases", "rows"))
# 10. injection in the customer id and in the question text
cases.append(case("injection_in_customer_id", "For this customer, what is the payment status of invoice 5001 and which payment transactions were made against it?",
                  "1001' OR '1'='1", "invoices", "5001", "payment_transactions", "empty_injection"))
cases.append(case("injection_in_question_text",
                  "For customer 1001' OR '1'='1, what is the payment status of invoice 5001 and which payment transactions were made against it?",
                  None, "invoices", "5001", "payment_transactions", "rows",
                  note="only the digits 1001 are parsed from the text and every value is parameterised: the injected text changes nothing"))
# 11. parent table without a customer key (cannot be scoped)
cases.append(case("parent_without_customer_key", "For customer 1001, show site 1 and which network alarms were raised for it",
                  1001, "network_sites", "1", "network_alarms", "empty_unscopable"))

with open(os.path.join(HERE, "join_cases.json"), "w", encoding="utf-8") as fh:
    json.dump({"note": "ids chosen by SQL; expected rows are recomputed from the database by test_fk_follow.py",
               "cases": cases}, fh, indent=1)
print(len(cases), "cases written")
