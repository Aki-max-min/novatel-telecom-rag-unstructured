# E13 extraction validation (gap 7) - AI-labelled, human review pending

> **Status: AI-labelled, human review pending. This is NOT validation by a human.** The 20 documents' labels (`correct_concepts` and the notes) were drafted and re-checked by an AI
> assistant (two passes) and have not been reviewed by a human. Five borderline rows are waiting for a human decision: EML_008, INC_C25_INC_2026_0179, SOP_C25_FTTH_FAULT_HANDLING, TRN_004, INC_C08_INC_2026_0211.
> 20 documents and 52 five-label predictions are a small sample; nothing here is generalisation evidence. Nothing in this document is marked "validated".

## Method

- **Sample:** the 20 documents of `docs/extraction_gold_sheet.csv` (it stays the blank template), drawn by the rule and seed in `docs/E13_kg_fixes2.md` (Step 1 rule: seed 20260611; one document each from C11, C12, C24;
  the rest stratified FAQ 4, KB 3, SOP 3, INC 3, MAN 3, EML 2, TRN 2). The labelled copy is `docs/extraction_gold_sheet_reviewed.csv` (labels untouched by this branch).
- **Definition of "correct":** a concept is correct when it is part of the document's **specific content**. Sentences copied into every document of a type (the KB symptoms and precondition sentences, the SOP
  "Required Information" and preconditions, the training-module template) do not count; a passing mention in a detection sentence does not count; a phrase used in another sense does not count; a match that exists only because of the
  metadata header (which repeats the category name) does not count.
- **Predictions:** the sheet's own `predicted_concepts` (they were produced before the vocabulary overlay), and the CURRENT extractor's predictions for the same documents (`knowledge_graph.gold_sheet.build_rows`).
- **Views:** *stale-strict* (the sheet's predictions), *current-strict* (current extractor), *current-lenient* (current extractor, but the 22 predictions in `docs/extraction_template_only.json` - template sentences or a weak passing mention - count as correct;
  they are added to the correct set, so the recall denominator grows with them).
- **Pooling:** the five content labels Service, Channel, VerificationMethod, Requirement, Location. The **Concept label is reported separately and is not comparable**: the gold lists each document's main-topic concept, while the extractor
  only emits the concepts of the vocabulary overlay and of the two name families.
- **Code:** `python scripts/score_extraction_gold.py docs/extraction_gold_sheet_reviewed.csv` (stale view) and `python scripts/score_extraction_current.py` (the three views and `docs/extraction_validation_disagreements.csv`);
  `knowledge_graph/gold_scoring.py`, tests `knowledge_graph/tests/test_gold_scoring.py`.

## Results

Five content labels pooled (52 predictions; 27 correct, 25 not):

| view | precision | recall | tp | fp | fn |
|---|---|---|---|---|---|
| stale-strict | 0.519 | 0.931 | 27 | 25 | 2 |
| current-strict | 0.519 | 0.931 | 27 | 25 | 2 |
| current-lenient | 0.942 | 0.961 | 49 | 3 | 2 |

Per label, current-strict (stale-strict is identical for these five labels: the overlay adds only Concept predictions):

| label | precision | recall | tp | fp | fn |
|---|---|---|---|---|---|
| Service | 0.593 | 1.000 | 16 | 11 | 0 |
| Channel | 0.222 | 0.500 | 2 | 7 | 2 |
| VerificationMethod | 0.462 | 1.000 | 6 | 7 | 0 |
| Requirement | 1.000 | 1.000 | 2 | 0 | 0 |
| Location | 1.000 | 1.000 | 1 | 0 | 0 |

Per label, current-lenient: Service 0.963 / 1.000 (26/1/0), Channel 0.778 / 0.778 (7/2/2), VerificationMethod 1.000 / 1.000 (13/0/0), Requirement 1.000 / 1.000 (2/0/0), Location 1.000 / 1.000 (1/0/0).

Concept label (separate, not comparable): stale 0 tp / 1 fp / 16 fn (the one false positive is `Concept:Network Coverage` on FAQ_C11_022, since removed by the documented exclusion); current 2 tp / 0 fp / 14 fn
(the overlay now finds `Device Compatibility` on FAQ_C12_024 and `IoT & M2M Services` on MAN_IOT_PORTAL_001). Only three documents' predictions differ between the sheet and the current extractor, all Concept predictions.

