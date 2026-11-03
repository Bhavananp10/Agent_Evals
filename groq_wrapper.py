import os
from dotenv import load_dotenv
from langchain_groq import ChatGroq
from deepeval.models.base_model import DeepEvalBaseLLM

load_dotenv()

class GroqDeepEvalWrapper(DeepEvalBaseLLM):
    def __init__(self, model_name: str = "openai/gpt-oss-120b", temperature: float = 0.0):
        # Initialize your underlying Groq model via LangChain
        self.model = ChatGroq(
            model=model_name,
            temperature=temperature,
            api_key=os.environ.get("GROQ_API_KEY")
        )
        self.model_name = model_name

    def load_model(self):
        return self.model

    def generate(self, prompt: str) -> str:
        chat_model = self.load_model()
        response = chat_model.invoke(prompt)
        return response.content

    async def a_generate(self, prompt: str) -> str:
        chat_model = self.load_model()
        response = await chat_model.ainvoke(prompt)
        return response.content

    def get_model_name(self):
        return f"Groq ({self.model_name})"

# Instantiate a reusable evaluator object
groq_eval_model = GroqDeepEvalWrapper()