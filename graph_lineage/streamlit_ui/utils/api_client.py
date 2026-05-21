"""HTTP client for Master API integration."""

from __future__ import annotations

import httpx

from graph_lineage.streamlit_ui.utils.errors import APIError


class HTTPXClient:
    """Async HTTP client for Master API calls with auth headers."""

    def __init__(self, base_url: str, api_token: str = ""):
        """Initialize HTTP client.

        Args:
            base_url: Master API base URL.
            api_token: API token for X-API-Key header.
        """
        self.base_url = base_url
        self.api_token = api_token
        self.client = httpx.AsyncClient(base_url=base_url, timeout=10.0)

    async def post(self, endpoint: str, json: dict | None = None) -> httpx.Response:
        """POST request to Master API.

        Args:
            endpoint: API endpoint path.
            json: Request body.

        Returns:
            HTTP response.

        Raises:
            APIError: If response status >= 400.
        """
        headers = {"X-API-Key": self.api_token} if self.api_token else {}
        response = await self.client.post(endpoint, json=json, headers=headers)

        if response.status_code >= 400:
            raise APIError(
                response.status_code, response.text, response.json() if response.text else ""
            )
        return response

    async def patch(self, endpoint: str, json: dict | None = None) -> httpx.Response:
        """PATCH request to Master API.

        Args:
            endpoint: API endpoint path.
            json: Request body.

        Returns:
            HTTP response.

        Raises:
            APIError: If response status >= 400.
        """
        headers = {"X-API-Key": self.api_token} if self.api_token else {}
        response = await self.client.patch(endpoint, json=json, headers=headers)

        if response.status_code >= 400:
            raise APIError(
                response.status_code, response.text, response.json() if response.text else ""
            )
        return response

    async def delete(self, endpoint: str) -> httpx.Response:
        """DELETE request to Master API.

        Args:
            endpoint: API endpoint path.

        Returns:
            HTTP response.

        Raises:
            APIError: If response status >= 400.
        """
        headers = {"X-API-Key": self.api_token} if self.api_token else {}
        response = await self.client.delete(endpoint, headers=headers)

        if response.status_code >= 400:
            raise APIError(
                response.status_code, response.text, response.json() if response.text else ""
            )
        return response

    async def get(self, endpoint: str) -> httpx.Response:
        """GET request to Master API.

        Args:
            endpoint: API endpoint path.

        Returns:
            HTTP response.

        Raises:
            APIError: If response status >= 400.
        """
        headers = {"X-API-Key": self.api_token} if self.api_token else {}
        response = await self.client.get(endpoint, headers=headers)

        if response.status_code >= 400:
            raise APIError(
                response.status_code, response.text, response.json() if response.text else ""
            )
        return response

    async def close(self) -> None:
        """Close the HTTP client."""
        await self.client.aclose()
