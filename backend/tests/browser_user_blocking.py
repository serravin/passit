"""Verify admin moderation and blocked sessions in separate browser contexts."""

import json
import os
import shutil
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

LOCALES = Path(__file__).resolve().parents[2] / "frontend" / "src" / "locales"


def main():
    base = os.getenv("PASSIT_WEB_URL", "http://localhost:5173")
    with sync_playwright() as p:
        executable = os.getenv("PLAYWRIGHT_CHROMIUM_PATH") or shutil.which("chromium")
        browser = p.chromium.launch(
            **({"executable_path": executable} if executable else {}), args=["--no-sandbox"]
        )
        admin = browser.new_context(locale="en-US", viewport={"width": 1440, "height": 1000})
        player = browser.new_context(locale="en-US", viewport={"width": 390, "height": 844})
        page, player_page = admin.new_page(), player.new_page()
        errors = []
        for tab in (page, player_page):
            tab.on("pageerror", lambda error: errors.append(str(error)))
            tab.goto(base)
            expect(tab.locator(".demo-bar")).to_be_visible()

        def sign_in(tab, name):
            tab.locator(".demo-bar button").click()
            tab.get_by_role("dialog").get_by_role("button", name=f"Play as {name}", exact=True).click()
            expect(tab.get_by_role("dialog")).not_to_be_visible()

        def ready():
            expect(page.locator(".moderation-page")).to_have_attribute("aria-busy", "false")
            expect(page.get_by_role("heading", name="User management.")).to_be_visible()

        sign_in(page, "Alex")
        sign_in(player_page, "Jamie")
        original = admin.request.get(base + "/api/me").json()["settings"]
        previous_events = len(admin.request.get(base + "/api/admin/moderation").json())
        jamie = player.request.get(base + "/api/me").json()
        page.locator(".profile-button").click()
        page.get_by_role("button", name="Admin dashboard", exact=True).click()
        page.get_by_role("button", name="Manage users", exact=True).click()
        ready()
        expect(page.get_by_role("button", name="Block Alex", exact=True)).to_be_disabled()
        page.get_by_label("Search users", exact=True).fill("Jamie")
        page.get_by_role("button", name="Search", exact=True).click()
        ready()
        expect(page.locator(".moderation-user")).to_have_count(1)
        expect(page.locator(".moderation-user .account-id")).to_have_text(jamie["id"])
        player_page.goto(base + "/#chains")
        expect(player_page.locator(".profile-button")).to_be_visible()
        try:
            # Review and cancel before actually applying a block.
            page.get_by_role("button", name="Block Jamie", exact=True).click()
            dialog = page.get_by_role("dialog")
            expect(dialog.get_by_role("heading", name="Block Jamie?")).to_be_visible()
            dialog.get_by_role("button", name="Cancel", exact=True).click()
            assert player.request.get(base + "/api/me").ok
            page.get_by_role("button", name="Block Jamie", exact=True).click()
            dialog.get_by_label("Private reason (optional)").fill("PRIVATE_MODERATION_REASON")
            dialog.get_by_role("button", name="Block user", exact=True).click()
            expect(dialog).not_to_be_visible()
            ready()
            expect(page.get_by_role("button", name="Unblock Jamie", exact=True)).to_be_visible()
            expect(page.locator(".moderation-user")).to_contain_text("PRIVATE_MODERATION_REASON")
            expect(player_page.get_by_role("heading", name="Account blocked", exact=True)).to_be_visible(
                timeout=10000
            )
            assert player.request.get(base + "/api/me").status == 403
            assert player.request.get(base + "/api/discover").status == 403
            assert "PRIVATE_MODERATION_REASON" not in player_page.locator("body").inner_text()
            player_page.reload()
            expect(player_page.get_by_role("heading", name="Account blocked", exact=True)).to_be_visible()
            for language in ("de", "fr", "it"):
                catalog = json.loads((LOCALES / f"{language}.json").read_text())
                player_page.locator(".language-selector").select_option(language)
                expect(
                    player_page.get_by_role("heading", name=catalog["Account blocked"], exact=True)
                ).to_be_visible()
                page.locator(".language-selector").select_option(language)
                expect(page.locator(".language-selector")).to_be_enabled()
                expect(
                    page.get_by_role("heading", name=catalog["User management."], exact=True)
                ).to_be_visible()
                page.get_by_role(
                    "button", name=catalog["Unblock {name}"].replace("{name}", "Jamie"), exact=True
                ).click()
                expect(dialog.get_by_label(catalog["Private reason (optional)"])).to_be_visible()
                for width in (320, 390, 768, 1440):
                    page.set_viewport_size({"width": width, "height": 1000})
                    assert not page.evaluate("document.documentElement.scrollWidth > innerWidth"), (
                        language,
                        width,
                    )
                dialog.get_by_role("button", name=catalog["Cancel"], exact=True).click()
            page.locator(".language-selector").select_option("en")
            player_page.locator(".language-selector").select_option("en")
            ready()
            page.screenshot(path="/tmp/passit-user-management-desktop.png", full_page=True)
            page.set_viewport_size({"width": 390, "height": 844})
            page.screenshot(path="/tmp/passit-user-management-mobile.png", full_page=True)
            player_page.screenshot(path="/tmp/passit-account-blocked.png", full_page=True)
            player_page.get_by_role("button", name="Sign out", exact=True).click()
            expect(player_page.get_by_role("heading", name="Account blocked", exact=True)).not_to_be_visible()
            player_page.locator(".demo-bar button").click()
            player_dialog = player_page.get_by_role("dialog")
            player_dialog.get_by_role("button", name="Play as Jamie", exact=True).click()
            expect(player_dialog.get_by_role("alert")).to_contain_text("Your account has been blocked")
            page.get_by_role("button", name="Unblock Jamie", exact=True).click()
            dialog.get_by_label("Private reason (optional)").fill("Appeal accepted")
            dialog.get_by_role("button", name="Unblock user", exact=True).click()
            expect(dialog).not_to_be_visible()
            ready()
            expect(page.locator(".moderation-history tbody tr")).to_have_count(min(20, previous_events + 2))
            expect(page.locator(".moderation-history tbody tr").first).to_contain_text("Unblocked")
            page.get_by_label("Account status", exact=True).select_option("blocked")
            ready()
            expect(page.locator(".moderation-user")).to_have_count(0)
            player_dialog.get_by_role("button", name="Play as Jamie", exact=True).click()
            expect(player_dialog).not_to_be_visible()
            expect(player_page.locator(".profile-button")).to_be_visible()
            assert player.request.get(base + "/api/me").ok
            player_page.goto(base + "/#admin/users")
            expect(player_page.get_by_role("heading", name="Administrator access required")).to_be_visible()
            expect(player_page.locator(".moderation-page")).to_have_count(0)
            assert player.request.get(base + "/api/admin/users").status == 403
            assert player.request.get(base + "/api/admin/moderation").status == 403
            guest = browser.new_context(locale="en-US")
            assert guest.request.get(base + "/api/admin/users").status == 401
            guest.close()
            assert not errors, errors
            print(
                "User blocking browser checks passed: search, confirmation, private history, existing sessions, reload, login denial, unblock, translations, responsive layouts and admin-only access."
            )
        finally:
            # Restore the fictional account even if a browser assertion fails.
            admin.request.put(
                base + f"/api/admin/users/{jamie['id']}/block",
                headers={"Origin": base},
                data={"blocked": False},
            )
            admin.request.put(base + "/api/me/settings", headers={"Origin": base}, data=original)
            browser.close()


if __name__ == "__main__":
    main()
