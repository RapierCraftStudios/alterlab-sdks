"""Session integration resource for AlterLab SDK.

Provides CRUD operations and validation for stored browser session integrations
(BYOS -- Bring Your Own Session). Users store encrypted cookies for authenticated
scraping of protected content.

Cookie values are NEVER returned in API responses -- only cookie names.
"""

from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from alterlab.client import AlterLab

from alterlab.types import (SessionIntegration, SessionListResponse,
                            SessionValidation)


class AsyncSessions:
    """Async session management resource.

    Access via ``client.sessions``.

    Example::

        async with AlterLab(api_key="sk_test_...") as client:
            # Create a session
            session = await client.sessions.create(
                name="My Amazon Prime",
                domain="amazon.com",
                cookies={"session-id": "abc123", "session-token": "xyz789"},
            )

            # List all sessions
            result = await client.sessions.list()
            for s in result["sessions"]:
                print(f"{s['name']} ({s['domain']}) - {s['status']}")

            # Validate a session
            validation = await client.sessions.validate(session["id"])
            print(f"Valid: {validation['is_valid']}")

            # Refresh cookies (rotate)
            updated = await client.sessions.refresh(
                session["id"],
                cookies={"session-id": "new-abc", "session-token": "new-xyz"},
            )

            # Delete when done
            await client.sessions.delete(session["id"])
    """

    def __init__(self, client: "AlterLab") -> None:
        self._client = client

    async def create(
        self,
        name: str,
        domain: str,
        cookies: Dict[str, str],
        headers: Optional[Dict[str, str]] = None,
        expires_at: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> SessionIntegration:
        """Create a new session integration.

        Stores encrypted cookies for authenticated scraping of a specific domain.

        Args:
            name: User label for this session (e.g. "My Amazon Prime")
            domain: Target domain (e.g. "amazon.com"). Protocols and paths are stripped.
            cookies: Cookie name-value mapping. Values are encrypted at rest.
            headers: Optional custom headers for this session.
            expires_at: Optional ISO-8601 expiration timestamp.
            notes: Optional user notes (max 1000 characters).

        Returns:
            Created session integration (cookie values are never returned).

        Raises:
            AlterLabAPIError: On validation errors or API failures.
        """
        payload: Dict[str, Any] = {
            "name": name,
            "domain": domain,
            "cookies": cookies,
        }
        if headers is not None:
            payload["headers"] = headers
        if expires_at is not None:
            payload["expires_at"] = expires_at
        if notes is not None:
            payload["notes"] = notes

        response = await self._client._request_with_retry(
            "POST", "/api/v1/sessions", json=payload
        )
        return response.json()

    async def list(
        self,
        domain: Optional[str] = None,
        status: Optional[str] = None,
    ) -> SessionListResponse:
        """List all session integrations for the authenticated user.

        Args:
            domain: Optional domain filter.
            status: Optional status filter (active, expired, invalid, pending_validation).

        Returns:
            Dictionary with ``sessions`` list and ``total`` count.

        Raises:
            AlterLabAPIError: On API failures.
        """
        params: Dict[str, str] = {}
        if domain is not None:
            params["domain"] = domain
        if status is not None:
            params["status"] = status

        response = await self._client._request_with_retry(
            "GET", "/api/v1/sessions", params=params
        )
        return response.json()

    async def get(self, session_id: str) -> SessionIntegration:
        """Get a single session integration by ID.

        Args:
            session_id: UUID of the session to retrieve.

        Returns:
            Session integration details (cookie values are never returned).

        Raises:
            AlterLabAPIError: If session not found or access denied.
        """
        response = await self._client._request_with_retry(
            "GET", f"/api/v1/sessions/{session_id}"
        )
        return response.json()

    async def update(
        self,
        session_id: str,
        name: Optional[str] = None,
        cookies: Optional[Dict[str, str]] = None,
        headers: Optional[Dict[str, str]] = None,
        expires_at: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> SessionIntegration:
        """Update a session integration.

        Only provided fields are updated. Use ``refresh()`` for cookie-only rotation
        with automatic re-validation.

        Args:
            session_id: UUID of the session to update.
            name: New session label.
            cookies: New cookie name-value mapping (replaces all cookies).
            headers: New custom headers (replaces all headers).
            expires_at: New expiration timestamp (ISO-8601).
            notes: New notes.

        Returns:
            Updated session integration.

        Raises:
            AlterLabAPIError: If session not found or validation fails.
        """
        payload: Dict[str, Any] = {}
        if name is not None:
            payload["name"] = name
        if cookies is not None:
            payload["cookies"] = cookies
        if headers is not None:
            payload["headers"] = headers
        if expires_at is not None:
            payload["expires_at"] = expires_at
        if notes is not None:
            payload["notes"] = notes

        response = await self._client._request_with_retry(
            "PATCH", f"/api/v1/sessions/{session_id}", json=payload
        )
        return response.json()

    async def delete(self, session_id: str) -> None:
        """Delete a session integration (soft delete).

        Args:
            session_id: UUID of the session to delete.

        Raises:
            AlterLabAPIError: If session not found or access denied.
        """
        await self._client._request_with_retry(
            "DELETE", f"/api/v1/sessions/{session_id}"
        )

    async def validate(self, session_id: str) -> SessionValidation:
        """Validate a session by testing its cookies against the target domain.

        Makes a real HTTP request to the stored domain using the session cookies
        and checks for logged-in indicators.

        Args:
            session_id: UUID of the session to validate.

        Returns:
            Validation result with ``is_valid``, ``confidence``, and ``details``.

        Raises:
            AlterLabAPIError: If session not found or validation request fails.
        """
        response = await self._client._request_with_retry(
            "POST", f"/api/v1/sessions/{session_id}/validate"
        )
        return response.json()

    async def refresh(
        self,
        session_id: str,
        cookies: Dict[str, str],
        headers: Optional[Dict[str, str]] = None,
    ) -> SessionIntegration:
        """Refresh (rotate) session cookies.

        Replaces all cookies and optionally headers, resets failure counters,
        and sets status back to ``active``.

        Args:
            session_id: UUID of the session to refresh.
            cookies: New cookie name-value mapping.
            headers: Optional new custom headers.

        Returns:
            Updated session integration.

        Raises:
            AlterLabAPIError: If session not found or validation fails.
        """
        payload: Dict[str, Any] = {"cookies": cookies}
        if headers is not None:
            payload["headers"] = headers

        response = await self._client._request_with_retry(
            "POST", f"/api/v1/sessions/{session_id}/refresh", json=payload
        )
        return response.json()


class SyncSessions:
    """Synchronous session management resource.

    Wraps ``AsyncSessions`` methods for non-async usage. Access via
    ``client.sessions`` on ``AlterLabSync``.

    Example::

        with AlterLabSync(api_key="sk_test_...") as client:
            session = client.sessions.create(
                name="My Amazon Prime",
                domain="amazon.com",
                cookies={"session-id": "abc123"},
            )
            sessions = client.sessions.list()
            client.sessions.delete(session["id"])
    """

    def __init__(self, async_sessions: AsyncSessions, runner) -> None:
        self._async = async_sessions
        self._run = runner

    def create(
        self,
        name: str,
        domain: str,
        cookies: Dict[str, str],
        headers: Optional[Dict[str, str]] = None,
        expires_at: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> SessionIntegration:
        """Synchronous version of create(). See AsyncSessions.create() for details."""
        return self._run(
            self._async.create(
                name=name,
                domain=domain,
                cookies=cookies,
                headers=headers,
                expires_at=expires_at,
                notes=notes,
            )
        )

    def list(
        self,
        domain: Optional[str] = None,
        status: Optional[str] = None,
    ) -> SessionListResponse:
        """Synchronous version of list(). See AsyncSessions.list() for details."""
        return self._run(self._async.list(domain=domain, status=status))

    def get(self, session_id: str) -> SessionIntegration:
        """Synchronous version of get(). See AsyncSessions.get() for details."""
        return self._run(self._async.get(session_id))

    def update(
        self,
        session_id: str,
        name: Optional[str] = None,
        cookies: Optional[Dict[str, str]] = None,
        headers: Optional[Dict[str, str]] = None,
        expires_at: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> SessionIntegration:
        """Synchronous version of update(). See AsyncSessions.update() for details."""
        return self._run(
            self._async.update(
                session_id=session_id,
                name=name,
                cookies=cookies,
                headers=headers,
                expires_at=expires_at,
                notes=notes,
            )
        )

    def delete(self, session_id: str) -> None:
        """Synchronous version of delete(). See AsyncSessions.delete() for details."""
        return self._run(self._async.delete(session_id))

    def validate(self, session_id: str) -> SessionValidation:
        """Synchronous version of validate(). See AsyncSessions.validate() for details."""
        return self._run(self._async.validate(session_id))

    def refresh(
        self,
        session_id: str,
        cookies: Dict[str, str],
        headers: Optional[Dict[str, str]] = None,
    ) -> SessionIntegration:
        """Synchronous version of refresh(). See AsyncSessions.refresh() for details."""
        return self._run(
            self._async.refresh(session_id=session_id, cookies=cookies, headers=headers)
        )
