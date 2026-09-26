from contextvars import ContextVar
import re
from uuid import uuid4


request_id_var: ContextVar[str] = ContextVar("request_id", default="")
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def new_request_id() -> str:
    return str(uuid4())


def request_id_or_new(candidate: str | None) -> str:
    if candidate and _REQUEST_ID_PATTERN.fullmatch(candidate):
        return candidate
    return new_request_id()
