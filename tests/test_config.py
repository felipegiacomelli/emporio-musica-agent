import pytest

from emporio.config import DATA_DIR, Settings


def test_settings_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.openai_model == "gpt-6.1-terra"
    assert s.reasoning_effort == "low"
    assert s.openai_api_key.get_secret_value() == "sk-test"


def test_data_dir_exists() -> None:
    assert (DATA_DIR / "políticas_da_loja.pdf").exists()
