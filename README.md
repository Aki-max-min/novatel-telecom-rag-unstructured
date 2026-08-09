NovaTel Telecom RAG — Unstructured Knowledge Retrieval Pipeline

A retrieval-focused RAG foundation for a synthetic enterprise telecom knowledge base.

This repository implements the unstructured-data ingestion, processing, embedding, vector indexing, semantic retrieval, and retrieval evaluation layer of a larger NovaTel Telecom RAG system.

The structured/CSV data layer is maintained separately by the project partner.

Table of Contents

Overview

Project Context

Objectives

Project Scope

Architecture

End-to-End Pipeline

Dataset

Document Types

Category Coverage

Repository Structure

Technology Stack

Pipeline Components

1. Document Discovery and Metadata

2. Document Loading

3. Canonical Document Construction

4. Text Cleaning

5. Document Processing

6. Chunking

7. Embedding Generation

8. Embedding Validation

9. FAISS Vector Index

10. Semantic Retrieval

11. Retrieval Evaluation

12. Retrieval Diagnostics

Retrieval Results

Understanding the Evaluation

Top-1 Miss Analysis

Validation Results

Design Decisions

Current Limitations

Future Improvements

Planned End-to-End RAG Architecture

Installation

Running the Pipeline

Testing and Validation Commands

Generated Artifacts

Reproducibility

Project Milestones

Current Status

Conclusion

Overview

NovaTel Telecom RAG is a retrieval pipeline designed for a synthetic enterprise telecom knowledge base.

The system processes heterogeneous unstructured documents and converts them into a searchable semantic representation.

The current implementation covers the complete pipeline from raw documents to evaluated vector retrieval:

Raw Unstructured Documents
            |
            v
    Document Discovery
            |
            v
     Document Loading
            |
            v
   Metadata / Manifest
            |
            v
   Canonical Document
        Builder
            |
            v
      Text Cleaning
            |
            v
        Chunking
            |
            v
 Sentence Transformer
   all-MiniLM-L6-v2
            |
            v
    384-D Embeddings
            |
            v
      FAISS Index
            |
            v
    Semantic Search
            |
            v
       Top-K Results
            |
            v
 Retrieval Evaluation


The current dataset contains:

148 unstructured documents

148 chunks

148 embeddings

384-dimensional vectors

1 FAISS IndexFlatIP index

29 retrieval benchmark questions

29 benchmark categories

Current retrieval baseline:

Top-1: 26/29 = 89.66%
Top-3: 29/29 = 100.00%
Top-5: 29/29 = 100.00%


Project Context

The larger NovaTel Telecom RAG system consists of two major information sources:

                         NOVATEL RAG SYSTEM
                                |
                +---------------+---------------+
                |                               |
                v                               v
        UNSTRUCTURED DATA                STRUCTURED DATA
          THIS REPOSITORY                 PARTNER COMPONENT
                |                               |
                v                               v
        Semantic Retrieval                Structured Retrieval
                |                               |
                +---------------+---------------+
                                |
                                v
                       Retrieved Context
                                |
                                v
                         Future RAG Layer
                                |
                                v
                              LLM
                                |
                                v
                       Grounded Response


This repository focuses specifically on the unstructured-data retrieval path.

The structured/CSV component is maintained separately by the project partner.

Objectives

The main objectives of this component are:

Ingest heterogeneous enterprise documents.

Normalize them into a common canonical representation.

Preserve important document metadata.

Clean extracted text without destroying semantic information.

Create retrieval-ready chunks.

Generate semantic embeddings.

Store embeddings in a FAISS vector index.

Perform semantic Top-K retrieval.

Build a reproducible retrieval benchmark.

Measure retrieval quality.

Diagnose retrieval failures.

Provide a clean foundation for the future end-to-end RAG system.

Project Scope

Included

Document ingestion

JSON

Markdown

DOCX

Manifest-based discovery

Metadata extraction

Document processing

Canonical document schema

Document builder

JSON semantic conversion

Text cleaning

Processed document generation

Dataset analysis

Retrieval

Document chunking

Sentence-Transformer embeddings

384-dimensional vectors

FAISS vector search

Top-K retrieval

Evaluation

Retrieval benchmark

Top-1 evaluation

Top-3 evaluation

Top-5 evaluation

Retrieval miss diagnostics

Chunk validation

Embedding validation

Not yet included

The following are planned for later stages:

Structured CSV retrieval

Hybrid retrieval

BM25

Cross-encoder reranking

LLM answer generation

Context assembly

Source citation generation

Production API

Deployment

End-to-end answer evaluation

Architecture

