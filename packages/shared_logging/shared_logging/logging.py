import logging
import os
import sys

from python_json_logger import jsonlogger


class DialogflowContextFilter(logging.Filter):
    """
    A logging filter that injects Dialogflow context into log records.
    This allows for powerful filtering and tracing in Google Cloud Logging.
    """

    def __init__(
        self,
        session_id=None,
        project_id=None,
        agent_id=None,
        flow_id=None,
        page_id=None,
        intent_id=None,
    ):
        super().__init__()
        self.context = {
            "session_id": session_id,
            "project_id": project_id,
            "agent_id": agent_id,
            "flow_id": flow_id,
            "page_id": page_id,
            "intent_id": intent_id,
        }

    def filter(self, record):
        # Attach all context fields to the log record object
        record.dialogflow_context = self.context
        return True


class CustomJsonFormatter(jsonlogger.JsonFormatter):
    """
    Custom formatter to define the structure of the JSON log output.
    It maps standard log record attributes to a 'json_fields' dictionary.
    """

    def add_fields(self, log_record, record, message_dict):
        super().add_fields(log_record, record, message_dict)

        # Rename standard fields to be consistent with Google Cloud Logging
        log_record["timestamp"] = log_record.pop("asctime", record.created)
        log_record["severity"] = log_record.pop("levelname", "INFO").upper()
        log_record["name"] = log_record.pop("name", record.name)

        # Add the Dialogflow context if it exists on the record
        if hasattr(record, "dialogflow_context"):
            log_record.update(record.dialogflow_context)


def get_logger(name: str, webhook_request: dict = None):
    """
    The main factory function for creating a pre-configured logger.

    Args:
        name (str): The name of the logger, typically __name__ of the calling module.
        webhook_request (dict, optional): The full Dialogflow webhook request dictionary.
                                         If provided, context is automatically extracted.

    Returns:
        logging.Logger: A logger instance configured for structured JSON logging.
    """
    log_level_str = os.environ.get("LOG_LEVEL", "INFO").upper()
    log_level = getattr(logging, log_level_str, logging.INFO)

    logger = logging.getLogger(name)
    logger.setLevel(log_level)
    logger.propagate = False  # Prevent logs from propagating to the root logger

    # Prevent adding handlers multiple times in environments like Cloud Functions
    if logger.hasHandlers():
        return logger

    # --- Extract Context from Webhook Request ---
    session_id, project_id, agent_id, flow_id, page_id, intent_id = (None,) * 6
    if webhook_request:
        session_path = webhook_request.get("sessionInfo", {}).get("session", "")
        # Expected format: projects/<ProjectID>/locations/<LocationID>/agents/<AgentID>/sessions/<SessionID>
        # Or: projects/<ProjectID>/locations/<LocationID>/agents/<AgentID>/environments/<EnvironmentID>/sessions/<SessionID>
        parts = session_path.split("/")
        if len(parts) >= 6:
            project_id = parts[1]
            agent_id = parts[3]
            session_id = parts[-1]

        flow_id = webhook_request.get("sessionInfo", {}).get("parameters", {}).get(
            "flow-id"
        ) or webhook_request.get("flowInfo", {}).get("displayName")

        page_id = webhook_request.get("sessionInfo", {}).get("parameters", {}).get(
            "page-id"
        ) or webhook_request.get("pageInfo", {}).get("displayName")

        intent_id = webhook_request.get("intentInfo", {}).get("displayName")

    # --- Create Filter and Formatter ---
    context_filter = DialogflowContextFilter(
        session_id=session_id,
        project_id=project_id,
        agent_id=agent_id,
        flow_id=flow_id,
        page_id=page_id,
        intent_id=intent_id,
    )

    # Define the fields that will appear in the JSON output
    formatter = CustomJsonFormatter(
        "%(asctime)s %(name)s %(levelname)s %(message)s",
        rename_fields={"levelname": "severity", "asctime": "timestamp"},
    )

    # --- Create Handler and attach everything ---
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    logger.addHandler(handler)
    logger.addFilter(context_filter)

    return logger


# --- Example Usage (for demonstration and testing) ---
if __name__ == "__main__":
    # Mock a Dialogflow Webhook Request
    mock_request = {
        "sessionInfo": {
            "session": "projects/telecom-project-123/locations/global/agents/agent-abc-456/sessions/session-xyz-789",
            "parameters": {"flow-id": "tech_support", "page-id": "internet_issues"},
        },
        "intentInfo": {"displayName": "report.internet.slow"},
        "text": "my internet is super slow today",
    }

    # In a real service, this would be the only line you need
    logger = get_logger(__name__, webhook_request=mock_request)

    logger.debug("This is a debug message. It won't show if LOG_LEVEL is INFO.")
    logger.info(
        "Starting internet speed diagnosis.", extra={"customer_id": "CUST-55443"}
    )
    logger.warning("Upstream API latency is high: 1200ms.")
    logger.error("Failed to retrieve account details.")

    try:
        result = 1 / 0
    except ZeroDivisionError:
        logger.exception("A critical calculation error occurred.")
