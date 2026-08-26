from app.orders import lookup_order, normalize_order_id


def test_normalize_lowercase_and_spaces():
    assert normalize_order_id("  ord-1007  ") == "ORD-1007"


def test_valid_order_lookup():
    result = lookup_order("ORD-1007")

    assert result["found"] is True
    assert result["order_id"] == "ORD-1007"
    assert result["status"] == "shipped"
    assert result["carrier"] == "UPS"
    assert result["estimated_delivery"] == "2026-08-22"


def test_internal_data_is_not_exposed():
    result = lookup_order("ORD-1007")

    text = str(result).lower()

    assert "ava.morgan@example.test" not in text
    assert "220 king street" not in text
    assert "risk_score" not in text
    assert "fraud review" not in text


def test_cancelled_order_does_not_return_stale_eta():
    result = lookup_order("ORD-1004")

    assert result["found"] is True
    assert result["status"] == "cancelled"
    assert "estimated_delivery" not in result
    assert "tracking_number" not in result


def test_shipped_order_without_eta():
    result = lookup_order("ORD-1011")

    assert result["found"] is True
    assert result["status"] == "shipped"
    assert result["carrier"] == "Canada Post"
    assert "estimated_delivery" not in result


def test_missing_order():
    result = lookup_order("ORD-9999")

    assert result["found"] is False
    assert result["error"] == "order_not_found"


def test_malformed_order_id():
    result = lookup_order("hello123")

    assert result["found"] is False
    assert result["error"] == "invalid_order_id"