Current Unstructured Retrieval Architecture

                    148 Unstructured Documents
                              |
                              v
                   +----------------------+
                   |   Document Loader    |
                   +----------+-----------+
                              |
                              v
                   +----------------------+
                   | Metadata / Manifest  |
                   +----------+-----------+
                              |
                              v
                   +----------------------+
                   | Canonical Document   |
                   | Schema / Builder      |
                   +----------+-----------+
                              |
                              v
                   +----------------------+
                   |     Text Cleaner     |
                   +----------+-----------+
                              |
                              v
                   +----------------------+
                   |       Chunker        |
                   +----------+-----------+
                              |
                              v
                   +----------------------+
                   | Sentence Transformer |
                   |  all-MiniLM-L6-v2    |
                   +----------+-----------+
                              |
                              v
                       384-D Vectors
                              |
                              v
                   +----------------------+
                   |    FAISS IndexFlatIP |
                   +----------+-----------+
                              |
                              v
                      Semantic Search
                              |
                              v
                         Top-K Results
                              |
                              v
                    Retrieval Evaluation


End-to-End Pipeline

The implemented pipeline follows this sequence:

1. Raw Documents
       |
       v
2. Document Discovery
       |
       v
3. Document Loading
       |
       v
4. Metadata Association
       |
       v
5. Canonical Document Construction
       |
       v
6. Text Cleaning
       |
       v
7. Processed Documents
       |
       v
8. Chunking
       |
       v
9. Sentence-Transformer Embeddings
       |
       v
10. Embedding Validation
       |
       v
11. FAISS Index Construction
       |
       v
12. Semantic Retrieval
       |
       v
13. Retrieval Benchmark
       |
       v
14. Retrieval Diagnostics


Each stage is implemented independently so that individual components can be tested, replaced, or improved without redesigning the entire pipeline.

Dataset

The current knowledge base contains:

148 synthetic unstructured documents.

The dataset represents a hypothetical enterprise telecom operator called NovaTel.

All documents are synthetic and intended for RAG development, experimentation, retrieval evaluation, and architecture demonstration.

Document Types

The dataset contains multiple types of enterprise telecom knowledge:

Document TypeCount



Coverage Map Description

2

FAQ

58

Incident Report

10

KB Article

21

Policy

8

RCA

5

Release Notes

3

SOP

12

Sample Email

10

Support Transcript

8

Tariff Catalogue

2

Training Manual

4

User Manual

5

Total

148

The diversity of document types is intentional.

A realistic enterprise RAG system should be able to retrieve information from different knowledge sources such as:

Customer FAQs

Internal procedures

Policies

Incident reports

Support conversations

Training documentation

Manuals

Release notes

Category Coverage

The knowledge base covers 29 telecom categories:

C01
C02
C03
C04
C05
C06
C07
C08
C09
C10
C11
C12
C13
C14
C15
C16
C17
C18
C19
C20
C21
C22
C23
C24
C25
C26
C27
C28
C29


The categories represent areas such as:

Account Management

Plans and Subscriptions

Recharge and Payments

Billing

SIM and SIM Swap

Number Portability

International Roaming

Network Outages and Coverage

Data Speed and FUP

Value Added Services

International Calling

Device Compatibility and VoLTE

Self-Care and App Login

Offers and Promotions

Loyalty

Complaint Escalation

KYC and Re-verification

Fraud and Security

Privacy and Data Requests

Refunds

Account Closure and Reactivation

New SIM Activation

Enterprise Connectivity

IoT / M2M

FTTH Broadband

DND / Spam

Accessibility

Regulatory / QoS

Network and Device Troubleshooting

Repository Structure

NovaTel_Telecom_RAG_Knowledge_Base/
│
├── data/
│   │
│   ├── raw/
│   │   └── unstructured/
│   │       ├── faq/
│   │       ├── kb/
│   │       ├── sops/
│   │       ├── policies/
│   │       ├── incidents/
│   │       ├── rca/
│   │       ├── transcripts/
│   │       ├── emails/
│   │       ├── manuals/
│   │       └── ...
│   │
│   ├── processed/
│   │   └── documents/
│   │
│   └── vectorstore/
│       ├── embeddings.npy
│       ├── faiss.index
│       ├── chunk_metadata.json
│       └── retrieval_evaluation.json
│
├── ingestion/
│   │
│   ├── __init__.py
│   │
│   ├── document_loader.py
│   ├── document_schema.py
│   ├── document_builder.py
│   ├── metadata_loader.py
│   ├── text_cleaner.py
│   ├── chunker.py
│   │
│   ├── process_documents.py
│   ├── chunk_documents.py
│   ├── embed_chunks.py
│   ├── build_faiss_index.py
│   │
│   ├── analyze_documents.py
│   ├── analyze_categories.py
│   ├── find_spacing_issues.py
│   ├── inspect_docx.py
│   │
│   ├── test_all_documents.py
│   ├── test_cleaning.py
│   ├── test_document_builder.py
│   ├── test_retrieval.py
│   │
│   ├── validate_chunks.py
│   ├── validate_embeddings.py
│   │
│   ├── evaluate_retrieval.py
│   ├── diagnose_retrieval.py
│   │
│   └── retrieval_benchmark.json
│
├── .gitignore
├── requirements.txt
└── README.md


