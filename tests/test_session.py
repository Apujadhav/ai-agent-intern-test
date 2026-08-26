from app.session import Session, SessionStore


def test_session_stores_order_id():
    session = Session("test-session")

    session.set_order_id("ORD-1007")

    assert session.last_order_id == "ORD-1007"


def test_session_stores_topic():
    session = Session("test-session")

    session.set_topic("06-international-shipping.md")

    assert session.last_topic == "06-international-shipping.md"


def test_session_stores_recent_history():
    session = Session("test-session")

    session.add_turn("user", "Where is ORD-1007?")
    session.add_turn("assistant", "Your order has shipped.")

    history = session.get_recent_history()

    assert len(history) == 2
    assert history[0]["role"] == "user"
    assert history[1]["role"] == "assistant"


def test_session_history_is_limited():
    session = Session("test-session")

    for i in range(10):
        session.add_turn("user", f"message {i}")

    history = session.get_recent_history()

    assert len(history) == 6


def test_sessions_are_separate():
    store = SessionStore()

    session_a = store.get_or_create("A")
    session_b = store.get_or_create("B")

    session_a.set_order_id("ORD-1007")

    assert session_a.last_order_id == "ORD-1007"
    assert session_b.last_order_id is None