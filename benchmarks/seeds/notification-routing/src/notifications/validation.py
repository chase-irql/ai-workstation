def validate_message(message: str) -> str:
    if not message.strip():
        raise ValueError("message cannot be empty")
    return message