Technology Stack

ComponentTechnology



Language

Python

Document Processing

python-docx / custom loaders

Embeddings

Sentence Transformers

Embedding Model

all-MiniLM-L6-v2

Embedding Dimension

384

Vector Database / Search

FAISS

Index

IndexFlatIP

Metadata

JSON

Evaluation

Custom retrieval benchmark

Environment

Python virtual environment

Pipeline Components

The main modules are:

document_loader.py
document_schema.py
document_builder.py
metadata_loader.py
text_cleaner.py
chunker.py
process_documents.py
chunk_documents.py
embed_chunks.py
build_faiss_index.py
validate_chunks.py
validate_embeddings.py
test_retrieval.py
evaluate_retrieval.py
diagnose_retrieval.py


1. Document Discovery and Metadata

A document manifest is used to associate source files with their metadata.

The manifest allows the pipeline to determine:

Document ID

Document type

Category

Department

Source path

Other metadata fields

The complete dataset was successfully discovered and processed.

Files discovered: 148
Successful: 148
Failed: 0


2. Document Loading

The document_loader.py module provides format-specific loading.

Supported formats include:

JSON
Markdown
DOCX


The purpose of this layer is to isolate source-format differences from the rest of the pipeline.

For example:

JSON ------\
Markdown ----> Document Loader
DOCX -------/
                  |
                  v
          Common representation


This allows downstream stages to work independently of the original file format.

3. Canonical Document Construction

Different document formats naturally represent information differently.

A JSON FAQ, DOCX SOP, and Markdown knowledge-base article should not require completely different retrieval pipelines.

The document_builder.py module converts source documents into a common canonical representation.

Conceptually:

JSON ------\
DOCX -------\
Markdown -----> Canonical Document
Other -------/


The canonical document contains fields such as:

document_id
title
document_type
category
department
customer_scope
version
last_updated
source_authority
related_ids
tags
content
file_path
file_type


The complete dataset was tested:

Files discovered: 148

Successful: 148
Failed: 0


4. Text Cleaning

The text cleaning stage normalizes extracted content while preserving meaningful information.

The cleaning pipeline is intentionally conservative.

The objective is not to aggressively rewrite documents.

Instead, it aims to:

Normalize unnecessary formatting

Preserve meaningful text

Preserve headings

Preserve identifiers

Preserve procedural language

Preserve semantic relationships

This is important because excessive cleaning can damage retrieval quality.

5. Document Processing

The complete document-processing pipeline is executed using:

python -m ingestion.process_documents


Result:

NOVATEL DOCUMENT PROCESSING

Input documents: 148
Output directory: data\processed\documents

PROCESSING RESULT

Successful: 148
Failed:     0


All 148 source documents were successfully processed.

Processed Document Statistics

The processed dataset has:

Documents: 148

Minimum characters: 289
Maximum characters: 1476
Average characters: 643.22

Minimum words: 43
Maximum words: 199
Average words: 91.66


This confirms that the current synthetic documents are relatively short.

The longest document contains:

199 words


6. Chunking

The chunker.py component converts documents into retrieval units.

For larger enterprise documents, chunking is important because embedding an entire long document into one vector can dilute the meaning of individual sections.

The current synthetic dataset contains short documents.

As a result:

Documents: 148
Chunks:    148


The current chunking result is:

Minimum chunks/document: 1
Maximum chunks/document: 1
Average chunks/document: 1.0


Therefore, every current document fits into one chunk.

This does not mean the chunking architecture is unnecessary.

The chunking component is designed so that longer future documents can produce multiple chunks without changing the downstream embedding and retrieval architecture.

Chunk Validation

Chunk validation was performed using:

python -m ingestion.validate_chunks


Result:

NOVATEL CHUNK DATASET VALIDATION

Chunk files discovered: 148

Unique chunk IDs: 148
Unique document IDs: 148

VALIDATION RESULT: PASSED
Errors: 0


This confirms:

All chunks have unique IDs.

All document IDs are unique.

Chunk metadata is structurally valid.

No duplicate chunk IDs were detected.

7. Embedding Generation

The project uses:

sentence-transformers/all-MiniLM-L6-v2


Each chunk is converted into a semantic vector.

The model generates:

384-dimensional embeddings


For the complete dataset:

Chunks discovered: 148

Embeddings shape: (148, 384)
Data type: float32
Metadata records: 148


The embeddings are saved to:

data/vectorstore/embeddings.npy


The corresponding metadata is saved to:

data/vectorstore/chunk_metadata.json


Why all-MiniLM-L6-v2?

The current model was selected because it provides:

Local inference

No paid embedding API

Relatively fast inference

Compact vectors

Easy Sentence Transformers integration

Straightforward FAISS integration

The same model is used for both:

Document embeddings


and:

Query embeddings


This ensures that queries and documents exist in the same semantic vector space.

