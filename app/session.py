class Session:
    """
    Stores relevant context for one conversation.
    """

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.history = []
        self.last_order_id = None
        self.last_topic = None

    def add_turn(self, role: str, content: str):
        self.history.append(
            {
                "role": role,
                "content": content,
            }
        )

        # Keep only the most recent turns.
        self.history = self.history[-6:]

    def set_order_id(self, order_id: str):
        self.last_order_id = order_id

    def set_topic(self, topic: str):
        self.last_topic = topic

    def get_recent_history(self):
        return self.history


class SessionStore:
    """
    Keeps separate conversation sessions.
    """

    def __init__(self):
        self.sessions = {}

    def get_or_create(self, session_id: str) -> Session:
        if session_id not in self.sessions:
            self.sessions[session_id] = Session(session_id)

        return self.sessions[session_id]