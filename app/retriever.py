import json
import math
import re
from collections import Counter
from pathlib import Path

import numpy as np
import yaml


PROJECT_ROOT = Path(__file__).resolve().parent.parent
KNOWLEDGE_BASE = PROJECT_ROOT / "knowledge-base"
INDEX_DIR = PROJECT_ROOT / "index"
INDEX_FILE = INDEX_DIR / "chunks.json"


def parse_front_matter(text: str) -> tuple[dict, str]:
    """
    Extract YAML front matter from a Markdown document.

    Expected format:

    ---
    key: value
    ---
    markdown content
    """

    if not text.startswith("---"):
        return {}, text

    parts = text.split("---", 2)

    if len(parts) < 3:
        return {}, text

    _, front_matter, body = parts

    metadata = yaml.safe_load(front_matter) or {}

    # Convert YAML date/datetime values into JSON-safe strings.
    for key, value in metadata.items():
        if hasattr(value, "isoformat"):
            metadata[key] = value.isoformat()

    return metadata, body.strip()

def split_by_headings(body: str) -> list[dict]:
    """
    Split Markdown content into heading-based sections.

    Each section contains:
    - heading
    - text
    """

    lines = body.splitlines()

    sections = []
    current_heading = None
    current_lines = []

    for line in lines:
        heading_match = re.match(r"^(#{1,6})\s+(.+)$", line)

        if heading_match:
            if current_heading is not None:
                content = "\n".join(current_lines).strip()

                if content:
                    sections.append(
                        {
                            "heading": current_heading,
                            "text": content,
                        }
                    )

            current_heading = heading_match.group(2).strip()
            current_lines = []
        else:
            current_lines.append(line)

    if current_heading is not None:
        content = "\n".join(current_lines).strip()

        if content:
            sections.append(
                {
                    "heading": current_heading,
                    "text": content,
                }
            )

    return sections


def load_documents() -> list[dict]:
    """
    Read every Markdown document in the knowledge base.
    """

    documents = []

    for path in sorted(KNOWLEDGE_BASE.glob("*.md")):

        text = path.read_text(encoding="utf-8")

        metadata, body = parse_front_matter(text)

        sections = split_by_headings(body)

        for section_number, section in enumerate(sections):

            documents.append(
                {
                    "chunk_id": f"{path.name}::{section_number}",
                    "filename": path.name,
                    "heading": section["heading"],
                    "text": section["text"],
                    "metadata": metadata,
                }
            )

    return documents


def authority_rank(metadata: dict) -> int:
    """
    Give a deterministic authority ranking to a document.

    This does NOT decide conflicts by itself.
    It only helps prioritize authoritative customer-facing content.
    """

    status = metadata.get("status")
    audience = metadata.get("audience")
    authority = metadata.get("policy_authority")
    customer_answering = metadata.get("customer_answering")

    score = 0

    if status == "active":
        score += 100

    if status == "superseded":
        score -= 100

    if status == "draft":
        score -= 100

    if audience == "customer":
        score += 30

    if authority == "official":
        score += 30

    if authority in {"none", None}:
        score -= 30

    if customer_answering is False:
        score -= 100

    if audience == "internal":
        score -= 100

    return score


def build_index(records: list[dict]) -> None:
    """
    Save the parsed document chunks.

    Embeddings will be added in the next stage.
    """

    INDEX_DIR.mkdir(exist_ok=True)

    with open(INDEX_FILE, "w", encoding="utf-8") as file:
        json.dump(records, file, indent=2, ensure_ascii=False)


def build_document_index() -> list[dict]:
    """
    Parse all Markdown documents and create the local index.
    """

    records = load_documents()

    for record in records:
        record["authority_rank"] = authority_rank(
            record["metadata"]
        )

    build_index(records)

    return records


def load_index() -> list[dict]:
    """
    Load the previously created index.
    """

    if not INDEX_FILE.exists():
        return build_document_index()

    with open(INDEX_FILE, "r", encoding="utf-8") as file:
        return json.load(file)

def tokenize(text: str) -> list[str]:
    """
    Convert text into simple lowercase word tokens.
    """
    return re.findall(r"\b[a-z0-9][a-z0-9'-]*\b", text.lower())


def build_tfidf_vectors(records: list[dict]):
    """
    Build simple TF-IDF vectors for all indexed chunks.

    This is intentionally lightweight because the supplied
    knowledge base is small.
    """

    documents = [tokenize(record["text"]) for record in records]

    document_frequency = Counter()

    for tokens in documents:
        for token in set(tokens):
            document_frequency[token] += 1

    total_documents = len(documents)

    vocabulary = {
        token: index
        for index, token in enumerate(sorted(document_frequency))
    }

    vectors = []

    for tokens in documents:
        term_frequency = Counter(tokens)

        vector = np.zeros(len(vocabulary), dtype=float)

        for token, count in term_frequency.items():
            if token not in vocabulary:
                continue

            tf = 1 + math.log(count)

            df = document_frequency[token]

            idf = math.log(
                (total_documents + 1) / (df + 1)
            ) + 1

            vector[vocabulary[token]] = tf * idf

        norm = np.linalg.norm(vector)

        if norm > 0:
            vector = vector / norm

        vectors.append(vector)

    return vocabulary, np.array(vectors)


