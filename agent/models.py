#invoke model
import sys
from dotenv import load_dotenv
from langchain.chat_models import init_chat_model

load_dotenv()

# Initialize Groq using LangChain's unified interface
model = init_chat_model(
    model="openai/gpt-oss-120b",
    model_provider="groq",
    temperature=0.0
)

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    response = model.invoke("tell me something about the sun in 2 sentences")
    print(response.content)