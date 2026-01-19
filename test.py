# log_config.py
import logging
import sys
import structlog

def configure_logger():
    # 1. Configure Standard Library Logging (for 3rd party libs)
    # We want everything to go to stdout
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=logging.INFO,
    )

    # 2. Configure Structlog
    structlog.configure(
        processors=[
            # Add context vars (like request_id if using contextvars)
            structlog.contextvars.merge_contextvars,
            # Add log level
            structlog.processors.add_log_level,
            # Add timestamp (ISO format is best for Datadog)
            structlog.processors.TimeStamper(fmt="iso"),
            # If an exception was raised, format it nicely
            structlog.processors.format_exc_info,
            # Datadog prefers 'message' over 'event', so we rename it
            structlog.processors.EventRenamer("message"),
            # Render as JSON
            structlog.processors.JSONRenderer()
        ],
        # This connects structlog to the standard logging module
        logger_factory=structlog.stdlib.LoggerFactory(),
        # This wrapper ensures the standard library calls use the processors above
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )