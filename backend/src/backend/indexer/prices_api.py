"""Prices service transport and provider capabilities."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any
from urllib import error, parse, request

DEFAULT_PRICES_API_BASE_URL = "https://prices.wavey.info"


class PricesApiError(RuntimeError):
    pass


class PricesApiAuthError(PricesApiError):
    pass


class PricesApiRateLimitError(PricesApiError):
    pass


DEFAULT_PROVIDER_CACHE_TTL_SECONDS = 60


def _extract_detail_message(body: str) -> str | None:
    if not body:
        return None
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return body.strip() or None
    detail = payload.get("detail")
    if isinstance(detail, dict):
        message = detail.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()
    if isinstance(detail, str) and detail.strip():
        return detail.strip()
    return None


@dataclass(frozen=True)
class ProviderCapability:
    id: str
    supports_price: bool
    supports_quote: bool
    supported_chains: tuple[int, ...]
    requires_api_key: bool
    available: bool
    unavailable_reason: str | None


class PricingApiClient:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout_seconds: float = 8.0,
    ) -> None:
        self.base_url = (base_url or os.environ.get("PRICES_API_BASE_URL") or DEFAULT_PRICES_API_BASE_URL).rstrip("/")
        self.api_key = (api_key if api_key is not None else os.environ.get("PRICES_API_KEY", "")).strip()
        self.timeout_seconds = timeout_seconds
        self._providers_cache: list[ProviderCapability] | None = None
        self._providers_cache_expires_at: float | None = None

    def fetch_providers(self) -> list[ProviderCapability]:
        now = time.monotonic()
        if (
            self._providers_cache is None
            or self._providers_cache_expires_at is None
            or now >= self._providers_cache_expires_at
        ):
            payload = self._request_json("/v1/providers")
            providers = payload.get("providers")
            if not isinstance(providers, list):
                raise PricesApiError("prices API providers response was malformed")
            self._providers_cache = [
                ProviderCapability(
                    id=str(item["id"]),
                    supports_price=bool(item.get("supports_price")),
                    supports_quote=bool(item.get("supports_quote")),
                    supported_chains=tuple(int(chain_id) for chain_id in item.get("supported_chains") or ()),
                    requires_api_key=bool(item.get("requires_api_key")),
                    available=bool(item.get("available", True)),
                    unavailable_reason=(
                        str(item["unavailable_reason"]).strip()
                        if item.get("unavailable_reason")
                        else None
                    ),
                )
                for item in providers
                if isinstance(item, dict) and item.get("id")
            ]
            self._providers_cache_expires_at = time.monotonic() + DEFAULT_PROVIDER_CACHE_TTL_SECONDS
        return list(self._providers_cache)

    def supported_providers(self, *, chain_id: int, kind: str) -> list[ProviderCapability]:
        providers = []
        for item in self.fetch_providers():
            if chain_id not in item.supported_chains:
                continue
            if kind == "quote" and not item.supports_quote:
                continue
            if kind == "price" and not item.supports_price:
                continue
            providers.append(item)
        return providers

    def fetch_quote(
        self,
        *,
        chain_id: int,
        token_in: str,
        token_out: str,
        amount_in: str,
        providers: list[str],
        use_underlying: bool,
        timeout_ms: int,
    ) -> dict[str, Any]:
        query = parse.urlencode(
            {
                "chain_id": chain_id,
                "token_in": token_in,
                "token_out": token_out,
                "amount_in": amount_in,
                "providers": providers,
                "include_route": True,
                "use_underlying": use_underlying,
                "timeout_ms": timeout_ms,
            },
            doseq=True,
        )
        return self._request_json(f"/v1/quote?{query}")

    def fetch_price(
        self,
        *,
        chain_id: int,
        token: str,
        providers: list[str],
        use_underlying: bool,
        timeout_ms: int,
    ) -> dict[str, Any]:
        query = parse.urlencode(
            {
                "chain_id": chain_id,
                "token": token,
                "providers": providers,
                "use_underlying": use_underlying,
                "timeout_ms": timeout_ms,
            },
            doseq=True,
        )
        return self._request_json(f"/v1/price?{query}")

    def _request_json(self, path: str) -> dict[str, Any]:
        headers = {
            "Accept": "application/json",
            "User-Agent": "auctionscan/pricing",
        }
        if self.api_key:
            headers["x-api-key"] = self.api_key
        req = request.Request(f"{self.base_url}{path}", headers=headers, method="GET")
        try:
            with request.urlopen(req, timeout=self.timeout_seconds) as response:
                payload = json.load(response)
        except error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            if exc.code in {401, 403}:
                raise PricesApiAuthError(
                    f"prices API authentication failed ({exc.code})"
                ) from exc
            if exc.code == 429:
                raise PricesApiRateLimitError("prices API rate limit exceeded") from exc
            raise PricesApiError(
                f"prices API request failed ({exc.code}): {_extract_detail_message(body) or exc.reason}"
            ) from exc
        except error.URLError as exc:
            raise PricesApiError(f"prices API request failed: {exc.reason}") from exc

        if not isinstance(payload, dict):
            raise PricesApiError("prices API returned a non-object JSON payload")
        return payload
