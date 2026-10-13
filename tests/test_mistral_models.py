"""
Tests for the model constants and manifest (Mistral Large 4 + Voxtral 2 stack).

Verifie que la configuration pointe vers les bons modeles et que le manifest
exige le SDK mistralai compatible. Verifie aussi que chaque mot du vocabulaire
domotique respecte la contrainte context_bias de Voxtral 2 (un seul mot, sans
espace ni virgule — pattern ^[^,\\s]+$).
"""

import json
import re
from pathlib import Path

import pytest
import yaml

from custom_components.homestral import const

MANIFEST_PATH = Path(__file__).parent.parent / "custom_components" / "homestral" / "manifest.json"
CUSTOM_SENTENCES_DIR = Path(__file__).parent.parent / "custom_components" / "homestral" / "custom_sentences"

EXPECTED_CHAT_MODELS = {
    "mistral-large-latest",  # Mistral Large 4 (flagship)
    "mistral-large-4",  # Mistral Large 4 — pinned preview ID
    "mistral-medium-latest",  # Mistral Medium 3.5
    "mistral-small-latest",  # Mistral Small 4
}


def test_default_chat_model():
    assert const.DEFAULT_CHAT_MODEL == "mistral-large-latest"


def test_available_chat_models():
    """Les 4 modeles de chat selectables sont proposes."""
    assert len(const.AVAILABLE_CHAT_MODELS) == 4
    assert EXPECTED_CHAT_MODELS.issubset(set(const.AVAILABLE_CHAT_MODELS))
    assert const.DEFAULT_CHAT_MODEL in const.AVAILABLE_CHAT_MODELS


def test_default_stt_model():
    assert const.DEFAULT_STT_MODEL == "voxtral-mini-latest"


def test_default_tts_model():
    assert const.DEFAULT_TTS_MODEL == "voxtral-mini-tts-2603"


def test_manifest_requirements_and_version():
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert manifest["domain"] == "homestral"
    assert manifest["version"] == "0.2.1"
    assert "mistralai==3.2.0" in manifest["requirements"]


def test_home_automation_vocab_single_word_constraint():
    """Chaque entree du context_bias Voxtral 2 doit etre un seul mot."""
    pattern = re.compile(r"^[^,\s]+$")
    assert const.HOME_AUTOMATION_VOCAB, "HOME_AUTOMATION_VOCAB must not be empty"
    for word in const.HOME_AUTOMATION_VOCAB:
        assert isinstance(word, str)
        assert pattern.match(word), f"context_bias entry must be a single word (no space, no comma): {word!r}"


@pytest.mark.parametrize("lang", ["fr", "en"])
def test_custom_sentences_yaml_structure(lang):
    """Les custom sentences HomestralQuery sont valides (intents + wildcard).

    Fichiers à copier dans <config>/custom_sentences/<lang>/ pour activer la
    voix : intent HomestralQuery avec des phrases non vides qui capturent le
    slot wildcard {query}.
    """
    path = CUSTOM_SENTENCES_DIR / f"{lang}.yaml"
    assert path.is_file(), f"missing custom sentences file: {path}"

    data = yaml.safe_load(path.read_text(encoding="utf-8"))

    assert data["language"] == lang
    intent_data = data["intents"]["HomestralQuery"]["data"]
    assert isinstance(intent_data, list) and intent_data
    for entry in intent_data:
        assert isinstance(entry, dict)
        sentences = entry["sentences"]
        assert isinstance(sentences, list) and sentences
        for sentence in sentences:
            assert isinstance(sentence, str) and sentence
            assert "{query}" in sentence
    assert data["lists"]["query"]["wildcard"] is True


if __name__ == "__main__":
    pytest.main([__file__])
