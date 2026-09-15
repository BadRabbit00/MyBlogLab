import logging
import sys

import pytest

from src.logger import ColoredFormatter, SecretRedactingFormatter


@pytest.mark.parametrize("formatter", [ColoredFormatter(), SecretRedactingFormatter()])
def test_token_redaction_covers_message_arguments_and_traceback(formatter):
    token = "123456:" + "a" * 35
    url = f"https://api.telegram.org/bot{token}/sendPhoto"
    try:
        raise RuntimeError(f"Request failed: {url}")
    except RuntimeError:
        record = logging.LogRecord("test", logging.ERROR, __file__, 1, "Failed: %s", (url,), sys.exc_info())
    output = formatter.format(record)
    assert token not in output
    assert "[REDACTED]" in output
