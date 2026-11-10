"""AlterLab SDK Session & Cookie Examples.

Demonstrates authenticated scraping using stored sessions and inline cookies.

Features demonstrated:
- Inline cookies for one-off authenticated scraping
- Creating and managing stored sessions
- Session validation
- Cookie rotation (refresh)
- Synchronous wrapper usage
"""

import asyncio

from alterlab import AlterLab, AlterLabSync


async def example_inline_cookies():
    """Example 1: One-off authenticated scraping with inline cookies."""
    print("\n" + "=" * 60)
    print("Example 1: Inline Cookies (One-off)")
    print("=" * 60)

    async with AlterLab(api_key="sk_test_...") as client:
        # Pass cookies directly — not stored, just used for this request
        result = await client.scrape(
            url="https://amazon.com/dp/B0XXXXX",
            cookies={
                "session-id": "abc123",
                "session-token": "xyz789",
                "ubid-main": "131-1234567-1234567",
            },
        )

        print(f"Status: {result.get('status_code')}")
        print(f"Content length: {len(result.get('content', ''))} characters")
        print(f"BYOS applied: {result.get('byos_applied', False)}")


async def example_session_crud():
    """Example 2: Full session lifecycle — create, list, get, update, delete."""
    print("\n" + "=" * 60)
    print("Example 2: Session CRUD")
    print("=" * 60)

    async with AlterLab(api_key="sk_test_...") as client:
        # Create a session
        session = await client.sessions.create(
            name="My Amazon Prime",
            domain="amazon.com",
            cookies={
                "session-id": "abc123",
                "session-token": "xyz789",
            },
            notes="Personal Prime account for product scraping",
        )
        print(f"Created session: {session['id']}")
        print(f"  Name: {session['name']}")
        print(f"  Domain: {session['domain']}")
        print(f"  Cookie names: {session['cookie_names']}")
        print(f"  Status: {session['status']}")

        # List all sessions
        result = await client.sessions.list()
        print(f"\nTotal sessions: {result['total']}")
        for s in result["sessions"]:
            print(f"  - {s['name']} ({s['domain']}) [{s['status']}]")

        # Get a specific session
        fetched = await client.sessions.get(session["id"])
        print(f"\nFetched session: {fetched['name']}")

        # Update session name
        updated = await client.sessions.update(
            session["id"],
            name="Amazon Prime - Production",
            notes="Updated for production use",
        )
        print(f"Updated name: {updated['name']}")

        # Delete when done
        await client.sessions.delete(session["id"])
        print("Session deleted.")


async def example_session_validation():
    """Example 3: Validate a session to check if cookies are still valid."""
    print("\n" + "=" * 60)
    print("Example 3: Session Validation")
    print("=" * 60)

    async with AlterLab(api_key="sk_test_...") as client:
        # Create a session first
        session = await client.sessions.create(
            name="Target Session",
            domain="target.com",
            cookies={"session_token": "abc123"},
        )

        # Validate the session
        validation = await client.sessions.validate(session["id"])
        print(f"Valid: {validation['is_valid']}")
        print(f"Confidence: {validation['confidence']}%")
        print(f"Details: {validation['details']}")
        if validation.get("detected_user"):
            print(f"Detected user: {validation['detected_user']}")
        if validation.get("cookies_expiring_soon"):
            print("Warning: Some cookies are expiring soon!")

        # Cleanup
        await client.sessions.delete(session["id"])


async def example_cookie_rotation():
    """Example 4: Rotate cookies when they expire."""
    print("\n" + "=" * 60)
    print("Example 4: Cookie Rotation (Refresh)")
    print("=" * 60)

    async with AlterLab(api_key="sk_test_...") as client:
        session = await client.sessions.create(
            name="Rotating Session",
            domain="example.com",
            cookies={"auth": "old-token-123"},
        )
        print(f"Original cookie names: {session['cookie_names']}")

        # Rotate cookies with fresh values
        refreshed = await client.sessions.refresh(
            session["id"],
            cookies={"auth": "new-token-456", "refresh": "refresh-789"},
        )
        print(f"Refreshed cookie names: {refreshed['cookie_names']}")
        print(f"Status after refresh: {refreshed['status']}")

        await client.sessions.delete(session["id"])


async def example_scrape_with_session():
    """Example 5: Scrape using a stored session."""
    print("\n" + "=" * 60)
    print("Example 5: Scrape with Stored Session")
    print("=" * 60)

    async with AlterLab(api_key="sk_test_...") as client:
        # Create and store session
        session = await client.sessions.create(
            name="Amazon Scraping Session",
            domain="amazon.com",
            cookies={
                "session-id": "abc123",
                "session-token": "xyz789",
            },
        )

        # Scrape using the stored session
        result = await client.scrape(
            url="https://amazon.com/dp/B0XXXXX",
            session_id=session["id"],
        )
        print(f"Content length: {len(result.get('content', ''))} characters")
        print(f"BYOS applied: {result.get('byos_applied', False)}")

        # Cleanup
        await client.sessions.delete(session["id"])


def example_sync_sessions():
    """Example 6: Synchronous session management."""
    print("\n" + "=" * 60)
    print("Example 6: Synchronous Wrapper")
    print("=" * 60)

    with AlterLabSync(api_key="sk_test_...") as client:
        # All session methods work synchronously too
        session = client.sessions.create(
            name="Sync Session",
            domain="example.com",
            cookies={"token": "abc123"},
        )
        print(f"Created: {session['id']}")

        sessions = client.sessions.list()
        print(f"Total sessions: {sessions['total']}")

        client.sessions.delete(session["id"])
        print("Deleted.")


async def main():
    """Run all examples."""
    print("=" * 60)
    print("AlterLab Python SDK - Session & Cookie Examples")
    print("=" * 60)

    await example_inline_cookies()
    await example_session_crud()
    await example_session_validation()
    await example_cookie_rotation()
    await example_scrape_with_session()

    # Sync example
    example_sync_sessions()

    print("\n" + "=" * 60)
    print("All session examples completed!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
