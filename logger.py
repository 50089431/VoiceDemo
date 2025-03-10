import logging
import os

# Create a logs directory if it doesn't exist
log_dir = os.path.join(os.path.dirname(__file__), 'logs')
if not os.path.exists(log_dir):
    os.makedirs(log_dir)

# Configure logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)  # Set logger level

# File handler
file_handler = logging.FileHandler(os.path.join(log_dir, "app.log"))
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))

# Stream handler (console)
# stream_handler = logging.StreamHandler()
# stream_handler.setLevel(logging.INFO)
# stream_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))

# Add handlers to the logger
logger.addHandler(file_handler)
# logger.addHandler(stream_handler)

def log_llm_input_output(model_name, input_data, output_data):
    logger.info(f"Model: {model_name} - Input: {input_data} - Output: {output_data}")

def log_query_search(query):
    logger.info(f"RAG Searched: {query}")

def log_tool_search(tool_name, parameters):
    logger.info(f"Tool: {tool_name} - Parameters: {parameters}")
