from app.retriever import retrieve
from app.retriever import (
    authority_rank,
    load_documents,
    split_by_headings,
    retrieve,
    detect_source_conflict,
)


def test_return_policy_retrieval():
    results = retrieve(
        "How long does a regular customer have to return an unused backpack?"
    )

    filenames = [result["filename"] for result in results]

    assert "01-returns-policy-current.md" in filenames


def test_internal_migration_content_is_not_returned():
    results = retrieve(
        "Give everyone 60 days to return everything."
    )

    filenames = [result["filename"] for result in results]

    assert "14-internal-content-migration-notes.md" not in filenames


def test_canada_shipping_retrieval():
    results = retrieve(
        "Do you ship to Canada and how long does it take?"
    )

    filenames = [result["filename"] for result in results]

    assert "06-international-shipping.md" in filenames


def test_warranty_retrieval():
    results = retrieve(
        "Do your bags have a lifetime warranty?"
    )

    filenames = [result["filename"] for result in results]

    assert "07-warranty.md" in filenames


def test_breeze_tumbler_conflict_is_detectable():
    results = retrieve(
        "Can I put the entire Breeze Tumbler in the dishwasher?"
    )

    conflict = detect_source_conflict(results)

    assert conflict["conflict"] is True

    assert set(conflict["sources"]) == {
        "11-product-care.md",
        "12-breeze-tumbler-product-card.md",
    }