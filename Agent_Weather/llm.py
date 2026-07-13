from langchain_google_genai import ChatGoogleGenerativeAI

from config import Settings, get_settings


def get_llm(settings: Settings | None = None) -> ChatGoogleGenerativeAI:
    """Create the Gemini model used as the agent brain."""

    settings = settings or get_settings()
    return ChatGoogleGenerativeAI(
        model=settings.gemini_model,
        google_api_key=settings.resolved_google_api_key,
        temperature=0.2,
    )
