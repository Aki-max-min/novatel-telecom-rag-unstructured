import json
from pathlib import Path


# ============================================================
# PATHS
# ============================================================

VECTORSTORE_DIR = Path(
    "data/experiments/public_pdfs/vectorstore"
)

INPUT_METADATA_PATH = (
    VECTORSTORE_DIR /
    "chunk_metadata.json"
)

OUTPUT_METADATA_PATH = (
    VECTORSTORE_DIR /
    "chunk_metadata_enriched.json"
)


# ============================================================
# DOCUMENT-SPECIFIC DOMAIN TAGS
# ============================================================

DOCUMENT_TAGS = {

    "PUBLIC_PDF_01_TELECOM_CONSUMERS_PROTECTION": [
        "consumer_rights",
        "customer_protection",
        "telecom_services",
        "consumer_welfare"
    ],

    "PUBLIC_PDF_02_CONSUMER_COMPLAINT_REDRESSAL": [
        "customer_complaints",
        "complaint_resolution",
        "grievance",
        "dispute_resolution"
    ],

    "PUBLIC_PDF_03_COMMERCIAL_COMMUNICATIONS_CUSTOMER_PREFERENCE": [
        "spam",
        "unsolicited_calls",
        "promotional_messages",
        "customer_preferences",
        "commercial_communication"
    ],

    "PUBLIC_PDF_04_QUALITY_OF_SERVICE_REGULATIONS": [
        "service_quality",
        "network_quality",
        "call_quality",
        "telecom_performance"
    ],

    "PUBLIC_PDF_05_COMMERCIAL_COMMUNICATIONS_CONSOLIDATED": [
        "commercial_communication",
        "spam",
        "telemarketing",
        "promotional_communication",
        "telecom_regulation"
    ],

    "PUBLIC_PDF_06_MOBILE_NUMBER_PORTABILITY": [
        "mobile_number_portability",
        "number_portability",
        "switching_operator",
        "mobile_number"
    ],

    "PUBLIC_PDF_07_TELECOM_YEARLY_PERFORMANCE_2024_2025": [
        "telecom_statistics",
        "annual_performance",
        "industry_performance",
        "telecom_trends"
    ],

    "PUBLIC_PDF_08_TELECOM_PERFORMANCE_APR_JUN_2025": [
        "telecom_statistics",
        "quarterly_performance",
        "subscriber_statistics",
        "telecom_performance"
    ],

    "PUBLIC_PDF_09_DRAFT_COMMERCIAL_COMMUNICATIONS": [
        "proposed_regulations",
        "commercial_communication",
        "spam_control",
        "telecom_policy"
    ],

    "PUBLIC_PDF_10_QOS_SUBMISSION_REPORTS_DIRECTION": [
        "qos_reporting",
        "service_quality",
        "compliance_reporting",
        "telecom_reporting"
    ]

}


# ============================================================
# ENRICHMENT FUNCTION
# ============================================================

def enrich_metadata():

    print("=" * 70)
    print("NOVATEL PUBLIC PDF METADATA ENRICHMENT")
    print("=" * 70)


    # --------------------------------------------------------
    # CHECK INPUT
    # --------------------------------------------------------

    if not INPUT_METADATA_PATH.exists():

        print(
            f"\nERROR: Metadata file not found:"
        )

        print(
            INPUT_METADATA_PATH
        )

        return


    # --------------------------------------------------------
    # LOAD ORIGINAL METADATA
    # --------------------------------------------------------

    print(
        "\nLoading original metadata..."
    )

    with open(
        INPUT_METADATA_PATH,
        "r",
        encoding="utf-8"
    ) as f:

        metadata = json.load(f)


    print(
        f"Metadata records loaded: "
        f"{len(metadata)}"
    )


    # --------------------------------------------------------
    # ENRICH METADATA
    # --------------------------------------------------------

    enriched_count = 0

    missing_documents = set()


    for record in metadata:

        document_id = record.get(
            "document_id"
        )


        domain_tags = DOCUMENT_TAGS.get(
            document_id
        )


        if domain_tags is None:

            missing_documents.add(
                document_id
            )

            continue


        # Preserve existing tags
        existing_tags = record.get(
            "tags",
            []
        )


        # Add new domain tags
        combined_tags = list(
            dict.fromkeys(
                existing_tags +
                domain_tags
            )
        )


        record[
            "tags"
        ] = combined_tags


        # Additional explicit metadata field
        record[
            "domain_tags"
        ] = domain_tags


        enriched_count += 1


    # --------------------------------------------------------
    # SAVE ENRICHED METADATA
    # --------------------------------------------------------

    with open(
        OUTPUT_METADATA_PATH,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            metadata,
            f,
            indent=4,
            ensure_ascii=False
        )


    # --------------------------------------------------------
    # RESULTS
    # --------------------------------------------------------

    print("\n" + "=" * 70)
    print(
        "METADATA ENRICHMENT RESULT"
    )
    print("=" * 70)

    print(
        f"Total records: "
        f"{len(metadata)}"
    )

    print(
        f"Enriched records: "
        f"{enriched_count}"
    )

    print(
        f"Unique documents configured: "
        f"{len(DOCUMENT_TAGS)}"
    )

    print(
        f"Documents missing enrichment rules: "
        f"{len(missing_documents)}"
    )


    if missing_documents:

        print(
            "\nMissing document IDs:"
        )

        for document_id in sorted(
            missing_documents
        ):

            print(
                f"  - {document_id}"
            )


    print(
        "\nEnriched metadata saved to:"
    )

    print(
        OUTPUT_METADATA_PATH
    )


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    enrich_metadata()