"""Tests for the spoken-confirmation guard (safety.py)."""

from types import SimpleNamespace

import pytest

from custom_components.homestral.safety import CONFIRMATION_REQUIRED, guard, is_sensitive, was_confirmed


def _log(*messages):
    """A chat log whose assistant turns are the given texts, oldest first."""
    content = [SimpleNamespace(role="system", content="prompt")]
    for role, text in messages:
        content.append(SimpleNamespace(role=role, content=text))
    return SimpleNamespace(content=content)


@pytest.mark.parametrize(
    "tool,args,expected",
    [
        ("HassTurnOn", {"entity_id": "lock.porte"}, True),
        ("HassTurnOff", {"entity_id": "alarm_control_panel.maison"}, True),
        ("control_ha_device", {"entity_id": "cover.garage"}, True),
        ("HassTurnOn", {"entity_ids": ["light.salon", "lock.porte"]}, True),
        ("HassTurnOn", {"domain": "lock"}, True),
        ("HassTurnOn", {"entity_id": "light.salon"}, False),
        ("GetLiveContext", {"entity_id": "lock.porte"}, False),  # read-only tool
        ("HassClimateSetTemperature", {"entity_id": "lock.porte"}, False),
        ("HassTurnOn", "not a dict", False),
    ],
)
def test_is_sensitive(tool, args, expected):
    assert is_sensitive(tool, args) is expected


def test_was_confirmed_reads_the_last_assistant_turn():
    assert was_confirmed(_log(("assistant", "Dois-je vraiment ouvrir le garage ?"))) is True
    assert was_confirmed(_log(("assistant", "C'est fait."))) is False
    # The latest assistant turn wins over an older question
    assert was_confirmed(_log(("assistant", "Confirmer ?"), ("assistant", "Terminé."))) is False
    # A user turn between the two does not hide the question
    assert was_confirmed(_log(("assistant", "Ouvrir le garage ?"), ("user", "oui"))) is True
    assert was_confirmed(_log()) is False
    assert was_confirmed(SimpleNamespace(content=None)) is False


def test_guard_refuses_an_unconfirmed_sensitive_action():
    refusal = guard("HassTurnOn", {"entity_id": "lock.porte"}, _log(("assistant", "C'est fait.")), enabled=True)

    assert refusal == {"error": CONFIRMATION_REQUIRED}


def test_guard_allows_the_action_after_a_question():
    log = _log(("assistant", "Je déverrouille la porte d'entrée, vous confirmez ?"))

    assert guard("HassTurnOn", {"entity_id": "lock.porte"}, log, enabled=True) is None


def test_guard_is_inert_when_disabled_or_for_ordinary_actions():
    log = _log(("assistant", "C'est fait."))

    assert guard("HassTurnOn", {"entity_id": "lock.porte"}, log, enabled=False) is None
    assert guard("HassTurnOn", {"entity_id": "light.salon"}, log, enabled=True) is None
