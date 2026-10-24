"""
Tests for the model constants and manifest (Mistral Small 4 / Large 4 + Voxtral 3 stack).

Verifie que la configuration pointe vers les identifiants Voxtral 3 documentes,
que le manifest exige le SDK mistralai avec l'extra realtime, que la table des
voix TTS est coherente et que le vocabulaire context_bias reste propre
(phrases multi-mots autorisees avec Voxtral 3, mais sans virgule).
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
    "mistral-small-latest",  # Mistral Small 4 (voice default)
    "mistral-large-latest",  # Mistral Large 4 (flagship)
    "mistral-medium-latest",  # Mistral Medium 3.5
}


def test_default_chat_model():
    assert const.DEFAULT_CHAT_MODEL == "mistral-small-latest"


def test_available_chat_models():
    """Les 3 alias de chat selectables sont proposes, sans id non documente."""
    assert set(const.AVAILABLE_CHAT_MODELS) == EXPECTED_CHAT_MODELS
    assert len(const.AVAILABLE_CHAT_MODELS) == len(EXPECTED_CHAT_MODELS)
    assert const.DEFAULT_CHAT_MODEL in const.AVAILABLE_CHAT_MODELS


def test_legacy_chat_model_aliases_resolve_to_available_models():
    for legacy, current in const.LEGACY_CHAT_MODEL_ALIASES.items():
        assert legacy not in const.AVAILABLE_CHAT_MODELS
        assert current in const.AVAILABLE_CHAT_MODELS
    assert const.resolve_chat_model("mistral-large-4") == "mistral-large-latest"
    assert const.resolve_chat_model("mistral-large-latest") == "mistral-large-latest"
    assert const.resolve_chat_model("unknown-model") == const.DEFAULT_CHAT_MODEL
    assert const.resolve_chat_model(None) == const.DEFAULT_CHAT_MODEL


def test_stt_models_are_voxtral3():
    assert const.DEFAULT_STT_MODEL == const.STT_MODEL_BATCH_MINI == "voxtral-mini-transcribe-3-0"
    assert const.STT_MODEL_BATCH_SMALL == "voxtral-small-transcribe-3-0"
    assert const.STT_MODEL_REALTIME == "voxtral-mini-transcribe-realtime-3-0"
    assert const.STT_MODEL_CHAT_FALLBACK == "voxtral-small-latest"


def test_default_tts_model_and_format():
    assert const.DEFAULT_TTS_MODEL == "voxtral-mini-tts-3-0"
    assert const.DEFAULT_TTS_FORMAT in {"mp3", "wav", "pcm", "flac", "opus"}


def test_tts_voices_table():
    """Chaque langue a au moins une voix preset Voxtral 3, ids uniques."""
    assert const.DEFAULT_TTS_LANGUAGE in const.TTS_VOICES
    seen: set[str] = set()
    for language, voices in const.TTS_VOICES.items():
        assert re.fullmatch(r"[a-z]{2}", language), language
        assert voices, f"no voice for {language}"
        for voice_id, name in voices:
            assert re.fullmatch(r"voice_\d+", voice_id), voice_id
            assert name and name == name.strip()
            assert voice_id not in seen, f"duplicate voice id {voice_id}"
            seen.add(voice_id)


def test_manifest_requirements_and_version():
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert manifest["domain"] == "homestral"
    assert manifest["version"] == "0.6.1"
    # The realtime extra brings websockets, sentence-stream splits the streamed answer into
    # sentences; pydub is gone (raw PCM goes straight to the API).
    assert manifest["requirements"] == ["mistralai[realtime]==3.3.0", "sentence-stream>=1.3.0"]


def test_tts_delivery_tag_values():
    """Emotion and pace values must match the documented Voxtral TTS 3 lists."""
    assert len(const.TTS_EMOTIONS) == 34
    assert const.TTS_PACES == ["very-slow", "slow", "moderate", "fast", "very-fast"]
    assert const.TTS_NONE not in const.TTS_EMOTIONS and const.TTS_NONE not in const.TTS_PACES
    for value in (*const.TTS_EMOTIONS, *const.TTS_PACES):
        assert value == value.strip().lower()
    assert len(set(const.TTS_EMOTIONS)) == len(const.TTS_EMOTIONS)
    # Fallback parameters only: the streamed container declares the real ones.
    assert (const.TTS_SAMPLE_RATE, const.TTS_SAMPLE_WIDTH, const.TTS_CHANNELS) == (24000, 2, 1)
    # Measured 2026-10-24: "pcm" returns 32-bit floats, which played as 16-bit integers is
    # noise. "wav" carries a header, so the stream describes itself.
    assert const.TTS_STREAM_FORMAT == "wav"


def test_home_automation_vocab_entries_are_clean():
    """Entrees context_bias non vides, sans virgule, sans espace parasite, uniques."""
    assert const.HOME_AUTOMATION_VOCAB, "HOME_AUTOMATION_VOCAB must not be empty"
    lowered = [entry.lower() for entry in const.HOME_AUTOMATION_VOCAB]
    assert len(lowered) == len(set(lowered)), "duplicate vocabulary entries"
    for entry in const.HOME_AUTOMATION_VOCAB:
        assert isinstance(entry, str)
        assert entry and entry == entry.strip(), repr(entry)
        assert "," not in entry, f"context_bias entry must not contain a comma: {entry!r}"


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
