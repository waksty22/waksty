"""All JSON-object API routes reject malformed and non-object request bodies."""
import asyncio
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import server


class JsonRequest:
    def __init__(self, payload=None, error=None):
        self.payload = payload
        self.error = error

    async def json(self):
        if self.error is not None:
            raise self.error
        return self.payload


BODY_ROUTES = [
    "api_record_skill_assessment",
    "api_record_decision",
    "api_evaluate_decision",
    "api_record_preference",
    "api_vision_analyze",
    "api_associate_visual_word",
    "api_teach_object_property",
    "api_record_object_experience",
    "api_compare_known_objects",
    "api_record_personal_goal_step",
    "api_record_causal_observation",
    "api_propose_causal_hypothesis",
    "api_plan_causal_experiment",
    "api_evaluate_causal_experiment",
    "api_record_imitation_demonstration",
    "api_record_imitation_practice",
    "api_validate_imitation",
    "api_reject_imitation",
]


def call_route(name, request):
    route = getattr(server, name)
    if name == "api_evaluate_decision":
        return asyncio.run(route(1, request, auth="creator"))
    if name in {
        "api_evaluate_causal_experiment",
        "api_record_imitation_practice",
        "api_validate_imitation",
        "api_reject_imitation",
    }:
        return asyncio.run(route(1, request, auth="creator"))
    return asyncio.run(route(request, auth="creator"))


@pytest.fixture
def no_storage(monkeypatch):
    def unexpected_storage():
        raise AssertionError("Invalid JSON must be rejected before database access")
    monkeypatch.setattr(server, "db_connection", unexpected_storage)


@pytest.mark.parametrize("route_name", BODY_ROUTES)
@pytest.mark.parametrize("payload", [None, [], "text", 7, True])
def test_json_body_routes_reject_non_object_payloads_before_storage(
    no_storage, route_name, payload
):
    with pytest.raises(HTTPException) as error:
        call_route(route_name, JsonRequest(payload))
    assert error.value.status_code == 422


@pytest.mark.parametrize("route_name", BODY_ROUTES)
@pytest.mark.parametrize("parse_error", [ValueError("bad JSON"), TypeError("bad body")])
def test_json_body_routes_reject_malformed_payloads_with_422(
    no_storage, route_name, parse_error
):
    with pytest.raises(HTTPException) as error:
        call_route(route_name, JsonRequest(error=parse_error))
    assert error.value.status_code == 422
