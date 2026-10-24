"""Tests for the calendar event tool.

Home Assistant's Assist API can read calendars but not write to them, so HomeStral
ships its own `create_calendar_event`. These tests pin the date handling, the target
selection and the refusals the model is meant to read and act on.
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.homestral.const import TOOL_CREATE_CALENDAR_EVENT
from custom_components.homestral.tools import HAToolExecutor


def _executor(*calendars):
    """An executor whose hass exposes the given (entity_id, supported_features) calendars."""
    hass = MagicMock()
    states = []
    for entity_id, features in calendars:
        state = MagicMock()
        state.entity_id = entity_id
        state.attributes = {"supported_features": features}
        states.append(state)
    hass.states.async_all.return_value = states
    hass.states.get.side_effect = lambda eid: next((s for s in states if s.entity_id == eid), None)
    hass.services.async_call = AsyncMock()
    return HAToolExecutor(hass)


async def _run(executor, **arguments):
    return json.loads(await executor.execute(TOOL_CREATE_CALENDAR_EVENT, arguments))


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_creates_a_timed_event_on_the_only_calendar():
    """The scenario that prompted this tool: a one-hour appointment."""
    executor = _executor(("calendar.perso", 1))

    result = await _run(
        executor,
        summary="Signature logement",
        start_date_time="2026-11-05T14:00:00",
        duration_minutes=60,
    )

    assert result["success"] is True
    domain, service, data = executor.hass.services.async_call.call_args.args[:3]
    assert (domain, service) == ("calendar", "create_event")
    assert data == {
        "entity_id": "calendar.perso",
        "summary": "Signature logement",
        "start_date_time": "2026-11-05T14:00:00",
        "end_date_time": "2026-11-05T15:00:00",
    }
    assert executor.hass.services.async_call.call_args.kwargs["blocking"] is True


@pytest.mark.asyncio
async def test_explicit_end_time_wins_over_the_duration():
    executor = _executor(("calendar.perso", 1))

    await _run(
        executor,
        summary="Réunion",
        start_date_time="2026-11-05T09:00:00",
        end_date_time="2026-11-05T11:30:00",
        duration_minutes=15,
    )

    data = executor.hass.services.async_call.call_args.args[2]
    assert data["end_date_time"] == "2026-11-05T11:30:00"


@pytest.mark.asyncio
async def test_duration_defaults_to_one_hour():
    executor = _executor(("calendar.perso", 1))

    await _run(executor, summary="Déjeuner", start_date_time="2026-11-05T12:00:00")

    assert executor.hass.services.async_call.call_args.args[2]["end_date_time"] == "2026-11-05T13:00:00"


@pytest.mark.asyncio
async def test_all_day_event_ends_the_following_day():
    """The service treats end_date as exclusive, so a single day spans to the next."""
    executor = _executor(("calendar.perso", 1))

    await _run(executor, summary="Congés", start_date="2026-11-05")

    data = executor.hass.services.async_call.call_args.args[2]
    assert data == {
        "entity_id": "calendar.perso",
        "summary": "Congés",
        "start_date": "2026-11-05",
        "end_date": "2026-11-06",
    }


@pytest.mark.asyncio
async def test_description_and_location_are_passed_through():
    executor = _executor(("calendar.perso", 1))

    await _run(
        executor,
        summary="Notaire",
        start_date_time="2026-11-05T14:00:00",
        description="Apporter les justificatifs",
        location="12 rue des Lilas",
    )

    data = executor.hass.services.async_call.call_args.args[2]
    assert data["description"] == "Apporter les justificatifs"
    assert data["location"] == "12 rue des Lilas"


# ---------------------------------------------------------------------------
# Refusals the model has to read
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_refuses_without_a_writable_calendar():
    executor = _executor(("calendar.jours_feries", 0))

    result = await _run(executor, summary="Test", start_date_time="2026-11-05T14:00:00")

    assert "Agenda local" in result["error"]
    executor.hass.services.async_call.assert_not_called()


@pytest.mark.asyncio
async def test_refuses_a_read_only_calendar_by_name():
    executor = _executor(("calendar.perso", 1), ("calendar.jours_feries", 0))

    result = await _run(
        executor, summary="Test", start_date_time="2026-11-05T14:00:00", entity_id="calendar.jours_feries"
    )

    assert "lecture seule" in result["error"]
    executor.hass.services.async_call.assert_not_called()


@pytest.mark.asyncio
async def test_reports_an_unknown_calendar_with_the_available_ones():
    executor = _executor(("calendar.perso", 1))

    result = await _run(executor, summary="Test", start_date_time="2026-11-05T14:00:00", entity_id="calendar.absent")

    assert "n'existe pas" in result["error"]
    assert "calendar.perso" in result["error"]


@pytest.mark.asyncio
async def test_asks_which_calendar_when_several_are_writable():
    executor = _executor(("calendar.perso", 1), ("calendar.famille", 1))

    result = await _run(executor, summary="Test", start_date_time="2026-11-05T14:00:00")

    assert "précise lequel" in result["error"]
    executor.hass.services.async_call.assert_not_called()


@pytest.mark.asyncio
async def test_targets_the_named_calendar_when_several_exist():
    executor = _executor(("calendar.perso", 1), ("calendar.famille", 1))

    await _run(executor, summary="Test", start_date_time="2026-11-05T14:00:00", entity_id="calendar.famille")

    assert executor.hass.services.async_call.call_args.args[2]["entity_id"] == "calendar.famille"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "arguments,expected",
    [
        ({"summary": "", "start_date_time": "2026-11-05T14:00:00"}, "titre"),
        ({"summary": "Test"}, "date de début"),
        (
            {"summary": "Test", "start_date_time": "2026-11-05T14:00:00", "end_date_time": "2026-11-05T13:00:00"},
            "après",
        ),
    ],
)
async def test_rejects_incoherent_requests(arguments, expected):
    executor = _executor(("calendar.perso", 1))

    result = await _run(executor, **arguments)

    assert expected in result["error"]
    executor.hass.services.async_call.assert_not_called()


@pytest.mark.asyncio
async def test_a_service_failure_is_reported_not_raised():
    executor = _executor(("calendar.perso", 1))
    executor.hass.services.async_call = AsyncMock(side_effect=RuntimeError("calendar unavailable"))

    result = await _run(executor, summary="Test", start_date_time="2026-11-05T14:00:00")

    assert "error" in result


def test_writable_calendars_filters_on_the_create_feature():
    executor = _executor(("calendar.perso", 1), ("calendar.lecture", 0), ("calendar.complet", 7))

    assert executor.writable_calendars() == ["calendar.perso", "calendar.complet"]
