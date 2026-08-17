def normalize_recipient(recipient: str) -> str:
    value = recipient.strip()
    if not value:
        raise ValueError("recipient cannot be empty")
    return value.casefold()


def send_email(recipient: str, message: str) -> dict[str, str]:
    return {"channel": "email", "recipient": normalize_recipient(recipient), "message": message}
