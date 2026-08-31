from typing import Any

from dify_plugin import ToolProvider
from dify_plugin.errors.tool import ToolProviderCredentialValidationError

from utils.aisa_client import AisaApiError, AisaClient


class GoToMarketProvider(ToolProvider):
    def _validate_credentials(self, credentials: dict[str, Any]) -> None:
        """Validate the AIsa API key against the free /credits/balance endpoint.

        Confirmed behavior: an invalid key gets HTTP 401, a valid key gets the
        account balance — no API credit is consumed.
        """
        api_key = (credentials.get("aisa_api_key") or "").strip()
        if not api_key:
            raise ToolProviderCredentialValidationError(
                "AIsa API key is required. Get one with the AIsa Go-to-Market "
                "plan ($39/mo, includes $50 API credit): "
                "https://aisa.one/solutions/go-to-market"
            )

        try:
            client = AisaClient(api_key)
            client.credits_balance()
        except AisaApiError as e:
            raise ToolProviderCredentialValidationError(e.message) from e
        except Exception as e:  # network hiccups, unexpected payloads, ...
            raise ToolProviderCredentialValidationError(
                f"Could not verify the AIsa API key: {e}"
            ) from e