Embedding Example

A test query:

How do I update the mobile number registered on my account?


produces:

Embedding shape: (384,)
Embedding type: numpy.ndarray


The first values of one generated vector were:

[-0.05707005,
 -0.04221169,
 -0.01931334,
 -0.04009104,
 -0.04571478]


The exact values are not important individually.

The important point is that the entire text is represented as a 384-dimensional semantic vector.

8. Embedding Validation

Embeddings were validated using:

python -m ingestion.validate_embeddings


Result:

NOVATEL EMBEDDING VALIDATION

Embedding shape: (148, 384)
Embedding dtype: float32
Metadata records: 148

NaN values: 0
Infinite values: 0
Unique chunk IDs: 148

Minimum vector norm:
0.9999998807907104

Maximum vector norm:
1.0000001192092896

VALIDATION RESULT: PASSED
Errors: 0


This confirms:

Correct embedding dimension

Correct data type

No NaN values

No infinite values

Unique chunk mappings

Approximately unit-normalized vectors

9. FAISS Vector Index

FAISS is used for vector similarity search.

The current index type is:

IndexFlatIP


Configuration:

Embeddings shape: (148, 384)
Metadata records: 148

Index type: IndexFlatIP
Vector dimension: 384
Vectors stored: 148


The index is saved to:

data/vectorstore/faiss.index


Why IndexFlatIP?

IndexFlatIP performs exact inner-product similarity search.

The generated embeddings are approximately unit normalized.

For normalized vectors:

Inner Product ≈ Cosine Similarity


Therefore:

similarity(query, document)
=
query_vector · document_vector


The current dataset contains only 148 vectors, so exact search is more than sufficient.

A larger production system could later use a more scalable approximate FAISS index.

10. Semantic Retrieval

The retrieval system converts a user query into the same embedding space as the document chunks.

Example:

I no longer have access to my old phone number.
How can I change the number linked to my account?


The query is embedded and searched against the FAISS index.

Example result:

Rank: 1
Score: 0.6496

Chunk ID:
FAQ_C01_001_chunk_000

Document ID:
FAQ_C01_001

Title:
How do I update the mobile number registered on my account?

Type:
FAQ

Category:
C01

Department:
Customer Care


The query and document use different wording, but semantic similarity allows the system to identify the relevant FAQ.

Semantic Retrieval Flow

User Query
    |
    v
Sentence Transformer
    |
    v
384-D Query Embedding
    |
    v
FAISS IndexFlatIP
    |
    v
Similarity Scores
    |
    v
Ranked Results
    |
    v
Top-K Documents


11. Retrieval Evaluation

A dedicated retrieval benchmark was created.

The benchmark contains:

29 questions
29 categories


There is one benchmark question for every category:

C01
C02
C03
...
C29


Each question has expected relevant document IDs.

This allows the retrieval system to be evaluated automatically rather than relying only on manual inspection.

Retrieval Evaluation Methodology

For every benchmark question:

Step 1 — User Query

A natural-language question is provided.

Example:

There is no mobile signal where I am.
How can I find out whether NovaTel is having a network outage?


Step 2 — Query Embedding

The query is converted into a 384-dimensional vector using:

all-MiniLM-L6-v2


Step 3 — Vector Search

FAISS searches the 148 document vectors.

Step 4 — Ranking

Results are sorted according to similarity score.

Step 5 — Relevance Matching

The retrieved document IDs are compared with the expected relevant document IDs defined in the benchmark.

Step 6 — Top-K Metrics

The evaluation calculates:

Top-1

Top-3

Top-5

12. Retrieval Diagnostics

The diagnose_retrieval.py script investigates cases where the expected document does not appear at rank 1.

This is important because a Top-1 miss does not necessarily mean retrieval completely failed.

For example:

Query
 |
 v
Rank 1: Similar but not expected document
 |
 v
Rank 2: Expected document


This is primarily a ranking issue.

The diagnostic tool therefore displays:

Query

Expected category

Expected documents

Top 10 retrieved documents

Similarity scores

Document categories

Whether expected documents were retrieved

Retrieval Results

The current baseline is:

MetricResult



Documents

148

Chunks

148

Embeddings

148

Embedding Dimension

384

FAISS Vectors

148

Benchmark Questions

29

Top-1

26/29 — 89.66%

Top-3

29/29 — 100.00%

Top-5

29/29 — 100.00%

Understanding the Evaluation

Top-1

Top-1 asks:

Is an expected relevant document the first result?

For example:

1. Relevant Document     PASS
2. Irrelevant Document
3. Irrelevant Document


This is the strictest ranking metric.

Current result:

26/29 = 89.66%


Top-3

Top-3 asks:

Is an expected relevant document present anywhere in the first three results?

Example:

1. Similar Document
2. Relevant Document     PASS
3. Another Document


Current result:

29/29 = 100%


This means every benchmark question had an expected relevant document within its first three retrieved results.

