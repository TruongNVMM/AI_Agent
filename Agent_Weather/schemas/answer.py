from pydantic import BaseModel, Field


class AgentAnswer(BaseModel):
    """Structured response returned by the assistant wrapper."""

    question: str = Field(description="Original user question.")
    answer: str = Field(description="Natural-language answer from the AI agent.")
