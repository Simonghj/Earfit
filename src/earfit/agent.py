"""Nemotron earplug designer: chats with the user and calls the geometry pipeline as a tool."""

from __future__ import annotations

import json
import os
from pathlib import Path

import trimesh
from openai import OpenAI

from earfit.geometry import customize_plug, make_mold

TOKEN_FACTORY_URL = "https://api.tokenfactory.nebius.com/v1/"
LOCAL_URL = "http://127.0.0.1:8080/v1"
MODEL = os.environ.get("EARFIT_MODEL", "nvidia/Nemotron-3_5-Lightning")

SYSTEM_PROMPT = """You are EarFit, an earplug designer. The user has a 3D scan of their own ear impression.
You shape it into a custom silicone earplug by calling design_earplug.

How to choose parameters:
- length_mm: shorter (10-14) for sleeping and comfort, longer (16-22) for loud environments and a deeper seal.
  Never exceed the max_length_mm reported by the tool.
- profile_trim_mm: 2-3 for side sleepers so nothing presses against the pillow; 0-1 otherwise.
- vent_diameter_mm: 0 for maximum blocking (sleep, shooting, power tools); 1.0-1.5 to hear speech and
  reduce pressure (concerts, office, flying, musicians).
- silicone: "Ecoflex 00-30" (very soft, sleep and all-day comfort) or "Dragon Skin 10" (firmer, durable, sports).

Rules:
- If you do not know what the earplugs are for, ask one short question first. Otherwise design right away.
- If the tool returns an error, adjust the parameters and call it again.
- After a successful design, explain your choices in at most 5 short bullets, using the measured numbers.
- Never claim a noise reduction rating (NRR); it has not been measured. Remind the user it is not a medical device.
"""

DESIGN_TOOL = {
    "type": "function",
    "function": {
        "name": "design_earplug",
        "description": "Shape the user's ear impression into an earplug and generate a two-part pour mold.",
        "parameters": {
            "type": "object",
            "properties": {
                "use_case": {"type": "string", "description": "What the earplugs are for, in a few words."},
                "length_mm": {"type": "number", "minimum": 8, "maximum": 30},
                "profile_trim_mm": {"type": "number", "minimum": 0, "maximum": 4},
                "vent_diameter_mm": {"type": "number", "minimum": 0, "maximum": 2},
                "silicone": {"type": "string", "enum": ["Ecoflex 00-30", "Dragon Skin 10"]},
            },
            "required": ["use_case", "length_mm", "profile_trim_mm", "vent_diameter_mm", "silicone"],
        },
    },
}


def make_client() -> OpenAI:
    """Nebius Token Factory when NEBIUS_API_KEY is set, otherwise the local llama.cpp server."""
    key = os.environ.get("NEBIUS_API_KEY")
    if key:
        return OpenAI(api_key=key, base_url=os.environ.get("EARFIT_BASE_URL", TOKEN_FACTORY_URL))
    return OpenAI(api_key="local", base_url=os.environ.get("EARFIT_BASE_URL", LOCAL_URL))


class Designer:
    def __init__(self, impression: trimesh.Trimesh, out_dir: Path, client: OpenAI | None = None):
        self.impression = impression
        self.out_dir = out_dir
        self.client = client or make_client()
        self.messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
        self.design: dict | None = None

    def _design_earplug(self, args: dict) -> dict:
        try:
            plug, report = customize_plug(
                self.impression, args["length_mm"], args["profile_trim_mm"], args["vent_diameter_mm"]
            )
            mold_a, mold_b = make_mold(plug)
        except (ValueError, KeyError) as err:
            return {"ok": False, "error": str(err)}
        self.out_dir.mkdir(parents=True, exist_ok=True)
        for name, mesh in (("plug", plug), ("mold_a", mold_a), ("mold_b", mold_b)):
            mesh.export(self.out_dir / f"{name}.stl")
        self.design = {**args, **report}
        return {"ok": True, **report}

    def chat(self, user_text: str, max_steps: int = 4) -> str:
        """Run one user turn through the model, executing tool calls until it answers in text."""
        self.messages.append({"role": "user", "content": user_text})
        for _ in range(max_steps):
            reply = self.client.chat.completions.create(
                model=MODEL, messages=self.messages, tools=[DESIGN_TOOL], temperature=0.6
            ).choices[0].message
            if not reply.tool_calls:
                self.messages.append({"role": "assistant", "content": reply.content or ""})
                return reply.content or ""
            self.messages.append(
                {
                    "role": "assistant",
                    "content": reply.content or "",
                    "tool_calls": [c.model_dump(include={"id", "type", "function"}) for c in reply.tool_calls],
                }
            )
            for call in reply.tool_calls:
                try:
                    result = self._design_earplug(json.loads(call.function.arguments))
                except json.JSONDecodeError as err:
                    result = {"ok": False, "error": f"arguments were not valid JSON: {err}"}
                self.messages.append({"role": "tool", "tool_call_id": call.id, "content": json.dumps(result)})
        raise RuntimeError(f"model did not finish within {max_steps} steps")