Top-5

Top-5 asks:

Is an expected relevant document present anywhere in the first five results?

Current result:

29/29 = 100%


This means every benchmark query successfully surfaced relevant knowledge within the first five retrieved results.

Why Top-3 and Top-5 Matter for RAG

In a RAG system, the retrieval layer usually does not need to identify exactly one document.

Instead, it typically retrieves multiple relevant pieces of context and passes them to a downstream generation model.

Therefore:

Query
 |
 v
Top-K Retrieval
 |
 +--> Relevant Document
 +--> Supporting Document
 +--> Related Document
 |
 v
Context Assembly
 |
 v
LLM


Because the current system achieves:

Top-3 = 100%
Top-5 = 100%


the retrieval layer is currently very effective at surfacing relevant information, even when the exact expected document is not always ranked first.

Top-1 Miss Analysis

There are three Top-1 misses:

Q08 — C08
Q16 — C16
Q17 — C17


These were investigated using the retrieval diagnostic tool.

Q08 — Network Outage

Query

There is no mobile signal where I am.
How can I find out whether NovaTel is having a network outage?


Expected Documents

KB_C08_outage_status_check
FAQ_C08_015


Top Results

1. KB_C29_network_reset_guide
   Score: 0.6180
   Category: C29

2. FAQ_C08_015
   Score: 0.5641
   Category: C08

3. FAQ_C11_022
   Score: 0.5609
   Category: C11

4. FAQ_C13_025
   Score: 0.5590
   Category: C13

5. FAQ_C12_023
   Score: 0.5533
   Category: C12

...

8. KB_C08_outage_status_check
   Score: 0.5154
   Category: C08


The first result is about network/device troubleshooting.

That topic is semantically close to the user's query.

However, the expected C08 documents are also retrieved.

Therefore, Q08 is primarily a ranking ambiguity between network troubleshooting and network outage information.

Q16 — Complaint Escalation

Query

I've already complained about this issue but nobody has resolved it.
How can I escalate my complaint?


Expected Documents

TRX_003
FAQ_C16_031
KB_C16_complaint_escalation


Top Results

1. EML_010
   Score: 0.6167
   Category: C16

2. FAQ_C16_031
   Score: 0.5915
   Category: C16

3. SOP_C16_COMPLAINT_ESCALATION
   Score: 0.4890
   Category: C16

4. TRX_003
   Score: 0.4880
   Category: C16

5. KB_C16_complaint_escalation
   Score: 0.4867
   Category: C16


The Top-1 result is still from the correct category:

C16


The expected documents are also present in the retrieved results.

This indicates that the retrieval system understands the query topic, but the embedding similarity ranking prefers an email document over the benchmark's expected documents.

This is a ranking issue, not a complete retrieval failure.

Q17 — KYC Re-verification

Query

What documents do I need to provide if NovaTel asks me
to complete KYC verification again?


Expected Documents

FAQ_C17_033
KB_C17_kyc_reverification
FAQ_C17_034


Top Results

1. EML_008
   Score: 0.7378
   Category: C17

2. FAQ_C17_034
   Score: 0.7301
   Category: C17

3. SOP_C17_KYC_VERIFICATION
   Score: 0.6829
   Category: C17

4. FAQ_C17_033
   Score: 0.6710
   Category: C17

5. TRX_007
   Score: 0.6707
   Category: C17

6. Policy_C17_kyc_policy
   Score: 0.6448
   Category: C17

7. KB_C17_kyc_reverification
   Score: 0.6427
   Category: C17


The Top-1 document belongs to the correct category:

C17


Multiple expected documents are also retrieved immediately after it.

Therefore, the system understands the query but the ranking can be improved.

What the Misses Mean

The three Top-1 misses do not indicate that the relevant knowledge is absent.

Instead, the results show:

Query
 |
 v
Semantic Search
 |
 +---- Relevant information found
 |
 +---- Similar document ranked higher
 |
 v
Expected information still appears in Top-K


This means the current optimization target should be ranking quality, not immediate modification of the 148-document dataset.

Potential improvements include:

Metadata-aware ranking

Metadata filtering

Cross-encoder reranking

Hybrid keyword + semantic retrieval

Query expansion

Query rewriting

Better benchmark coverage

Validation Results

The project includes validation at multiple stages.

Raw Documents
      |
      v
Document Validation
      |
      v
Canonical Documents
      |
      v
Processed Documents
      |
      v
Chunk Validation
      |
      v
Embedding Validation
      |
      v
FAISS Index
      |
      v
Retrieval Evaluation


Document Validation

Result:

Files discovered: 148

Successful: 148
Failed: 0


All source documents were successfully loaded.

Canonical Document Validation

Result:

Files discovered: 148

Successful: 148
Failed: 0


All 148 documents were successfully converted into canonical representations.

Processing Validation

Result:

Input documents: 148

Successful: 148
Failed: 0


