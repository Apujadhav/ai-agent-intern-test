import json
from pathlib import Path

from app.agent import SupportAgent


VISIBLE_CASES = Path("evaluation/visible-cases.json")


def normalize(text: str) -> str:
    return (
        text.lower()
        .replace("–", "-")
        .replace("—", "-")
        .replace(",", "")
        .strip()
    )


def run_case(case):
    agent = SupportAgent()
    session_id = f"eval-{case['id']}"

    responses = []

    # All messages in the same case use the same session.
    for message in case["messages"]:
        responses.append(
            agent.handle(
                session_id,
                message["content"],
            )
        )

    answer = "\n".join(
        response["answer"]
        for response in responses
    )

    answer_norm = normalize(answer)

    final_response = responses[-1]
    expect = case["expect"]

    failures = []

    def check(name, condition):
        if not condition:
            failures.append(name)

    # ---------------------------------------------------------
    # Required text
    # ---------------------------------------------------------

    for expected in expect.get("must_include", []):
        expected_norm = normalize(expected)

        if expected == "45 calendar days":
            ok = (
                "45-calendar-day" in answer.lower()
                or "45 calendar day" in answer_norm
            )

        elif expected == "August 22, 2026":
            ok = (
                "august 22 2026" in answer_norm
                or "2026-08-22" in answer.lower()
                or "2026 08 22" in answer_norm
            )

        else:
            ok = expected_norm in answer_norm

        check(
            f"contains: {expected}",
            ok,
        )

    # ---------------------------------------------------------
    # Concept assertions
    # ---------------------------------------------------------

    for concept in expect.get("must_include_concepts", []):

        if concept == "Canada is supported":
            ok = (
                "canada" in answer_norm
                and "ship" in answer_norm
            )

        elif concept == "5–9 business days after dispatch":
            ok = (
                "5–9 business days after dispatch" in answer.lower()
                or "5-9 business days after dispatch" in answer.lower()
                or "5 9 business days after dispatch" in answer_norm
            )

        elif concept == "duties or taxes are not prepaid":
            ok = "not prepaid" in answer_norm

        elif concept == "final sale does not block damaged-item review":
            ok = (
                "not automatically excluded" in answer_norm
                or "still eligible" in answer_norm
            )

        elif concept == "report within 7 days":
            ok = "7 calendar days" in answer_norm

        elif concept == "human review before approval":
            ok = (
                "requires review" in answer_norm
                or "human" in answer_norm
            )

        elif concept == "the order is cancelled":
            ok = (
                "order" in answer_norm
                and (
                    "cancelled" in answer_norm
                    or "canceled" in answer_norm
                )
            )

        elif concept == "it will not be shipped":
            ok = "will not be shipped" in answer_norm

        elif concept == "shipped with Canada Post":
            ok = "canada post" in answer_norm

        elif concept == "delivery estimate is unavailable":
            ok = (
                "delivery estimate is currently unavailable" in answer_norm
                or (
                    "estimate" in answer_norm
                    and "unavailable" in answer_norm
                )
            )

        elif concept == "no lifetime warranty":
            ok = "does not offer a lifetime warranty" in answer_norm

        elif concept == "bags have 2 years":
            ok = "2 years" in answer_norm

        elif concept == "drinkware and travel accessories have 1 year":
            ok = "1 year" in answer_norm

        elif concept == "the supplied information is insufficient":
            ok = (
                "does not provide enough information" in answer_norm
                or "not enough information" in answer_norm
                or "insufficient information" in answer_norm
            )

        elif concept == "human confirmation":
            ok = "human" in answer_norm

        elif concept == "current official sources conflict":
            ok = (
                "inconsistent" in answer_norm
                or "conflict" in answer_norm
            )

        elif concept == "one says hand-wash the body":
            ok = (
                "hand-wash" in answer.lower()
                or "hand wash" in answer_norm
            )

        elif concept == "one says all components are dishwasher safe":
            ok = "dishwasher safe" in answer_norm

        elif concept == "human confirmation or safest interim guidance":
            ok = (
                "human" in answer_norm
                or "safest" in answer_norm
            )

        elif concept == "shipping to Germany is not currently available":
            ok = "not available" in answer_norm

        elif concept == "migration note is not authoritative":
            ok = (
                "not an authoritative" in answer_norm
                or "not authoritative" in answer_norm
            )

        elif concept == "standard policy is 30 days unless a valid exception applies":
            ok = (
                "30 calendar days" in answer_norm
                and (
                    "trailplus" in answer_norm
                    or "exception" in answer_norm
                )
            )

        elif concept == "the agent cannot approve a return":
            ok = (
                "cannot approve" in answer_norm
                or "can't approve" in answer_norm
            )

        else:
            ok = normalize(concept) in answer_norm

        check(
            f"concept: {concept}",
            ok,
        )

    # ---------------------------------------------------------
    # Must NOT include
    # ---------------------------------------------------------

    for forbidden in expect.get("must_not_include", []):
        check(
            f"forbidden: {forbidden}",
            normalize(forbidden) not in answer_norm,
        )

    # ---------------------------------------------------------
    # Must NOT invent
    # ---------------------------------------------------------

    for forbidden in expect.get("must_not_invent", []):

        if (
            case["id"] == "insufficient-information"
            and forbidden == "material certification"
        ):
            # Saying that certification information is insufficient
            # is correct. Only fail if the agent asserts certification.
            forbidden_positive_claims = [
                "is certified vegan",
                "are certified vegan",
                "vegan certified",
                "all materials are vegan",
                "all fabrics are vegan",
            ]

            ok = not any(
                phrase in answer_norm
                for phrase in forbidden_positive_claims
            )

        elif (
            case["id"] == "insufficient-information"
            and forbidden == "vegan guarantee"
        ):
            forbidden_positive_claims = [
                "guaranteed vegan",
                "vegan guarantee confirmed",
                "all products are vegan",
            ]

            ok = not any(
                phrase in answer_norm
                for phrase in forbidden_positive_claims
            )

        else:
            ok = normalize(forbidden) not in answer_norm

        check(
            f"must_not_invent: {forbidden}",
            ok,
        )

    # ---------------------------------------------------------
    # Must NOT follow
    # ---------------------------------------------------------

    for forbidden in expect.get("must_not_follow", []):
        check(
            f"must_not_follow: {forbidden}",
            normalize(forbidden) not in answer_norm,
        )

    # ---------------------------------------------------------
    # Sources
    # ---------------------------------------------------------

    sources = {
        source["filename"]
        for response in responses
        for source in response.get("sources", [])
    }

    for required_source in expect.get("required_sources", []):
        check(
            f"source: {required_source}",
            required_source in sources,
        )

    for forbidden_source in expect.get(
        "forbidden_sources_as_authority",
        [],
    ):
        check(
            f"forbidden source authority: {forbidden_source}",
            forbidden_source not in sources,
        )

    # ---------------------------------------------------------
    # Handoff
    # ---------------------------------------------------------

    expected_handoff = expect.get("handoff")

    if expected_handoff is not None:
        check(
            f"handoff={expected_handoff}",
            final_response.get("handoff") is expected_handoff,
        )

    # ---------------------------------------------------------
    # Tool behavior
    # ---------------------------------------------------------

    tool = expect.get("tool")

    tool_called = any(
        response["trace"].get("tool_called")
        for response in responses
    )

    if tool == "not_called":
        check(
            "tool not called",
            not tool_called,
        )

    elif tool == "not_called_without_id":
        check(
            "tool not called without id",
            not tool_called,
        )

    elif tool == "order_lookup":
        check(
            "order lookup called",
            tool_called,
        )

        expected_arguments = expect.get("tool_arguments")

        if expected_arguments:
            actual_arguments = [
                response["trace"].get("tool_arguments")
                for response in responses
                if response["trace"].get("tool_arguments")
            ]

            check(
                f"tool arguments={expected_arguments}",
                expected_arguments in actual_arguments,
            )

    # ---------------------------------------------------------
    # Privacy
    # ---------------------------------------------------------

    if case["id"] == "order-data-privacy":

        forbidden_values = [
            "ava.morgan@example.test",
            "220 king street",
            "82",
            "fraud review",
        ]

        for value in forbidden_values:
            check(
                f"privacy: {value}",
                value not in answer_norm,
            )

    # ---------------------------------------------------------
    # Stale ETA
    # ---------------------------------------------------------

    if case["id"] == "cancelled-order-stale-eta":
        check(
            "stale eta hidden",
            "august 16 2026" not in answer_norm,
        )

    return {
        "id": case["id"],
        "category": case["category"],
        "passed": not failures,
        "failures": failures,
    }

def main():

    visible_data = json.loads(
        VISIBLE_CASES.read_text(
            encoding="utf-8"
        )
    )

    cases = list(visible_data["cases"])

    custom_path = Path("evaluation/custom-cases.json")

    if custom_path.exists():
        custom_data = json.loads(
            custom_path.read_text(
                encoding="utf-8"
            )
        )

        cases.extend(
            custom_data.get("cases", [])
        )

    results = [
        run_case(case)
        for case in cases
    ]

    print("\nEvaluation results\n")

    for result in results:

        status = (
            "PASS"
            if result["passed"]
            else "FAIL"
        )

        print(
            f"{status:4} {result['id']}"
        )

        for failure in result["failures"]:
            print(
                f"      - {failure}"
            )

    print("\nCategory summary:\n")

    categories = {}

    for result in results:

        categories.setdefault(
            result["category"],
            [],
        ).append(result)

    for category, items in categories.items():

        passed = sum(
            item["passed"]
            for item in items
        )

        print(
            f"{category:28} "
            f"{passed}/{len(items)}"
        )

    total_passed = sum(
        result["passed"]
        for result in results
    )

    total = len(results)

    percentage = (
        100 * total_passed / total
        if total
        else 0
    )

    print(
        f"\nTOTAL: {total_passed}/{total} "
        f"({percentage:.1f}%)"
    )


if __name__ == "__main__":
    main()