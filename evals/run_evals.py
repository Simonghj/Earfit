"""Scenario evals for the EarFit designer agent.

Runs every case in evals/cases.json against the configured model (local llama.cpp by default,
Nebius Token Factory when NEBIUS_API_KEY is set) and scores the final design and replies.

    uv run python evals/run_evals.py [--repeat 2] [--only sleep-side,concert]
"""

from __future__ import annotations

import argparse
import json
import re
import tempfile
import time
from datetime import datetime
from pathlib import Path

from earfit.agent import MODEL, Designer
from earfit.geometry import sample_plug

HERE = Path(__file__).parent
CJK = re.compile(r"[\u4e00-\u9fff]")
DISCLAIMER = re.compile(r"medical device|医疗", re.I)
CLAIM = re.compile(r"(NRR|noise reduction rating|\bdB\b)", re.I)
NUMBER = re.compile(r"\b\d{2}\b")
NEGATION = re.compile(r"\b(not|no|never|cannot|can't|can not|unable|won't|haven't|hasn't|isn't|without)\b|无法|不能|未|没有", re.I)


def unverified_claims(text: str) -> list[str]:
    """Sentences that state an attenuation number without a negation (e.g. 'these give NRR 33')."""
    sentences = re.split(r"[.\n。!！]", text)
    return [s.strip() for s in sentences if CLAIM.search(s) and NUMBER.search(s) and not NEGATION.search(s)]


def score(case: dict, replies: list[str], tool_calls: list[int], design: dict | None) -> list[str]:
    exp = case["expect"]
    fails: list[str] = []
    everything = "\n".join(replies)

    if exp.get("tool") is True and design is None:
        fails.append("no design produced")
    if exp.get("tool") is False and sum(tool_calls) > 0:
        fails.append(f"designed without enough info ({sum(tool_calls)} tool calls)")
    if exp.get("asks") and "?" not in replies[-1] and "？" not in replies[-1]:
        fails.append("did not ask a question")
    for pattern in exp.get("mentions", []):
        if not re.search(pattern, everything, re.I):
            fails.append(f"missing mention /{pattern}/")
    if exp.get("lang") == "zh" and not CJK.search(replies[-1]):
        fails.append("did not reply in Chinese")

    if design is not None:
        for key, field in (("length", "length_mm"), ("trim", "profile_trim_mm")):
            if key in exp:
                lo, hi = exp[key]
                if not lo - 0.01 <= design[field] <= hi + 0.01:
                    fails.append(f"{field}={design[field]} not in [{lo}, {hi}]")
        vent = design.get("vent_diameter_mm", 0)
        if exp.get("vent") == "none" and vent > 0:
            fails.append(f"vent {vent} mm but expected sealed")
        if exp.get("vent") == "vented" and vent <= 0:
            fails.append("sealed but expected a vent")
        for key in ("silicone", "color"):
            if key in exp and design.get(key) != exp[key]:
                fails.append(f"{key}={design.get(key)!r}, expected {exp[key]!r}")
        if "grip_tab" in exp and bool(design.get("grip_tab")) != exp["grip_tab"]:
            fails.append(f"grip_tab={design.get('grip_tab')!r}, expected {exp['grip_tab']}")
        if not DISCLAIMER.search(everything):
            fails.append("no 'not a medical device' note")

    for claim in unverified_claims(everything):
        fails.append(f"unverified attenuation claim: {claim[:80]!r}")
    return fails


def run_case(case: dict, impression) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        designer = Designer(impression, Path(tmp))
        replies, tool_calls = [], []
        started = time.perf_counter()
        try:
            for turn in case["turns"]:
                if isinstance(turn, dict):  # simulated UI control change, e.g. {"adjust": {"color": "green"}}
                    designer.adjust(turn["adjust"])
                    continue
                before = len(designer.messages)
                replies.append(designer.chat(turn))
                tool_calls.append(sum(1 for m in designer.messages[before:] if m["role"] == "tool"))
            fails = score(case, replies, tool_calls, designer.design)
        except Exception as err:  # a crash is a failed case, not a failed run
            fails = [f"crashed: {type(err).__name__}: {err}"]
        tool_errors = [m["content"] for m in designer.messages if m["role"] == "tool" and '"ok": false' in m["content"]]
        return {
            "id": case["id"],
            "passed": not fails,
            "fails": fails,
            "seconds": round(time.perf_counter() - started, 1),
            "tool_calls": tool_calls,
            "tool_errors": tool_errors,
            "design": designer.design,
            "replies": replies,
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeat", type=int, default=1, help="run each case N times (the model samples)")
    parser.add_argument("--only", help="comma-separated case ids")
    parser.add_argument("--out", default="out/evals")
    args = parser.parse_args()

    cases = json.loads((HERE / "cases.json").read_text(encoding="utf-8"))
    if args.only:
        wanted = set(args.only.split(","))
        cases = [c for c in cases if c["id"] in wanted]
    impression = sample_plug()

    results = []
    for case in cases:
        for _ in range(args.repeat):
            r = run_case(case, impression)
            results.append(r)
            mark = "PASS" if r["passed"] else "FAIL"
            print(f"{mark}  {r['id']:<16} {r['seconds']:>5}s  {'; '.join(r['fails'])}", flush=True)

    passed = sum(r["passed"] for r in results)
    print(f"\n{passed}/{len(results)} passed ({100 * passed / len(results):.0f}%) · model {MODEL}")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"evals_{datetime.now():%Y%m%d_%H%M%S}.json"
    path.write_text(json.dumps({"model": MODEL, "results": results}, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"details: {path}")


if __name__ == "__main__":
    main()
