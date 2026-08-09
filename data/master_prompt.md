# Master Prompt Used for This Generation

```
You are a Senior Telecom Knowledge Engineer, Technical Writer, and AI Solutions Architect.  Your task is to **generate a complete unstructured telecom knowledge base** for a hypothetical mobile operator’s RAG (Retrieval-Augmented Generation) project.  The knowledge base will include FAQ entries, Knowledge Base (KB) articles, SOPs, Policy documents, Incident Reports, RCAs, Training Manuals, Release Notes, Tariff Catalogues, Coverage Maps descriptions, User Manuals, Support Scripts (call-centre transcripts), and sample Customer Service Emails.  

For each **document type**, adhere to the following guidelines:

- **Purpose & Scope**: Explain why this document exists and which customer question categories it addresses (e.g. billing, recharge, SIM, network, offers, security, etc.). Map each document to the relevant question category codes (e.g., C01–C29 from the telecom question taxonomy).  
- **Schema/Metadata Fields**: Define a structured metadata schema for each document type, including fields like `document_id`, `title`, `category`, `department`, `last_updated`, `version`, `source_authority`, `customer_scope` (prepaid/postpaid/enterprise), `related_ids` (links to FAQs/KDs/RCA/etc.), and `tags`. Specify field formats (string, date, enum).  
- **File Format & Naming**: Specify the output format(s) (PDF, DOCX, MD, JSON) and a filename convention (e.g. `FAQ_C02_001.json`, `KB_C03_recharge_guide.md`, etc.).  
- **Content Structure**: Provide an outline with headings/subheadings. Use numbered steps, bullet lists, tables, decision trees, flowcharts (Mermaid if possible) to organise content. Keep paragraphs concise. Each document should be chunk-friendly (500–800 tokens with ~50–100 token overlap), so use clear section breaks and short paragraphs.  
- **Quantity & Examples**: Generate a realistic volume of content: e.g. 100–150 FAQs, 30–50 KB articles, 15–25 SOPs, 10–15 Policies, 10–20 Incident Reports, 5–10 RCAs, 5–10 Training Manuals, 3–5 Release Notes, 2–3 Tariff Catalogues, 2–3 Coverage Map descriptions, 5–10 User Guides, 10–15 Support Scripts, 10–20 Sample Emails. For each type, *include one fully fleshed-out example document* (with content and metadata) demonstrating structure, style, and formatting.  
- **Tone & Style**: Maintain an enterprise-professional tone suitable for internal company documentation. Use British English spelling. Cite real public sources (TRAI, operator help pages) where appropriate for factual claims or standard info. Ensure no real personal data (use synthetic names/IDs).  
- **Cross-References**: Embed `document_id` references and links between FAQs, KBs, SOPs, policies, etc. (e.g. FAQ answer may point to a relevant SOP or policy by ID). Use the `related_ids` field to link related documents.  
- **Metadata & Taxonomy**: Tag each document with the appropriate question-category (C01–C29) and department (e.g. Billing, Network, Customer Care, Legal).  Include a master **document_manifest.json** listing all generated files with their metadata (id, title, type, category, path). Also generate a **source_registry.json** listing source authority (internal knowledge base vs external reference docs).  
- **Quality & Validation**: Ensure coverage (question categories 1–29 are all addressed by some document). Check consistency: terminology, currency symbol (₹), date formats, style. All content must be accurate telecom domain information (even if synthetic). Provide a short bibliography of sources (URLs) used for facts.  
- **Diagrams**: For mapping question → document → data, include a Mermaid diagram illustrating how different document types support user intents. E.g. a flowchart linking sample question categories to document types.  
- **Output Package**: Instruct Claude to output *all files in a ZIP archive* with this folder layout:
  ```
  data/raw/unstructured/
      faq/
      kb/
      sops/
      policies/
      incidents/
      rca/
      training/
      release_notes/
      tariff/
      coverage_maps/
      manuals/
      transcripts/
      emails/
  ```
  Include the **document_manifest.json** and **source_registry.json** at the root.  

**Example**: Include one complete example (metadata + content) for each doc type. For instance, for FAQs:
```
FAQ_C02_001.json:
{
  "faq_id": "FAQ_C02_001",
  "question": "When does my plan expire?",
  "answer": "Your plan expiry depends on your subscription record. Check the My Plan section in the app. If your plan is prepaid, it typically lasts 28 days from activation. The expiry date shown is YYYY-MM-DD.",
  "category": "C02",
  "department": "Product",
  "customer_scope": "prepaid",
  "last_updated": "2026-08-08",
  "version": "1.0",
  "source_authority": "Internal Knowledge Base",
  "related_ids": ["KB_C02_plan_expiry", "Policy_C04_billing"],
  "tags": ["plan","expiry","subscription"]
}
```
And for a SOP:
```
SOP_C03_RECHARGE_FAILURE.docx:
Purpose: ...
...
```
(Instruct Claude to output in Word format for SOPs, PDF for policies, Markdown for KBs, JSON for FAQs, etc.)  

Finally, provide a **Word summary document** that outlines this generation plan, lists the number of documents per type, and explains how these outputs will feed into the RAG ingestion pipeline (categorisation, chunking, vectorisation). This summary should look like an executive-ready overview.  

**Constraints**: No real PII. Synthetic data only. If any detail is unspecified, mark it “UNSPECIFIED”. 

**Deliverables**:  
- The full master prompt text (as above).  
- A one-page executive summary (Word format) describing what the prompt generates and how it maps to the RAG pipeline.  
```
```
