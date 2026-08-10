from nate_e2a.get_model import DEFAULT_VOICE, voice_base_url


def test_piper_voice_resolution():
    assert DEFAULT_VOICE == "en_GB-alan-medium"
    assert voice_base_url("en_US-joe-medium") == (
        "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/"
        "en/en_US/joe/medium/en_US-joe-medium"
    )
