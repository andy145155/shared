import logging
import structlog
import sys

def setup_logging():
    # 1. Create the specific handlers for your files
    
    # Handler for ALL logs
    file_handler_all = logging.FileHandler("all.json")
    file_handler_all.setLevel(logging.INFO)
    
    # Handler for ERROR logs only
    file_handler_error = logging.FileHandler("errors.json")
    file_handler_error.setLevel(logging.ERROR)
    # Optional: Add the specific filter if setLevel isn't strict enough for your needs
    # file_handler_error.addFilter(ErrorFilter()) 

    # 2. Configure the Standard Library Logger
    # We need a formatter that just passes the message through, 
    # because structlog will have already converted it to JSON.
    logging.basicConfig(
        format="%(message)s",
        level=logging.INFO,
        handlers=[
            logging.StreamHandler(sys.stdout), # Keep logging to console
            file_handler_all,
            file_handler_error
        ]
    )

    # 3. Configure Structlog to wrap Standard Logging
    structlog.configure(
        processors=[
            # Merge context vars (thread local storage)
            structlog.contextvars.merge_contextvars,
            # Add log level and timestamp
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            # If an exception is present, format it nicely
            structlog.processors.format_exc_info,
            # Render the final event as a JSON string
            structlog.processors.JSONRenderer()
        ],
        # This tells structlog: "After processing, pass the result to logging.getLogger()"
        logger_factory=structlog.stdlib.LoggerFactory(),
        # This tells structlog: "Use the standard library's log methods (info, error, etc.)"
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

# Run the setup
setup_logging()