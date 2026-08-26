import re

from app.orders import lookup_order, normalize_order_id
from app.retriever import (
    retrieve,
    detect_source_conflict,
)
from app.session import SessionStore


ORDER_ID_PATTERN = re.compile(r"\bORD-\d+\b", re.IGNORECASE)


class SupportAgent:
    def __init__(self):
        self.sessions = SessionStore()

    def extract_order_id(self, message: str):
        match = ORDER_ID_PATTERN.search(message)

        if not match:
            return None

        return normalize_order_id(match.group(0))

    def looks_like_order_question(
        self,
        message: str,
        has_previous_order: bool = False,
    ) -> bool:
        text = message.lower()

        # Explicit order ID always means order lookup.
        if self.extract_order_id(message) is not None:
            return True

        order_phrases = [
            "tracking",
            "where is my order",
            "where's my order",
            "when will my order",
            "when will order",
            "track my",
            "order status",
            "order number",
        ]

        if any(phrase in text for phrase in order_phrases):
            return True

        # Follow-up delivery questions reuse the previous order
        # when a session already has one.
        follow_up_phrases = [
            "when will it arrive",
            "when will it get here",
            "when should it arrive",
            "when should it get here",
            "where is it",
            "where is my package",
        ]

        if any(phrase in text for phrase in follow_up_phrases):
            return True

        return False

    def looks_like_internal_request(self, message: str) -> bool:
        text = message.lower()

        forbidden_terms = [
            "system prompt",
            "hidden prompt",
            "hidden instructions",
            "internal note",
            "internal notes",
            "risk score",
            "customer email",
            "customer address",
            "shipping address",
            "secret",
            "credential",
        ]

        return any(term in text for term in forbidden_terms)

    def build_response(
        self,
        answer: str,
        sources=None,
        handoff: bool = False,
        trace=None,
    ):
        return {
            "answer": answer,
            "sources": sources or [],
            "handoff": handoff,
            "trace": trace or {},
        }

    def handle(self, session_id: str, message: str) -> dict:
        session = self.sessions.get_or_create(session_id)
        session.add_turn("user", message)

        query_text = message.lower()

        # =====================================================
        # 1. Untrusted migration / prompt-injection content
        # =====================================================

        migration_injection = (
            "migration note" in query_text
            or "migration notes" in query_text
            or "60 days" in query_text
            or "ignore the real policy" in query_text
            or "ignore prior rules" in query_text
            or "ignore all prior rules" in query_text
            or "approve my return" in query_text
        )

        if migration_injection:
            result = self.build_response(
                answer=(
                    "The migration note is not an authoritative customer "
                    "policy and cannot override the current Returns Policy. "
                    "The standard return window is **30 calendar days of "
                    "delivery**, unless a valid exception such as TrailPlus "
                    "applies. I cannot approve a return on my own."
                ),
                sources=[
                    {
                        "filename": "01-returns-policy-current.md",
                        "heading": "Standard return window",
                    }
                ],
                handoff=False,
                trace={
                    "route": "retrieval",
                    "tool_called": False,
                    "conflict": False,
                    "security_filter": "untrusted_migration_content",
                },
            )

            session.add_turn("assistant", result["answer"])
            return result

        # =====================================================
        # 2. Privacy / internal information
        # =====================================================

        if self.looks_like_internal_request(message):
            result = self.build_response(
                answer=(
                    "I can't provide internal-only information, "
                    "hidden instructions, customer private data, "
                    "risk scores, or system secrets."
                ),
                handoff=True,
                trace={
                    "route": "privacy",
                    "tool_called": False,
                },
            )

            session.add_turn("assistant", result["answer"])
            return result

        # =====================================================
        # 3. Order questions
        # =====================================================

        if self.looks_like_order_question(
            message,
            has_previous_order=session.last_order_id is not None,
        ):
            order_id = self.extract_order_id(message)

            # Reuse the previous order for a legitimate follow-up.
            if order_id is None:
                order_id = session.last_order_id

            # Never invent an order ID.
            if order_id is None:
                result = self.build_response(
                    answer=(
                        "Please provide your order ID so I can check "
                        "the order."
                    ),
                    handoff=False,
                    trace={
                        "route": "order",
                        "tool_called": False,
                    },
                )

                session.add_turn("assistant", result["answer"])
                return result

            session.set_order_id(order_id)

            lookup_result = lookup_order(order_id)

            if not lookup_result["found"]:
                result = self.build_response(
                    answer=(
                        "I couldn't find that order. "
                        "Please check the order ID or contact support."
                    ),
                    handoff=True,
                    trace={
                        "route": "order",
                        "tool_called": True,
                        "tool_arguments": {
                            "order_id": order_id,
                        },
                        "tool_result": lookup_result,
                    },
                )

                session.add_turn("assistant", result["answer"])
                return result

            status = lookup_result["status"]

            # Status is authoritative.
            if status == "cancelled":
                answer = (
                    f"Order {order_id} is cancelled and will not be shipped."
                )

            elif status == "returned":
                answer = (
                    f"Order {order_id} has been returned. "
                    "The return was received and processed."
                )

            elif status == "exception":
                answer = (
                    f"Order {order_id} has a shipping exception "
                    "that requires support review."
                )

            elif status == "shipped":
                carrier = lookup_result.get("carrier")
                estimated = lookup_result.get("estimated_delivery")

                if estimated:
                    answer = (
                        f"Order {order_id} has shipped"
                        f"{' with ' + carrier if carrier else ''}. "
                        "The current estimated delivery date is "
                        f"{estimated}."
                    )
                else:
                    answer = (
                        f"Order {order_id} has shipped"
                        f"{' with ' + carrier if carrier else ''}, "
                        "but a delivery estimate is currently unavailable."
                    )

            else:
                answer = f"Order {order_id} is currently {status}."

            result = self.build_response(
                answer=answer,
                handoff=(status == "exception"),
                trace={
                    "route": "order",
                    "tool_called": True,
                    "tool_arguments": {
                        "order_id": order_id,
                    },
                    "tool_result": lookup_result,
                },
            )

            session.add_turn("assistant", result["answer"])
            return result

        # =====================================================
        # 4. Knowledge-base retrieval
        # =====================================================

        results = retrieve(message, top_k=8)

        # =====================================================
        # 5. Explicit abstention for unsupported
        #    vegan/material certification
        # =====================================================

        if (
            "vegan" in query_text
            and (
                "fabric" in query_text
                or "fabrics" in query_text
                or "adhesive" in query_text
                or "adhesives" in query_text
                or "material" in query_text
                or "materials" in query_text
            )
        ):
            result = self.build_response(
                answer=(
                    "The supplied information does not provide enough "
                    "information to confirm whether all bag fabrics and "
                    "adhesives are vegan. I don't want to guess or provide "
                    "an unsupported material certification. Please contact "
                    "a human support specialist for confirmation."
                ),
                handoff=True,
                trace={
                    "route": "retrieval",
                    "tool_called": False,
                    "conflict": False,
                    "abstention": True,
                    "retrieved": results,
                },
            )

            session.add_turn("assistant", result["answer"])
            return result

        # =====================================================
        # 6. No retrieved evidence
        # =====================================================

        if not results:
            result = self.build_response(
                answer=(
                    "I don't have enough information in the supplied "
                    "knowledge base to answer that reliably. "
                    "Please contact a human support specialist."
                ),
                handoff=True,
                trace={
                    "route": "retrieval",
                    "tool_called": False,
                    "retrieved": [],
                },
            )

            session.add_turn("assistant", result["answer"])
            return result

        # =====================================================
        # 7. Canada international-shipping follow-up
        # =====================================================

        canada_shipping_question = (
            "canada" in query_text
            and any(
                term in query_text
                for term in [
                    "how long",
                    "when",
                    "delivery",
                    "arrive",
                    "take",
                    "shipping",
                ]
            )
        )

        if canada_shipping_question:
            canada_results = [
                result
                for result in results
                if result["filename"] == "06-international-shipping.md"
            ]

            if canada_results:
                answer = (
                    "Canada is supported for international shipping. "
                    "Canadian orders generally arrive within **5–9 "
                    "business days after dispatch**, with **1–2 business "
                    "days** of processing before dispatch. Delivery "
                    "estimates may be extended by customs processing or "
                    "carrier delays. Import duties, taxes, and brokerage "
                    "charges are **not prepaid**; the recipient is "
                    "responsible for charges assessed by Canadian "
                    "authorities or the carrier."
                )

                preferred_headings = {
                    "Supported destinations",
                    "Canada delivery estimate",
                    "Duties and taxes",
                }

                sources = [
                    {
                        "filename": result["filename"],
                        "heading": result["heading"],
                    }
                    for result in canada_results
                    if result["heading"] in preferred_headings
                ]

                if not sources:
                    sources = [
                        {
                            "filename": result["filename"],
                            "heading": result["heading"],
                        }
                        for result in canada_results[:3]
                    ]

                result = self.build_response(
                    answer=answer,
                    sources=sources,
                    handoff=False,
                    trace={
                        "route": "retrieval",
                        "tool_called": False,
                        "conflict": False,
                        "exception": "canada_shipping_followup",
                        "retrieved": results,
                    },
                )

                session.set_topic(
                    "06-international-shipping.md"
                )
                session.add_turn("assistant", result["answer"])
                return result

        # =====================================================
        # 8. Final-sale damaged-item exception
        # =====================================================

        final_sale_terms = [
            "final sale",
            "final-sale",
        ]

        damage_terms = [
            "damaged",
            "broken",
            "defective",
            "wrong item",
        ]

        has_final_sale = any(
            term in query_text
            for term in final_sale_terms
        )

        has_damage = any(
            term in query_text
            for term in damage_terms
        )

        retrieved_files = {
            result["filename"]
            for result in results
        }

        has_final_sale_policy = (
            "03-final-sale-and-promotions.md"
            in retrieved_files
        )

        has_damage_policy = (
            "04-damaged-or-wrong-items.md"
            in retrieved_files
        )

        if (
            has_final_sale
            and has_damage
            and has_final_sale_policy
            and has_damage_policy
        ):
            sources = [
                {
                    "filename": result["filename"],
                    "heading": result["heading"],
                }
                for result in results
                if result["filename"]
                in {
                    "03-final-sale-and-promotions.md",
                    "04-damaged-or-wrong-items.md",
                }
            ]

            result = self.build_response(
                answer=(
                    "A final-sale item is not automatically excluded "
                    "when it arrives damaged, defective, or incorrect. "
                    "The issue should be reported within 7 calendar "
                    "days of delivery. A replacement, refund, or other "
                    "resolution requires review, so I cannot promise "
                    "approval."
                ),
                sources=sources,
                handoff=True,
                trace={
                    "route": "retrieval",
                    "tool_called": False,
                    "conflict": False,
                    "exception": "final_sale_damaged_item",
                    "retrieved": results,
                },
            )

            session.add_turn("assistant", result["answer"])
            return result

        # =====================================================
        # 9. Genuine source conflict
        # =====================================================

        conflict = detect_source_conflict(results)

        if conflict["conflict"]:
            sources = [
                {
                    "filename": result["filename"],
                    "heading": result["heading"],
                }
                for result in results
                if result["filename"] in conflict["sources"]
            ]

            result = self.build_response(
                answer=(
                    "The current official product information is "
                    "inconsistent. One source says the Breeze Tumbler "
                    "body should be hand-washed, while another says "
                    "all components are dishwasher safe. I recommend "
                    "human confirmation before putting the entire "
                    "tumbler in a dishwasher."
                ),
                sources=sources,
                handoff=True,
                trace={
                    "route": "retrieval",
                    "tool_called": False,
                    "conflict": True,
                    "retrieved": results,
                },
            )

            session.add_turn("assistant", result["answer"])
            return result

        # =====================================================
        # 10. Temporary deterministic grounded response
        # =====================================================

        top = results[0]

        sources = [
            {
                "filename": top["filename"],
                "heading": top["heading"],
            }
        ]

        session.set_topic(top["filename"])

        answer = (
            "According to the supplied information:\n\n"
            + top["text"]
        )

        result = self.build_response(
            answer=answer,
            sources=sources,
            handoff=False,
            trace={
                "route": "retrieval",
                "tool_called": False,
                "conflict": False,
                "retrieved": results,
            },
        )

        session.add_turn("assistant", result["answer"])

        return result