Chunk Validation

Result:

Chunk files discovered: 148

Unique chunk IDs: 148
Unique document IDs: 148

VALIDATION RESULT: PASSED
Errors: 0


Embedding Validation

Result:

Embedding shape: (148, 384)
Embedding dtype: float32
Metadata records: 148

NaN values: 0
Infinite values: 0
Unique chunk IDs: 148

Minimum vector norm:
0.9999998807907104

Maximum vector norm:
1.0000001192092896

VALIDATION RESULT: PASSED
Errors: 0


Design Decisions

1. Canonicalization before retrieval

The source dataset contains multiple formats.

Instead of building separate retrieval pipelines, all documents are normalized into a common schema.

Multiple Formats
      |
      v
Canonical Document
      |
      v
Common Retrieval Pipeline


This improves maintainability and extensibility.

2. Conservative text cleaning

The cleaning stage avoids unnecessarily changing document semantics.

This is important for enterprise documents where:

Policy language matters

Procedure ordering matters

Identifiers matter

Technical terms matter

Section headings matter

3. Metadata preservation

Metadata such as:

Category
Department
Document Type
Customer Scope
Version
Source Authority
Related Documents


is preserved.

This enables future metadata-aware retrieval and filtering.

4. Local embeddings

The project uses a local Sentence Transformer rather than a paid external embedding API.

This provides:

Reproducibility

Low cost

No API dependency

Local inference

5. FAISS IndexFlatIP

The current dataset is small.

Therefore an exact similarity index is appropriate.

There is no need to introduce approximate indexing complexity for only 148 vectors.

Current Limitations

1. All documents currently produce one chunk

Because the documents are short:

148 documents
=
148 chunks


Longer real-world enterprise documents will require multiple chunks.

2. Dense retrieval only

The current system uses semantic vector retrieval.

It does not currently combine semantic retrieval with traditional keyword retrieval.

This may matter for:

Document IDs

Product codes

Policy names

Technical identifiers

Exact terminology

3. No reranking

FAISS directly determines the initial ranking.

A cross-encoder reranker could improve ranking quality among the top retrieved candidates.

4. Benchmark size

The benchmark currently contains:

29 questions


with one question per category.

This provides a useful baseline but should eventually be expanded.

5. No LLM generation yet

The current pipeline ends at:

Query
 |
 v
Retrieved Documents


The final:

Retrieved Documents
 |
 v
LLM
 |
 v
Grounded Answer


layer is not yet implemented in this repository.

6. Structured retrieval is separate

The structured/CSV data component is maintained by the project partner and is not part of the current unstructured retrieval implementation.

Future Improvements

Retrieval Improvements

Potential next steps include:

Hybrid Retrieval

Combine:

Dense Retrieval
+
BM25 / Keyword Retrieval


This can improve retrieval for exact technical terms and identifiers.

Cross-Encoder Reranking

Current:

Query
 |
 v
FAISS
 |
 v
Top-K


Potential future architecture:

Query
 |
 v
FAISS
 |
 v
Top-10 / Top-20 Candidates
 |
 v
Cross-Encoder Reranker
 |
 v
Final Top-K


The reranker would examine the query and candidate document together and produce a more precise relevance score.

Metadata-Aware Ranking

The preserved metadata can be used to boost relevant categories.

For example:

Query
 |
 v
Semantic Retrieval
 |
 v
Metadata-Aware Scoring
 |
 v
Reranked Results


This may help cases such as Q08, where C29 network troubleshooting is semantically close to C08 network outage information.

Query Expansion

A query can potentially be rewritten into multiple semantic representations before retrieval.

Example:

"There is no mobile signal"

could expand to:

"network outage"
"network coverage"
"service outage"
"mobile network unavailable"


This may improve recall.

Evaluation Improvements

The current benchmark can be expanded with:

Multiple questions per category

Paraphrased questions

Ambiguous questions

Short queries

Long queries

Misspelled queries

Technical queries

Multi-document questions

Hard negative examples

Future metrics may include:

Recall@K
Precision@K
MRR
nDCG


alongside the existing:

Top-1
Top-3
Top-5


Planned End-to-End RAG Architecture

The eventual system is intended to combine both unstructured and structured information.

                           User Query
                               |
                               v
                    +----------------------+
                    | Query Understanding  |
                    +----------+-----------+
                               |
                               v
                    +----------------------+
                    |   Retrieval Router   |
                    +----------+-----------+
                               |
                 +-------------+-------------+
                 |                           |
                 v                           v
        Unstructured Retrieval       Structured Retrieval
                 |                           |
                 v                           v
             FAISS                    Structured Data
                 |                           |
                 +-------------+-------------+
                               |
                               v
                       Retrieved Context
                               |
                               v
                         Reranker
                               |
                               v
                      Context Assembly
                               |
                               v
                              LLM
                               |
                               v
                     Grounded Response
                               |
                               v
                       Source Citations


