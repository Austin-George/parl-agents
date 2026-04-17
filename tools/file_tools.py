import os
from langchain_core.tools import tool

@tool
def write_file(path: str, content: str) -> str:
    """
    Writes content to a file at the given path.
    Creates any missing parent directories automatically.
    Use this to save documents, code files, or specifications.
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    return f"Successfully written to {path}"

@tool
def read_file(path: str) -> str:
    """
    Reads and returns the content of a file at the given path.
    Use this to read existing documents or code files.
    """
    if not os.path.exists(path):
        return f"Error: File not found at {path}"
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()

@tool
def list_files(directory: str) -> str:
    """
    Lists all files in a given directory.
    Use this to see what files already exist in a folder.
    """
    if not os.path.exists(directory):
        return f"Directory {directory} does not exist."
    files = []
    for root, dirs, filenames in os.walk(directory):
        for filename in filenames:
            filepath = os.path.join(root, filename)
            files.append(filepath)
    return "\n".join(files) if files else "No files found."