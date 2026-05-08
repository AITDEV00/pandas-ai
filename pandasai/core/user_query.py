class UserQuery:
    def __init__(self, user_query: str):
        self.value = user_query

    def __str__(self):
        return self.value

    def __repr__(self):
        return f"UserQuery(value={self.value})"

    def to_dict(self):
        """Return the raw query string (alias for to_json)."""
        return self.value

    def to_json(self):
        return self.value
