"""Safe error text for logs and user-facing status messages."""


def error_name(error):
    if isinstance(error, BaseException):
        return type(error).__name__
    return "UnknownError"


def public_error_message(error, fallback):
    name = error_name(error)
    if getattr(error, "safe_for_user", False):
        message = str(error).strip()
        if message:
            return message
    return f"{fallback} ({name})"
