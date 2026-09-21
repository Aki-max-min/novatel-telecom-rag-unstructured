// ===========================================================================
// NovaTel UNIFIED graph - cross-branch Cypher queries
// ===========================================================================
// Prerequisites (in this order):
//     python -m knowledge_graph.graph_loader              document KG    363 nodes / 1,473 rels
//     python -m knowledge_graph.structured_graph_loader   structured KG  43,928 / 31,027
//     python -m knowledge_graph.concept_bridge --load     concept layer  23 Concepts + 28 EntityTypes
//                                                                        + 61 bridge edges + 43,928 INSTANCE_OF
//
// THE JOIN RULE
// -------------
// The two branches are joined on the CONCEPT NAME, never on the C01-C29 code.
// The codes conflict across branches and a code join is silently wrong:
//     structured C11 = tickets        vs  document C11 = International Calling
//     structured C18 = porting        vs  document C18 = Security & Fraud
//     structured C05 = payments       vs  document C05 = SIM Card Services
// Only 8 of 28 structured entity types agree with the document branch on their
// code. Every query below crosses at (:Concept).
//
// Shape of the bridge:
//     (Document)-[:BELONGS_TO_CATEGORY]->(Category)-[:EXPRESSES_CONCEPT]->(Concept)
//     (Document)-[:MENTIONS_SERVICE]->(Service)-[:EXPRESSES_CONCEPT]->(Concept)
//     (Concept)<-[:REALIZES_CONCEPT]-(EntityType)<-[:INSTANCE_OF]-(row)-[:OF_CUSTOMER]->(Customer)
//
// Every query is LIMITed so the browser draws a readable picture.
// ===========================================================================


// --- U1 -------------------------------------------------------------------
// The whole bridge at a glance: which concepts join which side to which.
// A table, not a picture - the fastest way to see the crosswalk in the db.
MATCH (c:Concept)
OPTIONAL MATCH (c)<-[:REALIZES_CONCEPT]-(t:EntityType)
OPTIONAL MATCH (c)<-[:EXPRESSES_CONCEPT]-(hub)
RETURN c.name AS concept,
       collect(DISTINCT t.entity_type) AS structured_entity_types,
       collect(DISTINCT labels(hub)[0] + ':' + hub.key) AS document_hubs,
       c.bridges_both_sides AS bridges_both_sides
ORDER BY concept
LIMIT 25;


// --- U2 -------------------------------------------------------------------
// One concept end to end as a picture: the governing documents on the left,
// the database rows and their customers on the right. Swap the concept name.
MATCH p1 = (d:Document)-[:BELONGS_TO_CATEGORY|MENTIONS_SERVICE]->(hub)
           -[:EXPRESSES_CONCEPT]->(c:Concept {name: 'KYC & Identity Verification'})
WITH c, p1 LIMIT 10
MATCH p2 = (c)<-[:REALIZES_CONCEPT]-(:EntityType)<-[:INSTANCE_OF]-(row)-[:OF_CUSTOMER]->(:Customer)
RETURN p1, p2
LIMIT 25;


// --- U3 -------------------------------------------------------------------
// "Everything about KYC": the policy and FAQ documents that govern KYC, beside
// real KYC records and the customers they belong to.
MATCH (c:Concept {name: 'KYC & Identity Verification'})<-[:EXPRESSES_CONCEPT]-(hub)
MATCH (d:Document)-[:BELONGS_TO_CATEGORY|MENTIONS_SERVICE]->(hub)
WHERE d.resolved = true
WITH collect(DISTINCT d.key) AS governing_documents
MATCH (k:KYCRecord)-[:OF_CUSTOMER]->(cust:Customer)
RETURN governing_documents[0..10] AS governing_documents,
       size(governing_documents) AS document_count,
       k.kyc_id AS kyc_id, k.kyc_type AS kyc_type, k.status AS kyc_status,
       cust.customer_id AS customer_id, cust.name AS customer_name
ORDER BY kyc_id
LIMIT 10;


