import json
import random
import chainlit as cl
from datetime import datetime, timedelta
import uuid
from azure.core.credentials import AzureKeyCredential
from azure.identity import get_bearer_token_provider
from azure.search.documents import SearchClient
from openai import AzureOpenAI
import os
from datetime import datetime
import csv


rag_search_client = SearchClient(
    endpoint=os.environ["AZURE_SEARCH_ENDPOINT"],
    index_name=os.environ["POLICY_INDEX_NAME"],
    credential=AzureKeyCredential(os.environ["AZURE_SEARCH_KEY"]) 
)
fetch_relevant_documents_def = {
    "name": "fetch_relevant_documents",
    "description": "Fetch relevant documents for a query",
    "parameters": {
      "type": "object",
      "properties": {
        "query": {
          "type": "string",
          "description": "query for which documents are to be fetched"
        }
      },
      "required": ["query"]
    }
}

async def fetch_relevant_documents_handler(query: str):
    search_results = rag_search_client.search(
        search_text=query,
        top=5,
        select="content"
    )
    sources_formatted = "\n".join([f'{document["content"]}' for document in search_results])
    return sources_formatted


# get_current_time_def = {
#     "name": "get_current_time",
#     "description": "Get current time",
#     "parameters": {
#       "type": "object",
#       "properties": {
#         "query": {
#           "type": "string",
#           "description": "query to get the current time"
#         }
#       },
#       "required": ["query"]
#     }
# }

# async def get_current_time_handler(query: str):
#     current_time = datetime.now().strftime("%H:%M:%S")
#     return current_time


# structured_search_client = SearchClient(
#     endpoint=os.environ["AZURE_SEARCH_ENDPOINT"],
#     index_name=os.environ["LOAN_INDEX_NAME"],
#     credential=AzureKeyCredential(os.environ["AZURE_SEARCH_KEY"]) 
# )
# get_loan_information_def = {
#     "name": "get_loan_info",
#     "description": "get customer's loan information based on Agreement number or contact numner",
#     "parameters": {
#       "type": "object",
#       "properties": {
#         "query": {
#           "type": "string",
#           "description": "query for which loan information needs to be fetched"
#         }
#       },
#       "required": ["query"]
#     }
# }

# async def get_loan_information_handler(query: str):
#     # Search for loan information using either contact_number or agreement_number
#     search_results = structured_search_client.search(
#         search_text=query,
#         top=1,  # Get the top matching record
#         select= "agreement_number, customer_name, contact_number, emi_due, last_emi_due_date, last_emi_status, last_emi_paid_date, next_emi_due_date, outstanding_amount"
#     )

#     # Extract data from search results
#     loan_info = []
#     for document in search_results:
#         loan_info.append(
#             f"Agreement Number: {document.get('agreement_number', 'N/A')}\n"
#             f"Customer Name: {document.get('customer_name', 'N/A')}\n"
#             f"Contact Number: {document.get('contact_number', 'N/A')}\n"
#             f"EMI Due: {document.get('emi_due', 'N/A')}\n"
#             f"Last EMI Due Date: {document.get('last_emi_due_date', 'N/A')}\n"
#             f"Last EMI Status: {document.get('last_emi_status', 'N/A')}\n"
#             f"Last EMI Paid Date: {document.get('last_emi_paid_date', 'N/A')}\n"
#             f"Next EMI Due Date: {document.get('next_emi_due_date', 'N/A')}\n"
#             f"Outstanding Amount: {document.get('outstanding_amount', 'N/A')}\n"
#         )

#     # Return formatted loan information
#     return "\n\n".join(loan_info) if loan_info else "No records found."


search_data_def = {
    "name": "get_search_loan_details",
    "description": "get loan details based on contact number or agreement number",
    "parameters": {
      "type": "object",
      "properties": {
        "query": {
          "type": "string",
          "description": "query for fetching loan details"
        }
      },
      "required": ["query"]
    }
}
    
async def search_data_handler(query: str):
    """
    Searches for a record in the CSV file based on the provided key and value.
    :param file_path: Path to the CSV file.
    :param search_value: The value to search for in the key.
    :return: The matching record or a message if not found.
    """
    # print(query)
    try:
        file_path = 'loan_details.csv'
        with open(file_path, mode='r', encoding='utf-8-sig') as file:
            reader = csv.DictReader(file)
            for row in reader:
                # print(row)
                if row['contact_number'] == query:
                    print(row)
                    return row
                if row['agreement_number'] == query:
                    print(row)
                    return row               
            return f"No record found with {query}"
    except FileNotFoundError:
        return "File not found. Please check the file path."


# Tools list
tools = [
    (fetch_relevant_documents_def, fetch_relevant_documents_handler),
    # (get_current_time_def, get_current_time_handler),
    (search_data_def, search_data_handler)
]