Future RAG Query Flow

For example, a future customer query could be:

Why was my recharge amount debited
but my plan was not credited?


The system could perform:

User Query
    |
    v
Query Understanding
    |
    +----------------------------+
    |                            |
    v                            v
Unstructured Retrieval     Structured Retrieval
    |                            |
    v                            v
FAQ / KB / SOP             Customer / Transaction
    |                            |
    +-------------+--------------+
                  |
                  v
              Reranking
                  |
                  v
          Context Assembly
                  |
                  v
                 LLM
                  |
                  v
         Grounded Response


This is the intended direction for the larger NovaTel RAG architecture.

Installation

Requirements

The project uses Python and the dependencies listed in:

requirements.txt


Major dependencies include:

sentence-transformers

faiss

python-docx

pandas

NumPy

Environment Setup

Create a virtual environment:

python -m venv .venv


Activate it:

.venv\Scripts\Activate.ps1


Install dependencies:

python -m pip install -r requirements.txt


Running the Pipeline

1. Process Documents

python -m ingestion.process_documents


Expected result:

Input documents: 148
Successful: 148
Failed: 0


2. Chunk Documents

python -m ingestion.chunk_documents


Expected result:

Input documents: 148
Documents processed: 148
Total chunks: 148
Failed documents: 0


3. Validate Chunks

python -m ingestion.validate_chunks


Expected:

Unique chunk IDs: 148
Unique document IDs: 148

VALIDATION RESULT: PASSED


4. Generate Embeddings

python -m ingestion.embed_chunks


Expected:

Chunks discovered: 148

Embeddings shape: (148, 384)
Data type: float32
Metadata records: 148


5. Validate Embeddings

python -m ingestion.validate_embeddings


Expected:

Embedding shape: (148, 384)
NaN values: 0
Infinite values: 0

VALIDATION RESULT: PASSED


6. Build FAISS Index

python -m ingestion.build_faiss_index


Expected:

Index type: IndexFlatIP
Vector dimension: 384
Vectors stored: 148


7. Test Semantic Retrieval

python -m ingestion.test_retrieval


This loads the embedding model, embeds a test query, searches the FAISS index, and displays ranked results.

8. Evaluate Retrieval

python -m ingestion.evaluate_retrieval


Expected baseline:

Top-1: 26/29 (89.66%)
Top-3: 29/29 (100.00%)
Top-5: 29/29 (100.00%)


9. Diagnose Retrieval Misses

python -m ingestion.diagnose_retrieval


This provides detailed information for Top-1 misses.

Testing and Validation Commands

Analyze Documents

python -m ingestion.analyze_documents


Provides:

Document count

Word statistics

Character statistics

Document type statistics

Longest documents

Analyze Categories

python -m ingestion.analyze_categories


Groups documents by category.

Test All Documents

python -m ingestion.test_all_documents


Validates loading across the dataset.

Test Document Builder

python -m ingestion.test_document_builder


Validates canonical document construction.

Expected:

Files discovered: 148

Successful: 148
Failed: 0


Test Cleaning

python -m ingestion.test_cleaning


Tests text-cleaning behavior.

Inspect DOCX Extraction

python -m ingestion.inspect_docx


Useful for debugging paragraph and run-level extraction issues.

Find Spacing Issues

python -m ingestion.find_spacing_issues


The current diagnostic scan reported:

Documents scanned: 148
Documents with suspicious patterns: 0


Generated Artifacts

The primary generated artifacts are:

data/
├── processed/
│   └── documents/
│
└── vectorstore/
    ├── embeddings.npy
    ├── faiss.index
    ├── chunk_metadata.json
    └── retrieval_evaluation.json


embeddings.npy

Contains the generated document/chunk embeddings.

Current shape:

(148, 384)


Meaning:

148 vectors
384 dimensions per vector


faiss.index

Contains the FAISS similarity-search index.

Current configuration:

Index type: IndexFlatIP
Dimension: 384
Vectors: 148


chunk_metadata.json

Stores the metadata associated with each chunk.

This allows the vector position returned by FAISS to be mapped back to the original document information.

retrieval_evaluation.json

Contains detailed results from the retrieval benchmark.

It allows evaluation results to be stored as an artifact rather than only printed to the terminal.

Reproducibility

The unstructured retrieval pipeline can be rebuilt using:

python -m ingestion.process_documents

python -m ingestion.chunk_documents

python -m ingestion.validate_chunks

python -m ingestion.embed_chunks

python -m ingestion.validate_embeddings

python -m ingestion.build_faiss_index

python -m ingestion.test_retrieval

python -m ingestion.evaluate_retrieval


The resulting artifacts include:

Processed Documents
       |
       v
Chunks
       |
       v
Embeddings
       |
       v
FAISS Index
       |
       v
Retrieval Evaluation


Project Milestones

Phase 1 — Dataset Understanding

Document manifest validation

Dataset inventory

