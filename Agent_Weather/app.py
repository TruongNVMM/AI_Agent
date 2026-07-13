import argparse

from agent.assistant import WeatherAssistant


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AI Agent tra loi thoi tiet realtime.")
    parser.add_argument(
        "question",
        nargs="*",
        help="Cau hoi thoi tiet, vi du: Thoi tiet o Ha Noi hom nay the nao?",
    )
    parser.add_argument("--verbose", action="store_true", help="Hien log agent LangChain.")
    return parser


def run_once(question: str, verbose: bool = False) -> None:
    assistant = WeatherAssistant(verbose=verbose)
    answer = assistant.ask(question)
    print(answer.answer)


def run_chat(verbose: bool = False) -> None:
    assistant = WeatherAssistant(verbose=verbose)
    print("Weather AI Agent da san sang. Go 'exit' de thoat.")
    while True:
        try:
            question = input("\nBan: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nTam biet!")
            break

        if question.lower() in {"exit", "quit", "q"}:
            print("Tam biet!")
            break

        if not question:
            continue

        answer = assistant.ask(question)
        print(f"Agent: {answer.answer}")


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    question = " ".join(args.question).strip()
    if question:
        run_once(question, verbose=args.verbose)
    else:
        run_chat(verbose=args.verbose)


if __name__ == "__main__":
    main()