Counts: the sheet lists 53 predictions (52 five-label + 1 Concept), the current extractor 54 (52 + 2 Concept).

### Main finding: template text produces much of the noise

25 of the 52 five-label predictions (48%) are not part of the document's specific content; 22 of those 25 are on the template-only list (template sentences or a weak passing mention), and 19 of the 52 (37%) are plain template sentences.
Strict precision is therefore 0.52 and lenient 0.94: nearly all of the difference is template text. The four hub concepts of the graph are the clearest case, in this sample:

| concept | documents where predicted | of which correct | listed as template-only |
|---|---|---|---|
| VerificationMethod:OTP | 7 | 1 (MAN_APP_001) | 6 |
| Channel:My NovaTel App | 5 | 2 (EML_008, MAN_APP_001) | 3 (two template sentences and one weak mention) |
| Channel:Self-Care Portal | 4 | 0 | 2 (plus one header echo and one substring match) |
| Service:Mobile Number Update | 4 | 0 | 4 |

This is the mechanism behind the hub concepts OTP, My NovaTel App, Self-Care Portal and Mobile Number Update: the phrase sits in a sentence that every document of a type repeats, so the concept fans out to the whole type. The sample is 20 documents.

## Disagreements by cause (current extractor, strict; `docs/extraction_validation_disagreements.csv`)

Causes are read from the reviewer's notes in the sheet and from the template-only list. Counts: template sentence 19, weak passing mention 2, metadata-header echo 1, wrong sense 3, vocabulary gap 2 (27 in all: 25 false positives, 2 false negatives).

**template sentence** (19)

| document | concept | kind | phrase that fired |
|---|---|---|---|
| KB_C04_bill_disputes | Channel:My NovaTel App | false positive | `self-care app` |
| KB_C04_bill_disputes | Channel:Self-Care Portal | false positive | `self-care` |
| KB_C04_bill_disputes | Service:KYC Verification | false positive | `KYC` |
| KB_C04_bill_disputes | Service:Plan Change | false positive | `plan change` |
| KB_C04_bill_disputes | Service:SIM Swap | false positive | `SIM swap` |
| KB_C04_bill_disputes | VerificationMethod:OTP | false positive | `OTP` |
| KB_C20_refund_processing | Channel:My NovaTel App | false positive | `self-care app` |
| KB_C20_refund_processing | Channel:Self-Care Portal | false positive | `self-care` |
| KB_C20_refund_processing | VerificationMethod:OTP | false positive | `OTP` |
| KB_C28_qos_disclosures | VerificationMethod:OTP | false positive | `OTP` |
| SOP_C10_VAS_DISPUTE | Service:Mobile Number Update | false positive | `Registered mobile number` |
| SOP_C10_VAS_DISPUTE | VerificationMethod:OTP | false positive | `OTP` |
| SOP_C16_COMPLAINT_ESCALATION | Service:Mobile Number Update | false positive | `Registered mobile number` |
| SOP_C16_COMPLAINT_ESCALATION | VerificationMethod:OTP | false positive | `OTP` |
| SOP_C25_FTTH_FAULT_HANDLING | Service:Complaint Registration | false positive | `Escalation` |
| SOP_C25_FTTH_FAULT_HANDLING | Service:Mobile Number Update | false positive | `Registered mobile number` |
| SOP_C25_FTTH_FAULT_HANDLING | VerificationMethod:OTP | false positive | `OTP` |
| TRN_002 | VerificationMethod:Photo ID | false positive | `identity verification` |
| TRN_004 | Service:Complaint Registration | false positive | `Escalation` |

**weak passing mention** (2)

| document | concept | kind | phrase that fired |
|---|---|---|---|
| INC_C08_INC_2026_0211 | Channel:My NovaTel App | false positive | `self-care app` |
| INC_C08_INC_2026_0211 | Channel:Self-Care Portal | false positive | `self-care` |

**metadata-header echo** (1)

| document | concept | kind | phrase that fired |
|---|---|---|---|
| MAN_APP_001 | Channel:Self-Care Portal | false positive | `Self-Care Portal` |

**wrong sense** (3)

| document | concept | kind | phrase that fired |
|---|---|---|---|
| INC_C05_INC_2026_0171 | Service:Complaint Registration | false positive | `complaint` |
| MAN_APP_001 | Service:Mobile Number Update | false positive | `registered mobile number` |
| TRN_002 | Service:Complaint Registration | false positive | `Escalation` |

