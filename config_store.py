"""Utilities for loading credentials from environment and managing OAuth tokens."""
import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

from dotenv import load_dotenv

from contracts import APICredentials


class CredentialsStore:
    """Load application credentials from environment variables and manage OAuth files."""

    def __init__(self, persist_directory: str = "memory_db") -> None:
        self.persist_directory = Path(persist_directory)
        self.persist_directory.mkdir(parents=True, exist_ok=True)
        self.credentials_path = self.persist_directory / "credentials.json"
        self.oauth_dir = self.persist_directory / "credentials"
        self.oauth_dir.mkdir(parents=True, exist_ok=True)

    def load_env_credentials(self) -> APICredentials:
        """Load credentials from environment variables defined in .env."""
        load_dotenv()

        gmail_address = os.getenv("GMAIL_SENDER") or None
        method = (os.getenv("GMAIL_AUTH_METHOD") or "").strip().lower() or None
        app_password = os.getenv("GMAIL_APP_PASSWORD") or None
        oauth_token_path = os.getenv("GMAIL_OAUTH_TOKEN_PATH") or None
        oauth_token_json = os.getenv("GMAIL_OAUTH_TOKEN_JSON") or None

        gmail_token: Optional[str] = None
        gmail_token_path: Optional[str] = None
        resolved_method = method

        if resolved_method == "oauth" or (not resolved_method and (oauth_token_json or oauth_token_path)):
            if oauth_token_json:
                gmail_token_path = self.persist_gmail_oauth_token(oauth_token_json)
            elif oauth_token_path:
                path_candidate = Path(oauth_token_path).expanduser()
                gmail_token_path = str(path_candidate.resolve()) if path_candidate.exists() else oauth_token_path
            resolved_method = "oauth" if (gmail_token_path or oauth_token_json) else resolved_method
            gmail_token = None
        elif resolved_method == "app_password" or (app_password and not resolved_method):
            gmail_token = app_password
            gmail_token_path = None
            resolved_method = "app_password" if gmail_token else resolved_method
            if not gmail_token:
                resolved_method = None
        else:
            # Attempt to infer method when only one credential type is provided
            if app_password:
                gmail_token = app_password
                resolved_method = "app_password"
            elif oauth_token_path or oauth_token_json:
                if oauth_token_json:
                    gmail_token_path = self.persist_gmail_oauth_token(oauth_token_json)
                elif oauth_token_path:
                    path_candidate = Path(oauth_token_path).expanduser()
                    gmail_token_path = str(path_candidate.resolve()) if path_candidate.exists() else oauth_token_path
                resolved_method = "oauth"

        if resolved_method != "oauth":
            # Remove any stored OAuth token if switching away from OAuth
            self.delete_gmail_oauth_token()

        pipedrive_api_token = os.getenv("PIPEDRIVE_API_TOKEN") or None
        pipedrive_domain = os.getenv("PIPEDRIVE_DOMAIN") or None
        calendly_token = os.getenv("CALENDLY_API_KEY") or None
        calendly_event_type_uuid = os.getenv("CALENDLY_EVENT_TYPE_UUID") or None
        calendly_scheduling_link = os.getenv("CALENDLY_SCHEDULING_LINK") or None

        return APICredentials(
            gmail_token=gmail_token,
            gmail_token_path=gmail_token_path,
            gmail_address=gmail_address,
            gmail_auth_method=resolved_method,
            pipedrive_api_token=pipedrive_api_token,
            pipedrive_domain=pipedrive_domain,
            calendly_token=calendly_token,
            calendly_event_type_uuid=calendly_event_type_uuid,
            calendly_scheduling_link=calendly_scheduling_link
        )

    def persist_gmail_oauth_token(self, token_input: str) -> str:
        """Persist Gmail OAuth token JSON and return its path."""
        token_path = self.oauth_dir / "gmail_token.json"
        token_data = self._load_token_data(token_input)
        with token_path.open("w", encoding="utf-8") as fh:
            json.dump(token_data, fh, indent=2)
        return str(token_path.resolve())

    def delete_gmail_oauth_token(self) -> None:
        """Remove any stored Gmail OAuth token."""
        token_path = self.oauth_dir / "gmail_token.json"
        if token_path.exists():
            token_path.unlink()

    def _load_token_data(self, token_input: str) -> Dict[str, Any]:
        token_input = token_input.strip()
        path_candidate = Path(token_input)
        if path_candidate.exists():
            with path_candidate.open("r", encoding="utf-8") as fh:
                return json.load(fh)
        try:
            return json.loads(token_input)
        except json.JSONDecodeError as exc:  # pragma: no cover - user input
            raise ValueError("Invalid Gmail OAuth token JSON provided") from exc
