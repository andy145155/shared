import logging
import json
import datetime
import sys

# 1. Define the Formatter (The logic we just discussed)
class JsonFormatter(logging.Formatter):
    def format(self, record):
        log_record = {
            "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "message": record.getMessage(),
            "logger": record.name
        }
        
        if record.exc_info:
            log_record["exception"] = self.formatException(record.exc_info)

        # Filter out standard attributes to capture 'extra' fields
        standard_attribs = {
            'args', 'asctime', 'created', 'exc_info', 'exc_text', 'filename',
            'funcName', 'levelname', 'levelno', 'lineno', 'module',
            'msecs', 'message', 'msg', 'name', 'pathname', 'process',
            'processName', 'relativeCreated', 'stack_info', 'thread', 'threadName'
        }

        for key, value in record.__dict__.items():
            if key not in standard_attribs:
                log_record[key] = value

        return json.dumps(log_record)

# 2. Define the Helper Function
def get_json_logger(name=__name__):
    """
    Returns a logger configured to output JSON to stdout.
    Safe to call multiple times; it won't add duplicate handlers.
    """
    logger = logging.getLogger(name)
    
    # Only add the handler if it doesn't already have one
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
        
        # Set default level (can be overridden by env vars if needed)
        logger.setLevel(logging.INFO)
        
        # Prevent propagation to root logger (avoids double logging if root is configured)
        logger.propagate = False
        
    return logger