Document type analysis

Category analysis

Document length analysis

Phase 2 — Document Ingestion

JSON loader

Markdown loader

DOCX loader

Metadata loader

Full dataset loading test

Phase 3 — Canonicalization

Canonical document schema

Document builder

JSON semantic conversion

Full dataset canonicalization test

Phase 4 — Text Processing

Text cleaning

Cleaning validation

Processed document generation

Document statistics

Phase 5 — Retrieval Representation

Chunking

Chunk validation

Sentence Transformer integration

Embedding generation

Embedding validation

Phase 6 — Vector Search

FAISS integration

Index construction

Semantic retrieval test

Metadata mapping

Phase 7 — Retrieval Evaluation

Retrieval benchmark

29 benchmark questions

29 category coverage

Top-1 evaluation

Top-3 evaluation

Top-5 evaluation

Retrieval miss diagnostics

Phase 8 — Future RAG Integration

Retrieval reranking

Hybrid retrieval

Structured retrieval integration

Query routing

Context assembly

LLM integration

Grounded response generation

Source citations

End-to-end evaluation

API layer

Deployment

Current Status

Completed

The following components are complete:

148-document unstructured knowledge base

JSON ingestion

Markdown ingestion

DOCX ingestion

Manifest-based discovery

Metadata extraction

Canonical document schema

Canonical document builder

JSON semantic conversion

Text cleaning

Document processing

Document analysis

Chunking

Chunk validation

Sentence-Transformer embeddings

Embedding validation

FAISS IndexFlatIP

Semantic retrieval

Retrieval benchmark

Top-K evaluation

Retrieval diagnostics

Current Baseline

                    NOVATEL RETRIEVAL BASELINE

Documents                  148
Chunks                     148
Embeddings                 148
Embedding Dimension        384
FAISS Vectors              148
FAISS Index                IndexFlatIP

Benchmark Questions         29
Benchmark Categories        29

Top-1                       89.66%
Top-3                      100.00%
Top-5                      100.00%


Results at a Glance

                         148 Documents
                               |
                               v
                          148 Chunks
                               |
                               v
                     148 x 384 Embeddings
                               |
                               v
                         FAISS Index
                               |
                               v
                       Semantic Retrieval
                               |
                               v
                       29 Benchmark Queries
                               |
                +--------------+--------------+
                |              |              |
                v              v              v
              Top-1          Top-3          Top-5
             89.66%         100.00%         100.00%


Key Findings

The current retrieval baseline demonstrates that the unstructured knowledge layer is functioning end-to-end.

The most important findings are:

1. All 148 documents process successfully

148/148 successful


2. All documents successfully produce retrieval chunks

148 documents
148 chunks


3. All embeddings are valid

Shape: (148, 384)
NaN: 0
Infinite: 0


4. FAISS successfully indexes all vectors

148 vectors
384 dimensions


5. Semantic retrieval is strong

Top-1: 89.66%
Top-3: 100%
Top-5: 100%


6. The three Top-1 misses are ranking issues

The diagnostic analysis shows that the expected information is still retrieved for Q08, Q16, and Q17.

Therefore, the next retrieval optimization should focus on improving ranking rather than immediately changing the source dataset.

Next Development Stage

The natural next stage is:

Current
  |
  v
Dense Retrieval
  |
  v
Top-K Candidates
  |
  v
Metadata-Aware Ranking
  +
Cross-Encoder Reranking
  +
Hybrid Retrieval
  |
  v
Improved Retrieval
  |
  v
Structured Retrieval Integration
  |
  v
Context Assembly
  |
  v
LLM
  |
  v
Grounded Answer


The unstructured retrieval layer therefore serves as the foundation for the larger hybrid RAG system.

Conclusion

This repository implements the complete unstructured semantic retrieval foundation for the NovaTel Telecom RAG system.

The pipeline transforms heterogeneous enterprise documents into validated semantic search artifacts:

Heterogeneous Documents
          |
          v
      Ingestion
          |
          v
    Canonicalization
          |
          v
      Text Cleaning
          |
          v
       Chunking
          |
          v
      Embeddings
          |
          v
      FAISS Index
          |
          v
   Semantic Retrieval
          |
          v
   Retrieval Evaluation


The current system successfully processes:

148 Documents
148 Chunks
148 Embeddings
384 Dimensions


and achieves:

Top-1: 89.66%
Top-3: 100.00%
Top-5: 100.00%


The three Top-1 misses have been explicitly diagnosed and show that the expected information is still present within the retrieved results.

This establishes a strong baseline for the next stage of development:

Improved ranking

Hybrid retrieval

Metadata-aware retrieval

Cross-encoder reranking

Structured-data integration

Context assembly

LLM-based grounded generation

End-to-end RAG evaluation

Project Status

Unstructured ingestion + semantic retrieval baseline: COMPLETE

Next milestone: Hybrid retrieval + structured-data integration + end-to-end RAG
