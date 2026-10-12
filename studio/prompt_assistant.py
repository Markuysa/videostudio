"""Editable creative direction before the existing shot planner runs."""
import json

from .knowledge import DIRECTOR_RULES
from .llm import LLM, LLMError

FIELDS = ("subject", "setting", "action", "camera", "lighting", "sound", "continuity")


def suggest_direction(llm: LLM, body: dict, prefs: str = "") -> dict:
    if not isinstance(body, dict):
        raise ValueError("expected an object")
    request = body.get("request")
    if not isinstance(request, str) or not request.strip():
        raise ValueError("describe what we are shooting")
    if len(request) > 12000:
        raise ValueError("idea is too long (maximum 12000 characters)")
    context = {k: body[k] for k in ("request", "kind", "duration", "format", "language", "music",
                                   "captions", "loop", "notes", "direction", "series_bible") if k in body}
    system = DIRECTOR_RULES + """
You help a producer clarify an idea BEFORE a film is split into LTX-2.5 shots.
Return JSON with fields subject, setting, action, camera, lighting, sound, continuity
(each a concise string), assumptions (array of strings), questions (array of strings, at most 3).
Write in the language of the producer's request. The language setting is for dialogue only.
Respect existing notes and direction, explicit exclusions, music settings and loop requirements.
Preserve the story's scale and ending. Do not compress an entire film into one shot.
Describe achievable visible actions and coherent camera/light choices, avoiding decorative jargon.
Every invented detail must be listed in assumptions. For critical ambiguity, ask a question
and leave the affected detail unspecified. Do not invent dialogue unless requested.
This is an editable production brief, not the final English video prompt. No quality guarantees.
Standing preferences (lower priority than this request):
""" + prefs
    result = llm.complete_json(system, json.dumps(context, ensure_ascii=False), max_tokens=4000)
    if not isinstance(result, dict):
        raise LLMError("assistant returned an invalid brief")
    for key in FIELDS:
        if not isinstance(result.get(key), str) or len(result[key]) > 4000:
            raise LLMError(f"assistant returned an invalid {key}")
    for key in ("assumptions", "questions"):
        if not isinstance(result.get(key), list) or any(not isinstance(x, str) for x in result[key]):
            raise LLMError(f"assistant returned invalid {key}")
    return {key: result[key] for key in (*FIELDS, "assumptions", "questions")}
