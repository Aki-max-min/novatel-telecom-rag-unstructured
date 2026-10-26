// ===========================================================================
// NovaTel Knowledge Graphs - example Cypher queries
// ===========================================================================
// Load both graphs first:
//     python -m knowledge_graph.graph_loader              (document KG:   363 nodes / 1,473 rels)
//     python -m knowledge_graph.structured_graph_loader   (structured KG: 43,928 nodes / 31,027 rels)
//
// Two graphs share this database and never touch:
//   * document KG   - ids use a DOUBLE colon (Document::FAQ_C01_001), labels
//     Document, Category, Tag, Service, Channel, VerificationMethod, ...
//   * structured KG - ids use a SINGLE colon (Customer:1829), every node carries
//     its EntityType label plus the shared :StructuredEntity label.
// There are zero relationships crossing between them.
//
// Every query below is LIMITed so Neo4j Browser draws a readable picture rather
// than 44,291 nodes. Raise the limits only if you know what you are asking for.
// ===========================================================================


// ===========================================================================
// DOCUMENT KG (5)
// ===========================================================================

// --- D1 -------------------------------------------------------------------
// Which documents are filed under KYC & Identity Verification (C17)?
// The category node plus every document in it - a clean starter picture.
MATCH p = (c:Category {key: 'C17'})<-[:BELONGS_TO_CATEGORY]-(d:Document)
RETURN p
LIMIT 25;


// --- D2 -------------------------------------------------------------------
// Which documents mention OTP, and what words triggered the extraction?
// Every MENTIONS_* edge carries its evidence, so the answer is auditable.
MATCH (d:Document)-[m:MENTIONS_VERIFICATION]->(v:VerificationMethod {key: 'OTP'})
RETURN d.key AS document_id,
       d.document_type AS type,
       m.matched_terms AS matched_terms,
       m.evidence AS evidence
ORDER BY document_id
LIMIT 25;


// --- D3 -------------------------------------------------------------------
// Everything the graph knows about the KYC Verification service:
// the documents that mention it, and which department owns each of them.
MATCH p = (dept:Department)<-[:OWNED_BY_DEPARTMENT]-(d:Document)
          -[:MENTIONS_SERVICE]->(s:Service {key: 'KYC Verification'})
RETURN p
LIMIT 25;


// --- D4 -------------------------------------------------------------------
// "Customers reading this also need..." - documents two hops from FAQ_C01_001
// through a shared Service or Tag, which neither document links to directly.
MATCH p = (d:Document {key: 'FAQ_C01_001'})-[:MENTIONS_SERVICE|HAS_TAG]->(hub)
          <-[:MENTIONS_SERVICE|HAS_TAG]-(other:Document)
WHERE other <> d AND other.resolved = true
RETURN p
LIMIT 25;


// --- D5 -------------------------------------------------------------------
// Broken cross-references: related_ids pointing at documents that were never
// ingested. All 84 are unresolved - this is the work list for fixing metadata.
MATCH p = (d:Document)-[:RELATED_TO]->(missing:Document {resolved: false})
RETURN p
LIMIT 25;


// ===========================================================================
// STRUCTURED KG (5)
// ===========================================================================

// --- S1 -------------------------------------------------------------------
// Customer 360: everything attached to one customer in a single hop -
// subscriptions, invoices, payments, tickets, KYC, devices, orders and more.
// One relationship type (OF_CUSTOMER) replaces a 14-way SQL join.
MATCH p = (c:Customer {id: 'Customer:1829'})<-[:OF_CUSTOMER]-(row)
RETURN p
LIMIT 25;


// --- S2 -------------------------------------------------------------------
// Which complaints escalated, and whose? Two hops:
// Customer <- Ticket <- EscalationCase, with the escalation level.
MATCH p = (c:Customer)<-[:OF_CUSTOMER]-(t:Ticket)<-[:ESCALATES_TICKET]-(e:EscalationCase)
RETURN p
LIMIT 25;


// --- S3 -------------------------------------------------------------------
// A network site and the alarms raised at it (site 9126 is the busiest,
// with 33 alarms). Swap the id for any other site.
MATCH p = (s:NetworkSite {id: 'NetworkSite:9126'})<-[:AT_SITE]-(a:NetworkAlarm)
RETURN p
LIMIT 25;


// --- S4 -------------------------------------------------------------------
// Invoice/payment reconciliation for one customer: what was billed, what was
// actually paid, and how many attempts it took. Note payment_status on the
// invoice can disagree with the payments that exist - see the report.
MATCH (c:Customer {id: 'Customer:1829'})<-[:OF_CUSTOMER]-(i:Invoice)
OPTIONAL MATCH (i)<-[:PAYS_INVOICE]-(p:PaymentTransaction)
RETURN i.invoice_id AS invoice,
       i.total_amount AS billed,
       i.payment_status AS invoice_says,
       sum(CASE WHEN p.status = 'SUCCESS' THEN toFloat(p.amount) ELSE 0.0 END) AS paid_ok,
       count(p) AS payment_attempts,
       collect(DISTINCT p.status) AS attempt_statuses
ORDER BY invoice
LIMIT 25;


// --- S5 -------------------------------------------------------------------
// The busiest accounts: customers with the most attached rows across all 14
// referencing tables. Aggregation only - no picture, so the limit is small.
MATCH (c:Customer)<-[:OF_CUSTOMER]-(row)
RETURN c.customer_id AS customer_id,
       c.account_type AS account_type,
       c.circle AS circle,
       count(row) AS attached_rows,
       count(DISTINCT row.entity_type) AS distinct_entity_types
ORDER BY attached_rows DESC, customer_id
LIMIT 10;


// ===========================================================================
// VERIFICATION (run these to confirm both graphs are loaded and separate)
// ===========================================================================

// Document KG counts - expect 363 nodes / 1,473 relationships.
MATCH (n) WHERE NOT n:StructuredEntity
WITH count(n) AS document_nodes
MATCH (a)-[r]->(b) WHERE NOT a:StructuredEntity AND NOT b:StructuredEntity
RETURN document_nodes, count(r) AS document_rels;

// Structured KG counts - expect 43,928 nodes / 31,027 relationships.
MATCH (n:StructuredEntity)
WITH count(n) AS structured_nodes
MATCH (:StructuredEntity)-[r]->(:StructuredEntity)
RETURN structured_nodes, count(r) AS structured_rels;

// No relationship should cross between the two graphs - expect 0.
MATCH (a)-[r]->(b)
WHERE (a:StructuredEntity) <> (b:StructuredEntity)
RETURN count(r) AS crossover_relationships;
