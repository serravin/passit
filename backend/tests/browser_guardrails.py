"""Check automatic blocks, in-app notices and admin review in separate browsers."""

import json
import os
import shutil
from pathlib import Path
from uuid import uuid4

from playwright.sync_api import expect, sync_playwright

LOCALES = Path(__file__).resolve().parents[2] / "frontend" / "src" / "locales"


def main():
    base = os.getenv("PASSIT_WEB_URL", "http://localhost:5173")
    # This explicit marker tests the demo plumbing; the demo is not a safety classifier.
    text = "[[demo:bullying]] " + uuid4().hex[:10]
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
            tab.locator(".language-selector").select_option("en")

        def sign_in(tab, name):
            tab.locator(".demo-bar button").click()
            tab.get_by_role("dialog").get_by_role("button", name=f"Play as {name}", exact=True).click()
            expect(tab.get_by_role("dialog")).not_to_be_visible()

        sign_in(page, "Alex")
        sign_in(player_page, "Jamie")
        original = admin.request.get(base + "/api/me").json()["settings"]
        jamie = player.request.get(base + "/api/me").json()
        for notice in player.request.get(base + "/api/account-status").json()["notices"]:
            assert player.request.post(
                base + f"/api/account-notices/{notice['id']}/read", headers={"Origin": base}
            ).ok
        review_id = None
        try:
            player_page.get_by_role("button", name="New chain", exact=True).first.click()
            player_page.get_by_role("textbox", name="Set the scene", exact=True).fill(text)
            player_page.locator(".people-picker label").filter(has_text="Alex").get_by_role(
                "checkbox"
            ).check()
            player_page.get_by_role("button", name="Launch & pass").click()
            expect(player_page.get_by_role("heading", name="Account blocked", exact=True)).to_be_visible()
            expect(player_page.locator(".account-notices")).to_contain_text(
                "Your account was blocked by the story safety check."
            )
            expect(player_page.locator(".account-notices")).to_contain_text("Bullying or harassment")
            expect(player_page.locator(".account-notices")).to_contain_text("Contact an administrator")
            assert player.request.get(base + "/api/me").status == 403
            assert player.request.get(base + "/api/account-status").ok
            assert text not in player_page.locator("body").inner_text()
            player_page.reload()
            expect(player_page.locator(".account-notices")).to_contain_text("Bullying or harassment")
            page.locator(".profile-button").click()
            page.get_by_role("button", name="Admin dashboard", exact=True).click()
            page.get_by_role("button", name="Safety reviews", exact=True).click()
            expect(page.locator(".safety-page")).to_have_attribute("aria-busy", "false")
            card = page.locator(".safety-review").filter(has_text=text)
            expect(card).to_contain_text("Jamie")
            expect(card).to_contain_text("Human-written")
            records = admin.request.get(base + "/api/admin/safety-reviews").json()["items"]
            review_id = next(r["id"] for r in records if r["text"] == text)
            for language in ("de", "fr", "it"):
                catalog = json.loads((LOCALES / f"{language}.json").read_text())
                player_page.locator(".language-selector").select_option(language)
                page.locator(".language-selector").select_option(language)
                expect(player_page.locator(".account-notices")).to_contain_text(
                    catalog["Bullying or harassment"]
                )
                expect(
                    page.get_by_role("heading", name=catalog["Story safety reviews."], exact=True)
                ).to_be_visible()
                expect(card).to_contain_text(catalog["Flagged text"])
                for width in (320, 390, 768, 1440):
                    for tab in (page, player_page):
                        tab.set_viewport_size({"width": width, "height": 1000})
                        assert not tab.evaluate("document.documentElement.scrollWidth > innerWidth"), (
                            language,
                            width,
                            tab.url,
                            tab.evaluate(
                                "Array.from(document.querySelectorAll('body *')).filter(e => e.getBoundingClientRect().right > innerWidth).map(e => [e.className, e.textContent.slice(0,100)])"
                            ),
                        )
            page.locator(".language-selector").select_option("en")
            player_page.locator(".language-selector").select_option("en")
            page.set_viewport_size({"width": 1440, "height": 1000})
            page.screenshot(path="/tmp/passit-safety-reviews-desktop.png", full_page=True)
            page.set_viewport_size({"width": 390, "height": 844})
            page.screenshot(path="/tmp/passit-safety-reviews-mobile.png", full_page=True)
            player_page.set_viewport_size({"width": 390, "height": 844})
            player_page.screenshot(path="/tmp/passit-safety-notice.png", full_page=True)
            page.once("dialog", lambda dialog: dialog.accept())
            card.get_by_role("button", name="Allow & review account access", exact=True).click()
            expect(card).to_have_count(0)
            assert player.request.get(base + "/api/me").ok
            player_page.reload()
            expect(player_page.get_by_role("heading", name="Account blocked", exact=True)).not_to_be_visible()
            expect(player_page.locator(".account-notices")).to_contain_text(
                "Your account access was restored."
            )
            # Acknowledgement works for this identity and persists across reload.
            restored = player_page.locator(".account-notice").filter(
                has_text="Your account access was restored."
            )
            restored.get_by_role("button", name="Dismiss notice", exact=True).click()
            expect(restored).to_have_count(0)
            player_page.reload()
            expect(restored).to_have_count(0)
            player_page.goto(base + "/#admin/safety")
            expect(player_page.get_by_role("heading", name="Administrator access required")).to_be_visible()
            assert player.request.get(base + "/api/admin/safety-reviews").status == 403
            guest = browser.new_context()
            assert guest.request.get(base + "/api/admin/safety-reviews").status == 401
            guest.close()
            assert not errors, errors
            print(
                "Guardrail browser checks passed: automatic block, persistent in-app notice, admin reversal, notice acknowledgement, translations, responsive layouts and private review access."
            )
        finally:
            if review_id:
                admin.request.put(
                    base + f"/api/admin/safety-reviews/{review_id}",
                    headers={"Origin": base},
                    data={"decision": "allow"},
                )
            admin.request.put(
                base + f"/api/admin/users/{jamie['id']}/block",
                headers={"Origin": base},
                data={"blocked": False},
            )
            admin.request.put(base + "/api/me/settings", headers={"Origin": base}, data=original)
            browser.close()


if __name__ == "__main__":
    main()