**vocabulary gap** (2)

| document | concept | kind | phrase that fired |
|---|---|---|---|
| FAQ_C07_013 | Channel:My NovaTel App | false negative | (none: not extracted) |
| MAN_ESIM_001 | Channel:My NovaTel App | false negative | (none: not extracted) |

**Concept label, shown separately** (14 main-topic concepts the extractor does not emit; not comparable)

| document | main-topic concept in the gold |
|---|---|
| FAQ_C14_028 | Concept:Offers & Promotions |
| INC_C05_INC_2026_0171 | Concept:SIM Card Services |
| INC_C08_INC_2026_0211 | Concept:Network Outages |
| INC_C25_INC_2026_0179 | Concept:Broadband & FTTH Services |
| INC_C25_INC_2026_0179 | Concept:Network Outages |
| KB_C04_bill_disputes | Concept:Billing & Invoices |
| KB_C20_refund_processing | Concept:Billing & Invoices |
| MAN_ESIM_001 | Concept:SIM Card Services |
| MAN_IOT_PORTAL_001 | Concept:Enterprise & Business Services |
| SOP_C10_VAS_DISPUTE | Concept:Value Added Services |
| SOP_C16_COMPLAINT_ESCALATION | Concept:Complaints & Grievances |
| SOP_C25_FTTH_FAULT_HANDLING | Concept:Broadband & FTTH Services |
| TRN_002 | Concept:Network Outages |
| TRN_004 | Concept:KYC & Identity Verification |

Notes on the causes: the false negatives are the Channel `My NovaTel App` expressed as a bare "the app" ("activate ... from the app", "SIM Services > eSIM in the app"), which the extractor's phrases (`my novatel app`, `novatel app`, ...) do not contain: a vocabulary gap.
The Concept rows are the documents' main-topic concepts (for example Billing & Invoices on a billing KB, Value Added Services on the VAS SOP); most of them are concepts that the extractor emits only for the two name families and the overlay, so a Concept recall of 2 of 16 says nothing about the quality of the
concepts it does emit.

## Where I would label differently (reported, not changed)

The brief is to leave the labels untouched. Three places where I would have judged differently, so a human can look at them first:
1. **FTTH on INC_C25_INC_2026_0179 and SOP_C25_FTTH_FAULT_HANDLING** is counted correct as `Service:Broadband/FTTH Installation`, although the notes themselves say these documents are about an outage / a fault, not an installation. The same standard marked `Complaint Registration` on INC_C05 as a wrong sense.
2. **The template-only list contains two predictions that the notes call a wrong sense** (`Service:Complaint Registration` on TRN_002, the escalation to the NOC; `Service:Mobile Number Update` on MAN_APP_001, used for login). The lenient view therefore counts two wrong-sense predictions as correct. Without them the lenient precision would be 0.904 (47 of 52) instead of 0.942.
3. **`VerificationMethod:Photo ID` on EML_008 and TRN_004** is counted correct because the concept fits, although the phrase that fired came from the header (EML_008) or from template text (TRN_004): right concept, wrong evidence. Elsewhere template-only evidence counts against the prediction.

Sensitivity of the strict five-label precision to the five borderline rows (arithmetic on flips, not new judgements): if the four counted-correct borderline predictions (FTTH twice, Photo ID twice) were wrong, precision would be 0.442 (23 of 52) with recall 0.920; if `Channel:My NovaTel App` on INC_C08_INC_2026_0211
(a weak passing mention, currently not counted) were correct, precision would be 0.538 (28 of 52) with recall 0.933. The strict figure of 0.519 therefore sits in a range of roughly 0.44 to 0.54 until a human decides these rows.

## What is NOT shown

- The labels are an AI assistant's (two passes), **not a human's**; the five borderline rows above are pending human review. Until then the figures are an AI-assisted estimate, not a validation, and nothing here is marked "validated".
- 20 documents, 52 five-label predictions: a small sample, stratified by document type but not drawn to represent the corpus. No confidence interval is given because the sample is too small for one to mean much. Not generalisation evidence.
- The Concept label is not comparable and is not part of the pooled figures.
- Person A's 42 questions are not involved (this is an extraction check, not a retrieval run); no extractor rule, overlay phrase, graph or retrieval setting was changed on this branch.