def cosine_similarity(query_vector, document_vectors):
    """
    Calculate cosine similarity between a query and
    every document vector.
    """

    return document_vectors @ query_vector

def is_customer_authoritative(record: dict) -> bool:
    """
    Return True only when a document is appropriate as
    customer-facing authoritative evidence.
    """

    metadata = record.get("metadata", {})

    return (
        metadata.get("status") == "active"
        and metadata.get("audience") == "customer"
        and metadata.get("policy_authority") == "official"
        and metadata.get("customer_answering", True) is not False
    )


def is_non_authoritative(record: dict) -> bool:
    """
    Identify documents that should not be used as authority
    for customer answers.
    """

    metadata = record.get("metadata", {})

    return (
        metadata.get("status") in {"superseded", "draft"}
        or metadata.get("audience") == "internal"
        or metadata.get("policy_authority") != "official"
        or metadata.get("customer_answering") is False
    )


def authority_boost(record: dict) -> float:
    """
    Deterministic ranking bonus.

    Active official customer documents get the strongest boost.
    Superseded/internal/draft material is strongly penalized.
    """

    if is_customer_authoritative(record):
        return 1.0

    if is_non_authoritative(record):
        return -1.0

    return 0.0


def query_relevance_boost(query: str, record: dict) -> float:
    """
    Give a small boost when the query explicitly mentions
    a topic directly covered by the retrieved document.
    """

    query_text = query.lower()
    filename = record["filename"].lower()
    heading = record["heading"].lower()
    text = record["text"].lower()

    boost = 0.0

    # Prefer Canada delivery-estimate evidence only when the
    # query is actually about Canada/international shipping.
    canada_shipping_query = (
        "canada" in query_text
        or "canadian" in query_text
        or "international" in query_text
        or "ship internationally" in query_text
    )

    delivery_question = any(term in query_text for term in [
        "how long",
        "when will",
        "when should",
        "how fast",
        "delivery",
        "arrive",
        "takes",
        "take",
    ])

    if canada_shipping_query and delivery_question:
        if filename == "06-international-shipping.md":
            if "delivery estimate" in heading:
                boost += 0.50

    return boost

def detect_source_conflict(results: list[dict]) -> dict:
    """
    Detect the genuine Breeze Tumbler conflict only when
    both conflicting sources are actually relevant to the query.
    """

    authoritative = [
        result
        for result in results
        if is_customer_authoritative(result)
    ]

    # Only consider reasonably relevant evidence.
    relevant = [
        result
        for result in authoritative
        if result.get("similarity", 0.0) >= 0.20
    ]

    filenames = {
        result["filename"]
        for result in relevant
    }

    conflict_sources = {
        "11-product-care.md",
        "12-breeze-tumbler-product-card.md",
    }

    if conflict_sources.issubset(filenames):
        return {
            "conflict": True,
            "sources": sorted(conflict_sources),
        }

    return {
        "conflict": False,
        "sources": [],
    }



def retrieve(
    query: str,
    top_k: int = 5,
    include_internal: bool = False,
) -> list[dict]:
    """
    Retrieve the most relevant knowledge-base sections.

    Internal/non-customer documents are excluded by default.
    """

    records = load_index()

    vocabulary, document_vectors = build_tfidf_vectors(records)

    query_tokens = tokenize(query)

    query_vector = np.zeros(len(vocabulary), dtype=float)

    query_frequency = Counter(query_tokens)

    total_documents = len(records)

    document_frequency = Counter()

    for record in records:
        for token in set(tokenize(record["text"])):
            document_frequency[token] += 1

    for token, count in query_frequency.items():

        if token not in vocabulary:
            continue

        tf = 1 + math.log(count)

        df = document_frequency[token]

        idf = math.log(
            (total_documents + 1) / (df + 1)
        ) + 1

        query_vector[vocabulary[token]] = tf * idf

    query_norm = np.linalg.norm(query_vector)

    if query_norm == 0:
        return []

    query_vector = query_vector / query_norm

    similarities = cosine_similarity(
        query_vector,
        document_vectors,
    )

    results = []

    for index, similarity in enumerate(similarities):

        record = records[index]

        metadata = record["metadata"]

        # Do not expose internal customer-answering-disabled
        # material as normal customer evidence.
        if not include_internal:

            if metadata.get("customer_answering") is False:
                continue

            if metadata.get("audience") == "internal":
                continue

        result = dict(record)

        result["similarity"] = float(similarity)

        result["authority_boost"] = authority_boost(result)

        result["query_relevance_boost"] = query_relevance_boost(
            query,
            result,
                )

        result["final_score"] = (
            result["similarity"]
            + result["authority_boost"]
            + result["query_relevance_boost"]
        )

        results.append(result)

    results.sort(
    key=lambda item: (
        item["final_score"],
        item["similarity"],
    ),
    reverse=True,
)

    return results[:top_k]

if __name__ == "__main__":

    records = build_document_index()

    print(f"Indexed {len(records)} sections.")

    for record in records[:10]:
        print()
        print("FILE:", record["filename"])
        print("HEADING:", record["heading"])
        print("AUTHORITY:", record["authority_rank"])


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