# NovaTel Telecom RAG — Unstructured Knowledge Pipeline

A retrieval-focused RAG knowledge pipeline for a hypothetical telecom operator, NovaTel.

This repository implements the **unstructured-data ingestion and retrieval layer** of the larger telecom RAG system. The structured/CSV data layer is maintained separately by the project partner.

## 1. Project Scope

The pipeline processes a synthetic enterprise telecom knowledge base containing:

- FAQs
- Knowledge Base articles
- Standard Operating Procedures
- Policies
- Incident Reports
- Root Cause Analyses
- Training Manuals
- Release Notes
- Tariff Catalogues
- Coverage Map descriptions
- User Manuals
- Support Transcripts
- Customer Service Emails

Total source documents: **148**

All data is synthetic and intended for RAG development and evaluation.

---

## 2. Architecture

`	ext
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
                    | Schema / Builder     |
                    +----------+-----------+
                               |
                               v
                    +----------------------+
                    |    Text Cleaning     |
                    +----------+-----------+
                               |
                               v
                    +----------------------+
                    |       Chunking       |
                    +----------+-----------+
                               |
                               v
                    +----------------------+
                    | Sentence Transformer |
                    | all-MiniLM-L6-v2     |
                    +----------+-----------+
                               |
                               v
                    +----------------------+
                    | 384-D Embeddings     |
                    +----------+-----------+
                               |
                               v
                    +----------------------+
                    | FAISS IndexFlatIP    |
                    +----------+-----------+
                               |
                               v
                         Semantic Search
                               |
                               v
                         Top-K Results
