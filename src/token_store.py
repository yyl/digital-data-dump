"""OAuth token persistence utilities."""

import os
from pathlib import Path
from typing import Optional

from .config import Config


def save_tokens_to_env(
    prefix: str,
    access_token: str,
    refresh_token: Optional[str] = None,
    env_path: Optional[Path] = None,
) -> None:
    """Persist OAuth access and refresh tokens into .env.

    Args:
        prefix: Prefix for environment variables (e.g., 'OURA', 'SCHWAB').
        access_token: The OAuth access token string.
        refresh_token: The OAuth refresh token string, if available.
        env_path: Optional custom path to .env (defaults to Config.PROJECT_ROOT / ".env").
    """
    if env_path is None:
        env_path = Config.PROJECT_ROOT / ".env"

    access_key = f"{prefix}_ACCESS_TOKEN="
    refresh_key = f"{prefix}_REFRESH_TOKEN="

    lines = []
    access_found = False
    refresh_found = False

    if env_path.exists():
        with open(env_path, "r") as f:
            for line in f:
                if line.startswith(access_key):
                    lines.append(f"{prefix}_ACCESS_TOKEN={access_token}\n")
                    access_found = True
                elif line.startswith(refresh_key):
                    if refresh_token:
                        lines.append(f"{prefix}_REFRESH_TOKEN={refresh_token}\n")
                    else:
                        lines.append(line)
                    refresh_found = True
                else:
                    lines.append(line)

    if not access_found:
        lines.append(f"\n{prefix}_ACCESS_TOKEN={access_token}\n")
    if refresh_token and not refresh_found:
        lines.append(f"{prefix}_REFRESH_TOKEN={refresh_token}\n")

    fd = os.open(env_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w") as f:
        f.writelines(lines)

    print(f"✓ {prefix} tokens saved to {env_path}")
