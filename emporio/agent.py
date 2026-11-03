"""Tool-calling loop on the OpenAI Responses API.

Fail closed: an API error, an empty answer or too many tool rounds give a
fixed message with the store's contact, never a guessed answer.
"""

from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import openai
from attrs import define, field, frozen

from emporio.data import Store
from emporio.prompt import build_instructions
from emporio.tools import TOOL_SCHEMAS, run_tool

type Clock = Callable[[], datetime]

TZ = ZoneInfo("America/Campo_Grande")
MAX_ROUNDS = 5
FALLBACK = (
    "Desculpe, não consegui responder agora. Fale com a nossa equipe pelo "
    "WhatsApp (67) 3341-4444 — segunda a sexta, das 9h às 18h, e sábado, "
    "das 9h às 13h."
)


def campo_grande_now() -> datetime:
    return datetime.now(TZ)


@frozen
class ToolCall:
    name: str
    arguments: str
    output: str


@frozen
class Turn:
    user: str
    reply: str
    tool_calls: tuple[ToolCall, ...]
    fallback: bool
    model: str | None


@define
class Agent:
    client: openai.OpenAI
    store: Store
    model: str
    reasoning_effort: str
    clock: Clock = campo_grande_now
    turns: list[Turn] = field(factory=list, init=False)
    _input: list[Any] = field(factory=list, init=False)

    def reply(self, user_text: str) -> Turn:
        before = list(self._input)
        self._input.append({"role": "user", "content": user_text})
        tool_calls: list[ToolCall] = []
        model: str | None = None
        text = ""
        try:
            for _ in range(MAX_ROUNDS):
                now = self.clock()
                response = self.client.responses.create(  # type: ignore[call-overload]
                    model=self.model,
                    instructions=build_instructions(now),
                    input=self._input,
                    tools=TOOL_SCHEMAS,
                    store=False,
                    include=["reasoning.encrypted_content"],
                    reasoning={"effort": self.reasoning_effort},
                )
                model = response.model
                if response.status == "incomplete":
                    break  # truncated answer: fall back instead of sending it
                self._input.extend(response.output)
                pending = [o for o in response.output if o.type == "function_call"]
                if not pending:
                    text = response.output_text.strip()
                    break
                for item in pending:
                    output = run_tool(self.store, item.name, item.arguments, now.date())
                    tool_calls.append(ToolCall(item.name, item.arguments, output))
                    self._input.append(
                        {
                            "type": "function_call_output",
                            "call_id": item.call_id,
                            "output": output,
                        }
                    )
        except openai.OpenAIError:
            text = ""
        if not text:
            # Roll back this turn's partial items so the next request is valid.
            self._input = [
                *before,
                {"role": "user", "content": user_text},
                {"role": "assistant", "content": FALLBACK},
            ]
        turn = Turn(user_text, text or FALLBACK, tuple(tool_calls), not text, model)
        self.turns.append(turn)
        return turn


def to_markdown(turns: Sequence[Turn], title: str) -> str:
    lines = [f"# {title}", ""]
    for turn in turns:
        lines += ["### Cliente", "", turn.user, "", "### Agente", ""]
        for c in turn.tool_calls:
            short = c.output if len(c.output) <= 300 else c.output[:300] + "…"
            lines += [
                f"<details><summary>🔧 {c.name}({c.arguments})</summary>",
                "",
                f"```json\n{short}\n```",
                "</details>",
                "",
            ]
        lines += [turn.reply, ""]
    return "\n".join(lines)
