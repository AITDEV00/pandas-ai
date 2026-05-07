""" Memory class to store the conversations """
from typing import Union


class Memory:
    """Memory class to store the conversations"""

    _messages: list
    _memory_size: int
    agent_description: str

    def __init__(
        self, memory_size: int = 10, agent_description: Union[str, None] = None
    ):
        self._messages = []
        self._memory_size = memory_size
        self.agent_description = agent_description

    def add(self, message: str, is_user: bool):
        self._messages.append({"message": message, "is_user": is_user})

    def count(self) -> int:
        return len(self._messages)

    def all(self) -> list:
        return self._messages

    def last(self) -> dict:
        return self._messages[-1]

    def _truncate(self, message: str, max_length: int = 100) -> str:
        """
        Truncates the message if it is longer than max_length
        """
        return (
            f"{message[:max_length]} ..." if len(str(message)) > max_length else message
        )

    def get_previous_conversation(self) -> str:
        """
        Returns the previous conversation (all messages except the last one)
        formatted as ### QUERY / ### ANSWER blocks.

        Used by completion models (legacy) that concatenate everything into
        a single text prompt. Chat models should use
        ``to_openai_messages_for_chat()`` instead.
        """
        if len(self._messages) <= 1:
            return ""

        lines = []
        for msg in self._messages[:-1]:
            if msg["is_user"]:
                lines.append(f"### QUERY\n {msg['message']}")
            else:
                lines.append(f"### ANSWER\n {self._truncate(msg['message'])}")
        return "\n".join(lines)

    def to_json(self) -> list[dict[str, str]]:
        messages = []
        for message in self.all():
            if message["is_user"]:
                messages.append({"role": "user", "message": message["message"]})
            else:
                messages.append({"role": "assistant", "message": message["message"]})
        return messages

    def to_openai_messages_for_chat(self, num_turns: int = None):
        """Build the messages array for chat-completion LLM calls.

        This is the **authoritative** method for constructing the messages
        array sent to chat models (LiteLLM, OpenAI, etc.).  It guarantees:

        1. The **system prompt** is always the first message (never lost).
        2. Conversation history is rounded up so you always get complete
           user→assistant pairs — a dangling user message without its
           assistant reply is never sent as a standalone history entry.
        3. The **last message** in memory (the current user query) is
           **excluded** because it is already embedded in the rendered
           instruction template (the final user message added by the LLM
           caller).

        Args:
            num_turns: How many *user turns* of history to include.
                ``num_turns = 3`` means "include the previous 3 user prompts
                and their corresponding assistant responses".  Because the
                current query is the Nth user turn and is excluded, the
                actual history that appears in the messages array is the
                previous ``num_turns`` complete user→assistant pairs.

                If the available history has an odd number of messages
                (e.g. 5: u1 a1 u2 a2 u3), the count is rounded up to the
                next even number (6) so that u3 is paired with its
                (pending/expected) assistant response.  In practice this
                means: if ``num_turns = 3`` and there are 5 messages, we
                round to 6 → but since the last message is the current
                query, we include messages [0..4] = u1 a1 u2 a2, and the
                current query u3 goes in the instruction template.

                If ``None``, falls back to ``self._memory_size``.

        Returns:
            list[dict]: Messages in OpenAI chat-completion format::

                [
                    {"role": "system",  "content": "<agent_description>"},
                    {"role": "user",    "content": "previous query 1"},
                    {"role": "assistant","content": "previous answer 1"},
                    {"role": "user",    "content": "previous query 2"},
                    {"role": "assistant","content": "previous answer 2"},
                ]
                # The LLM caller then appends the current instruction as
                # the final user message.
        """
        if num_turns is None:
            num_turns = self._memory_size

        messages = []

        # 1. ALWAYS include the system prompt first
        if self.agent_description:
            messages.append(
                {"role": "system", "content": self.agent_description}
            )

        # 2. Gather previous conversation (excluding the current query)
        all_msgs = self.all()
        if len(all_msgs) <= 1:
            # Only the current query (or empty) — no history to include
            return messages

        # Exclude the last message — it's the current query already in the
        # instruction template
        history = all_msgs[:-1]

        # 3. Apply the num_turns limit
        #    num_turns means "how many user prompts to include".
        #    Each user prompt is paired with its assistant response,
        #    so num_turns user messages = num_turns * 2 raw messages
        #    (user + assistant pairs).
        #
        #    Round UP: if num_turns is 3 and we have u1 a1 u2 a2 u3,
        #    that's 5 messages (3 user turns). We need to round up to
        #    include the full pair — but since we already excluded the
        #    current query, the history should only contain complete
        #    pairs. If the last message in history is a user message
        #    (dangling), we drop it to maintain complete pairs.
        max_raw_messages = num_turns * 2  # user + assistant pairs

        # Take the last max_raw_messages from history
        history_slice = history[-max_raw_messages:]

        # Round up: ensure we don't end with a dangling user message.
        # If the last message in the slice is a user message (no
        # assistant response yet), drop it so we only send complete
        # pairs.
        if history_slice and history_slice[-1]["is_user"]:
            history_slice = history_slice[:-1]

        # 4. Append as structured messages
        for msg in history_slice:
            role = "user" if msg["is_user"] else "assistant"
            messages.append({"role": role, "content": msg["message"]})

        return messages

    def clear(self):
        self._messages = []

    @property
    def memory_size(self) -> int:
        """Maximum number of user turns to include in conversation history."""
        return self._memory_size

    @memory_size.setter
    def memory_size(self, value: int):
        """Set the maximum number of user turns for conversation history."""
        self._memory_size = value
