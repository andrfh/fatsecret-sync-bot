"""Application logs contain metadata only, including third-party failures."""
import logging

_EXTERNAL_LOGGERS = ("google.", "httpx", "httpcore", "requests", "urllib3",
                     "oauthlib", "requests_oauthlib", "telegram", "asyncio")
_configured = False
_original_factory = logging.getLogRecordFactory()


def _redact(record):
    if record.name.startswith(_EXTERNAL_LOGGERS):
        record.msg = "External library event (details omitted)"
        record.args = ()
        record.exc_info = None
        record.exc_text = None
        record.stack_info = None
    return record


class MetadataOnlyFilter(logging.Filter):
    def filter(self, record):
        _redact(record)
        return True


def configure_safe_logging():
    global _configured
    if not _configured:
        def safe_record_factory(*args, **kwargs):
            return _redact(_original_factory(*args, **kwargs))
        logging.setLogRecordFactory(safe_record_factory)
        _configured = True
    root = logging.getLogger()
    if not root.handlers:
        root.addHandler(logging.StreamHandler())
    for handler in root.handlers:
        handler.addFilter(MetadataOnlyFilter())
