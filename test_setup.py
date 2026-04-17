from dotenv import load_dotenv
load_dotenv()

from langchain_ollama import OllamaLLM

llm = OllamaLLM(model="llama3")
response = llm.invoke("Say hello in one sentence.")
print("LLM Response:", response)
print("Setup complete!")