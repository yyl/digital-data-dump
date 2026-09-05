"""Tests for token storage utility."""

from src.token_store import save_tokens_to_env


def test_save_tokens_to_env_creates_file_if_not_exists(tmp_path):
    env_file = tmp_path / ".env"
    save_tokens_to_env("TEST", "access_123", "refresh_456", env_path=env_file)

    assert env_file.exists()
    content = env_file.read_text()
    assert "TEST_ACCESS_TOKEN=access_123" in content
    assert "TEST_REFRESH_TOKEN=refresh_456" in content


def test_save_tokens_to_env_updates_existing_tokens(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "OTHER_VAR=hello\n"
        "TEST_ACCESS_TOKEN=old_acc\n"
        "TEST_REFRESH_TOKEN=old_ref\n"
        "ANOTHER_VAR=world\n"
    )

    save_tokens_to_env("TEST", "new_acc", "new_ref", env_path=env_file)

    content = env_file.read_text()
    assert "OTHER_VAR=hello\n" in content
    assert "ANOTHER_VAR=world\n" in content
    assert "TEST_ACCESS_TOKEN=new_acc\n" in content
    assert "TEST_REFRESH_TOKEN=new_ref\n" in content
    assert "old_acc" not in content
    assert "old_ref" not in content


def test_save_tokens_to_env_without_refresh_token(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("TEST_REFRESH_TOKEN=keep_this_ref\n")

    save_tokens_to_env("TEST", "new_acc", None, env_path=env_file)

    content = env_file.read_text()
    assert "TEST_ACCESS_TOKEN=new_acc\n" in content
    assert "TEST_REFRESH_TOKEN=keep_this_ref\n" in content
