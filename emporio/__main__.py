import argparse
import sys
from collections.abc import Callable
from pathlib import Path

import openai
from pydantic import ValidationError

from emporio.agent import Agent, to_markdown
from emporio.config import Settings
from emporio.data import load_store

TITLE = "Conversa com o assistente da Empório da Música"


def main(
    argv: list[str] | None = None,
    agent: Agent | None = None,
    input_fn: Callable[[str], str] = input,
) -> int:
    parser = argparse.ArgumentParser(prog="emporio")
    parser.add_argument("--transcript", type=Path)
    parser.add_argument("--model")
    args = parser.parse_args(argv)

    if agent is None:
        try:
            settings = Settings()
        except ValidationError as exc:
            for err in exc.errors():
                if err["loc"] == ("openai_api_key",) and err["type"] == "missing":
                    print(
                        "OPENAI_API_KEY não configurada. "
                        "Copie .env.example para .env e preencha a chave.",
                        file=sys.stderr,
                    )
                else:
                    field = ".".join(str(x) for x in err["loc"])
                    print(
                        f"Configuração inválida: {field}: {err['msg']}",
                        file=sys.stderr,
                    )
            return 2
        agent = Agent(
            client=openai.OpenAI(api_key=settings.openai_api_key.get_secret_value()),
            store=load_store(),
            model=args.model or settings.openai_model,
            reasoning_effort=settings.reasoning_effort,
        )

    print(
        "Empório da Música — assistente virtual. "
        "Digite sua mensagem (Ctrl-D para sair)."
    )
    try:
        while True:
            try:
                text = input_fn("Você: ").strip()
            except EOFError:
                break
            if text:
                print(f"Empório: {agent.reply(text).reply}")
    except KeyboardInterrupt:
        pass
    finally:
        if args.transcript:
            args.transcript.write_text(
                to_markdown(agent.turns, TITLE), encoding="utf-8"
            )
    print("\nAté mais! 🎸")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
