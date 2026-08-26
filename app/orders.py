import json
import re
from pathlib import Path


# Find the project root directory.
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Location of the supplied orders.json file.
ORDERS_FILE = PROJECT_ROOT / "data" / "orders.json"


def load_orders():
    """Load the order dataset once."""
    with open(ORDERS_FILE, "r", encoding="utf-8") as file:
        data = json.load(file)

    return {
        order["order_id"]: order
        for order in data["orders"]
    }


ORDERS = load_orders()


def normalize_order_id(order_id: str) -> str:
    """
    Normalize harmless user input differences.

    Example:
        ' ord-1007 ' -> 'ORD-1007'
        'ord-1007'   -> 'ORD-1007'
    """
    return order_id.strip().upper()


def is_valid_order_id(order_id: str) -> bool:
    """Check the expected ORD-1234 style format."""
    return bool(re.fullmatch(r"ORD-\d+", order_id))


def lookup_order(order_id: str) -> dict:
    """
    Safely look up an order and return only customer-safe fields.

    The full order record is never returned.
    """

    if not isinstance(order_id, str):
        return {
            "found": False,
            "error": "invalid_order_id",
            "message": "The order ID is invalid."
        }

    normalized_id = normalize_order_id(order_id)

    if not is_valid_order_id(normalized_id):
        return {
            "found": False,
            "error": "invalid_order_id",
            "order_id": normalized_id,
            "message": "The order ID format is invalid."
        }

    order = ORDERS.get(normalized_id)

    if order is None:
        return {
            "found": False,
            "error": "order_not_found",
            "order_id": normalized_id,
            "message": "The order was not found. Please check the order ID or contact support."
        }

    # ---------------------------------------------------------
    # Only expose customer-safe fields.
    # ---------------------------------------------------------

    result = {
        "found": True,
        "order_id": order["order_id"],
        "membership_tier": order.get("membership_tier"),
        "status": order.get("status"),
        "status_updated_at": order.get("status_updated_at"),
        "customer_safe_message": order.get("customer_safe_message"),
    }

    # Include item information only when available.
    result["items"] = [
        {
            "name": item.get("name"),
            "quantity": item.get("quantity"),
            "final_sale": item.get("final_sale"),
        }
        for item in order.get("items", [])
    ]

    # ---------------------------------------------------------
    # Delivery-related fields
    # ---------------------------------------------------------

    status = order.get("status")

    # Cancelled and returned orders must not expose stale
    # shipping/ETA information as if they are still arriving.
    if status not in {"cancelled", "returned"}:

        if order.get("shipped_at") is not None:
            result["shipped_at"] = order["shipped_at"]

        if order.get("delivered_at") is not None:
            result["delivered_at"] = order["delivered_at"]

        if order.get("carrier") is not None:
            result["carrier"] = order["carrier"]

        if order.get("tracking_number") is not None:
            result["tracking_number"] = order["tracking_number"]

        if order.get("estimated_delivery") is not None:
            result["estimated_delivery"] = order["estimated_delivery"]

    return result