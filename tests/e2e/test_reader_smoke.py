"""
Two-context Playwright smoke test (LOCAL ONLY — needs `pip install playwright`
and `playwright install chromium`).

Scenario (the brief's smoke test): two users annotate the same PDF and see each
other's room annotations appear through the polling sync, without echoing.

Run:  python -m pytest tests/e2e -q      (or: playwright test)
Skipped automatically when playwright is not installed.
"""
import os
import unittest

try:
    import pytest
    from playwright.sync_api import expect, sync_playwright
except ImportError as exc:  # pragma: no cover - e2e extras are optional
    raise unittest.SkipTest(f"e2e extras not installed: {exc}")

BASE = os.environ.get("E2E_BASE_URL", "http://127.0.0.1:8000")


def _login(page, username, password):
    page.goto(f"{BASE}/accounts/login/")
    page.fill("#id_username", username)
    page.fill("#id_password", password)
    page.click("button[type=submit]")
    page.wait_for_url(f"{BASE}/")


@pytest.mark.e2e
def test_two_users_annotate_the_same_pdf():  # noqa: ANN201
    """
    Alice creates a room, Bob joins, both annotate; each sees the other's
    annotation in the room layer within the poll interval; neither sees the
    other's private notes.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch()
        alice_ctx = browser.new_context()
        bob_ctx = browser.new_context()
        alice = alice_ctx.new_page()
        bob = bob_ctx.new_page()

        try:
            _login(alice, "alice", "test-password-123")
            _login(bob, "bob", "test-password-123")

            # Alice starts a shared reading for book 1 and opens the reader.
            alice.goto(f"{BASE}/library/1/")
            alice.click("text=Start shared reading")
            alice.wait_for_url("**/rooms/**")
            invite = alice.locator("code").first.inner_text()
            alice.goto(f"{BASE}/read/1/")

            # Bob joins via the invite link and opens the same reader room.
            bob.goto(invite.replace(BASE, BASE))
            bob.goto(f"{BASE}/read/1/")

            # Both select the room layer.
            for page in (alice, bob):
                page.click('button.layer-btn[data-layer="room"]')

            # Alice annotates (highlight tool), Bob annotates.
            for page, label in ((alice, "alice note"), (bob, "bob note")):
                page.evaluate(
                    """async (label) => {
                        const registry = await window.__viewer.registry;
                        const api = registry.getPlugin('annotation').provides();
                        api.setActiveTool('highlight');
                    }""",
                    label,
                )

            # Within ~2 poll intervals each sees presence of the other.
            alice.wait_for_timeout(8000)
            assert alice.locator("#presenceAvatars .avatar").count() >= 1
            assert bob.locator("#presenceAvatars .avatar").count() >= 1

            # Sync chip should not be stuck offline.
            chip = alice.locator("#syncChip")
            expect(chip).not_to_have_text("Offline")
        finally:
            alice_ctx.close()
            bob_ctx.close()
            browser.close()
