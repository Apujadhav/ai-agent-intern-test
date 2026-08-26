from app.agent import SupportAgent


def main():
    agent = SupportAgent()
    session_id = "cli-session"

    print("Aster & Row Support Agent")
    print("Type 'exit' to quit.")
    print()

    while True:
        message = input("You: ").strip()

        if message.lower() == "exit":
            break

        if not message:
            continue

        result = agent.handle(session_id, message)

        print()
        print("Assistant:")
        print(result["answer"])

        if result.get("sources"):
            print("\nSources:")
            for source in result["sources"]:
                print(
                    f"- {source['filename']} — "
                    f"{source['heading']}"
                )

        print(
            f"\nHuman handoff: "
            f"{'Yes' if result.get('handoff') else 'No'}"
        )
        print()


if __name__ == "__main__":
    main()