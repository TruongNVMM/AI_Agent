from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from llm import get_llm
from prompts.system_prompt import SYSTEM_PROMPT
from schemas.answer import AgentAnswer
from tools.weather import get_realtime_weather


class WeatherAssistant:
    """LangChain agent that uses Gemini 2.5 Flash and realtime weather tools."""

    def __init__(self, verbose: bool = False) -> None:
        self.tools = [get_realtime_weather]
        self.llm = get_llm()
        self.prompt = ChatPromptTemplate.from_messages(
            [
                ("system", SYSTEM_PROMPT),
                MessagesPlaceholder(variable_name="chat_history", optional=True),
                ("human", "{input}"),
                MessagesPlaceholder(variable_name="agent_scratchpad"),
            ]
        )
        agent = create_tool_calling_agent(self.llm, self.tools, self.prompt)
        self.executor = AgentExecutor(
            agent=agent,
            tools=self.tools,
            verbose=verbose,
            max_iterations=6,
            handle_parsing_errors=True,
        )

    def ask(self, question: str) -> AgentAnswer:
        result = self.executor.invoke({"input": question, "chat_history": []})
        return AgentAnswer(question=question, answer=str(result["output"]))
