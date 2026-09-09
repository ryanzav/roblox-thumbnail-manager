from src.config import load_config


def test_empty_actions_variables_fall_back_to_defaults(monkeypatch):
    # GitHub Actions passes an unset `vars.X` through as an empty string.
    monkeypatch.setenv("SMTP_HOST", "")
    monkeypatch.setenv("SMTP_PORT", "")
    cfg = load_config()
    assert cfg.smtp_host == "smtp.gmail.com"
    assert cfg.smtp_port == 587


def test_explicit_smtp_settings_are_used(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_PORT", "2525")
    cfg = load_config()
    assert cfg.smtp_host == "smtp.example.com"
    assert cfg.smtp_port == 2525
