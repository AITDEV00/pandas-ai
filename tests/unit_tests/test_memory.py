from pandasai.helpers.memory import Memory


def test_to_json_empty_memory():
    memory = Memory()
    assert memory.to_json() == []


def test_to_json_with_messages():
    memory = Memory()

    # Add test messages
    memory.add("Hello", is_user=True)
    memory.add("Hi there!", is_user=False)
    memory.add("How are you?", is_user=True)

    expected_json = [
        {"role": "user", "message": "Hello"},
        {"role": "assistant", "message": "Hi there!"},
        {"role": "user", "message": "How are you?"},
    ]

    assert memory.to_json() == expected_json


def test_to_json_message_order():
    memory = Memory()

    # Add messages in specific order
    messages = [("Message 1", True), ("Message 2", False), ("Message 3", True)]

    for msg, is_user in messages:
        memory.add(msg, is_user=is_user)

    result = memory.to_json()

    # Verify order is preserved
    assert len(result) == 3
    assert result[0]["message"] == "Message 1"
    assert result[1]["message"] == "Message 2"
    assert result[2]["message"] == "Message 3"


# --- Tests for to_openai_messages_for_chat() ---


def test_to_openai_messages_for_chat_empty():
    """No messages → only system prompt (if set), no history."""
    memory = Memory(agent_description="I am a data assistant")
    result = memory.to_openai_messages_for_chat()
    assert result == [{"role": "system", "content": "I am a data assistant"}]


def test_to_openai_messages_for_chat_single_query():
    """Only the current query (1 message) → no history to include."""
    memory = Memory(agent_description="I am a data assistant")
    memory.add("tell me about sales", is_user=True)
    result = memory.to_openai_messages_for_chat()
    # Current query is excluded (it goes in the instruction template)
    assert result == [{"role": "system", "content": "I am a data assistant"}]


def test_to_openai_messages_for_chat_one_complete_pair():
    """1 complete pair (user + assistant) + current query → history has 1 pair."""
    memory = Memory(agent_description="System prompt")
    memory.add("how many are female", is_user=True)
    memory.add("There are 10 female employees.", is_user=False)
    memory.add("tell me everyone called mhmd", is_user=True)

    result = memory.to_openai_messages_for_chat()
    assert result == [
        {"role": "system", "content": "System prompt"},
        {"role": "user", "content": "how many are female"},
        {"role": "assistant", "content": "There are 10 female employees."},
    ]


def test_to_openai_messages_for_chat_two_complete_pairs():
    """2 complete pairs + current query → history has 2 pairs."""
    memory = Memory(agent_description="System prompt")
    memory.add("query 1", is_user=True)
    memory.add("answer 1", is_user=False)
    memory.add("query 2", is_user=True)
    memory.add("answer 2", is_user=False)
    memory.add("current query", is_user=True)

    result = memory.to_openai_messages_for_chat()
    assert result == [
        {"role": "system", "content": "System prompt"},
        {"role": "user", "content": "query 1"},
        {"role": "assistant", "content": "answer 1"},
        {"role": "user", "content": "query 2"},
        {"role": "assistant", "content": "answer 2"},
    ]


def test_to_openai_messages_for_chat_rounds_up_dangling_user():
    """If history ends with a dangling user message (no assistant response),
    it is dropped to maintain complete pairs (round-up behavior)."""
    memory = Memory(agent_description="System prompt")
    memory.add("query 1", is_user=True)
    memory.add("answer 1", is_user=False)
    memory.add("query 2", is_user=True)  # dangling — no assistant response yet
    memory.add("current query", is_user=True)

    result = memory.to_openai_messages_for_chat()
    # query 2 is dangling → dropped. Only query1/answer1 pair included.
    assert result == [
        {"role": "system", "content": "System prompt"},
        {"role": "user", "content": "query 1"},
        {"role": "assistant", "content": "answer 1"},
    ]


def test_to_openai_messages_for_chat_num_turns_limits_history():
    """num_turns=1 means only 1 previous user turn (1 pair) in history."""
    memory = Memory(agent_description="System prompt")
    memory.add("query 1", is_user=True)
    memory.add("answer 1", is_user=False)
    memory.add("query 2", is_user=True)
    memory.add("answer 2", is_user=False)
    memory.add("current query", is_user=True)

    # num_turns=1 → only 1 pair (2 raw messages) from history
    result = memory.to_openai_messages_for_chat(num_turns=1)
    assert result == [
        {"role": "system", "content": "System prompt"},
        {"role": "user", "content": "query 2"},
        {"role": "assistant", "content": "answer 2"},
    ]


def test_to_openai_messages_for_chat_num_turns_3_rounds_up():
    """num_turns=3 with only 2 pairs available → includes all 2 pairs (no truncation)."""
    memory = Memory(agent_description="System prompt")
    memory.add("query 1", is_user=True)
    memory.add("answer 1", is_user=False)
    memory.add("query 2", is_user=True)
    memory.add("answer 2", is_user=False)
    memory.add("current query", is_user=True)

    # num_turns=3 → up to 3 pairs, but only 2 available → all included
    result = memory.to_openai_messages_for_chat(num_turns=3)
    assert result == [
        {"role": "system", "content": "System prompt"},
        {"role": "user", "content": "query 1"},
        {"role": "assistant", "content": "answer 1"},
        {"role": "user", "content": "query 2"},
        {"role": "assistant", "content": "answer 2"},
    ]


def test_to_openai_messages_for_chat_always_has_system_prompt():
    """System prompt is ALWAYS the first message, even with no history."""
    memory = Memory(agent_description="Important system instructions")
    memory.add("hello", is_user=True)

    result = memory.to_openai_messages_for_chat()
    assert result[0] == {"role": "system", "content": "Important system instructions"}


def test_to_openai_messages_for_chat_no_system_prompt():
    """If no agent_description, no system message — but history still works."""
    memory = Memory()
    memory.add("query 1", is_user=True)
    memory.add("answer 1", is_user=False)
    memory.add("current query", is_user=True)

    result = memory.to_openai_messages_for_chat()
    assert result == [
        {"role": "user", "content": "query 1"},
        {"role": "assistant", "content": "answer 1"},
    ]


def test_to_openai_messages_for_chat_uses_memory_size_default():
    """When num_turns is not passed, uses _memory_size as default."""
    memory = Memory(memory_size=1, agent_description="System prompt")
    memory.add("query 1", is_user=True)
    memory.add("answer 1", is_user=False)
    memory.add("query 2", is_user=True)
    memory.add("answer 2", is_user=False)
    memory.add("current query", is_user=True)

    # memory_size=1 → num_turns=1 → only 1 pair from history
    result = memory.to_openai_messages_for_chat()
    assert result == [
        {"role": "system", "content": "System prompt"},
        {"role": "user", "content": "query 2"},
        {"role": "assistant", "content": "answer 2"},
    ]


def test_to_openai_messages_for_chat_long_conversation():
    """5 pairs of history, num_turns=3 → only last 3 pairs included."""
    memory = Memory(agent_description="System prompt")
    for i in range(1, 6):
        memory.add(f"query {i}", is_user=True)
        memory.add(f"answer {i}", is_user=False)
    memory.add("current query", is_user=True)

    result = memory.to_openai_messages_for_chat(num_turns=3)
    assert result == [
        {"role": "system", "content": "System prompt"},
        {"role": "user", "content": "query 3"},
        {"role": "assistant", "content": "answer 3"},
        {"role": "user", "content": "query 4"},
        {"role": "assistant", "content": "answer 4"},
        {"role": "user", "content": "query 5"},
        {"role": "assistant", "content": "answer 5"},
    ]