// --- U4 -------------------------------------------------------------------
// The complaint view - the code-conflict case. Structured tickets are filed
// under C11 and complaint documents under C16, so only the concept joins them.
// Returns complaint documentation alongside real escalation chains.
MATCH (c:Concept {name: 'Complaints & Grievances'})
MATCH p1 = (d:Document)-[:BELONGS_TO_CATEGORY]->(:Category)-[:EXPRESSES_CONCEPT]->(c)
WITH c, p1 LIMIT 8
MATCH p2 = (c)<-[:REALIZES_CONCEPT]-(:EntityType {entity_type: 'EscalationCase'})
           <-[:INSTANCE_OF]-(e:EscalationCase)-[:ESCALATES_TICKET]->(t:Ticket)
           -[:OF_CUSTOMER]->(cust:Customer)
RETURN p1, p2
LIMIT 25;


// --- U5 -------------------------------------------------------------------
// Number Portability: structured C18 vs document C06 - another code conflict.
// The porting documentation next to the actual porting requests.
MATCH (c:Concept {name: 'Number Portability'})
OPTIONAL MATCH (d:Document)-[:BELONGS_TO_CATEGORY|MENTIONS_SERVICE]->(hub)-[:EXPRESSES_CONCEPT]->(c)
WITH c, collect(DISTINCT d.key) AS docs
MATCH (p:PortingRequest)-[:OF_CUSTOMER]->(cust:Customer)
RETURN docs[0..8] AS porting_documents,
       p.port_id AS port_id, p.status AS status,
       p.request_date AS requested_on,
       cust.customer_id AS customer_id, cust.circle AS customer_circle
ORDER BY port_id
LIMIT 15;


// --- U6 -------------------------------------------------------------------
// THE CONNECTIVITY PROOF: a shortest path from a document to a real customer.
// Before the concept layer this returned nothing - the two graphs were islands.
MATCH (d:Document {key: 'FAQ_C01_001'}), (cust:Customer {id: 'Customer:1829'})
MATCH p = shortestPath((d)-[*..8]-(cust))
RETURN p
LIMIT 1;


// --- U7 -------------------------------------------------------------------
// Documentation coverage vs data volume: which concepts are well documented
// relative to how much data they carry, and which are thin.
// High rows + low docs = a documentation gap.
MATCH (c:Concept)<-[:REALIZES_CONCEPT]-(t:EntityType)
OPTIONAL MATCH (i:StructuredEntity)-[:INSTANCE_OF]->(t)
WITH c, count(i) AS rows
OPTIONAL MATCH (d:Document)-[:BELONGS_TO_CATEGORY|MENTIONS_SERVICE]->(hub)-[:EXPRESSES_CONCEPT]->(c)
WHERE d.resolved = true
RETURN c.name AS concept,
       rows AS database_rows,
       count(DISTINCT d) AS documents
ORDER BY database_rows DESC
LIMIT 25;


// --- U8 -------------------------------------------------------------------
// From one customer back out to the documentation that governs their records:
// customer -> their rows -> entity type -> concept -> documents.
// "What does the knowledge base say about the things this customer has?"
MATCH p = (cust:Customer {id: 'Customer:1829'})<-[:OF_CUSTOMER]-(row)
          -[:INSTANCE_OF]->(:EntityType)-[:REALIZES_CONCEPT]->(c:Concept)
RETURN p
LIMIT 25;


// ===========================================================================
// VERIFICATION
// ===========================================================================

// Concept layer counts - expect 23 concepts, 28 REALIZES, 33 EXPRESSES.
MATCH (c:Concept) WITH count(c) AS concept_nodes
MATCH (:EntityType)-[r1:REALIZES_CONCEPT]->(:Concept) WITH concept_nodes, count(r1) AS realizes
MATCH ()-[r2:EXPRESSES_CONCEPT]->(:Concept)
RETURN concept_nodes, realizes, count(r2) AS expresses;

// Concepts that bridge both sides - expect 22 of 23
// (Retail & Store Network is structured-only: no document category covers it).
MATCH (c:Concept)
WHERE EXISTS { (c)<-[:REALIZES_CONCEPT]-(:EntityType) }
  AND EXISTS { (c)<-[:EXPRESSES_CONCEPT]-() }
RETURN count(c) AS concepts_bridging_both_sides;

// Whole database - expect 44,342 nodes and 76,489 relationships
// (44,291 graph nodes + 23 Concept + 28 EntityType;
//  32,500 graph rels + 61 bridge + 43,928 INSTANCE_OF).
MATCH (n) WITH count(n) AS nodes
MATCH ()-[r]->()
RETURN nodes, count(r) AS relationships;
