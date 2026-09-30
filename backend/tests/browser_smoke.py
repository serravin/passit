"""Run against an already-running local demo API, worker and Vite client.

python backend/tests/browser_smoke.py
Requires playwright and a Chromium installation (or PLAYWRIGHT_CHROMIUM_PATH).
"""

import os
import shutil
import time
from uuid import uuid4

from playwright.sync_api import expect, sync_playwright


def main():
    base = os.getenv("PASSIT_WEB_URL", "http://localhost:5173")
    premise = f"The hotel handed me a crown instead of a room key. Round {uuid4().hex[:8]}."
    with sync_playwright() as p:
        path = os.getenv("PLAYWRIGHT_CHROMIUM_PATH") or shutil.which("chromium")
        browser = p.chromium.launch(**({"executable_path": path} if path else {}), args=["--no-sandbox"])
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(base)
        expect(page.get_by_role("heading", name="The stories that made it.")).to_be_visible()
        accounts = context.request.get(base + "/api/demo/accounts").json()

        def switch(name):
            page.locator(".demo-bar button").click()
            page.get_by_role("dialog").get_by_role("button", name=f"Play as {name}", exact=True).click()
            expect(page.get_by_role("dialog")).not_to_be_visible()
            expect(page.locator(".demo-bar")).to_contain_text(f"Playing as {name}")

        switch("Alex")
        page.get_by_role("button", name="New chain", exact=True).first.click()
        page.get_by_role("textbox", name="Set the scene", exact=True).fill(premise)
        page.locator(".people-picker label").filter(has_text="Jamie").get_by_role("checkbox").check()
        page.locator(".people-picker label").filter(has_text="Sam").get_by_role("checkbox").check()
        page.get_by_role("button", name="Launch & pass").click()
        page.wait_for_url("**/#story/*")
        chain_id = page.url.split("#story/")[1]

        def story():
            response = context.request.get(base + f"/api/chains/{chain_id}")
            assert response.ok, response.text()
            return response.json()

        for _ in range(2):
            end = time.monotonic() + 20
            active = None
            while time.monotonic() < end:
                active = next((t for t in story()["turns"] if t["status"] != "submitted"), None)
                if active:
                    break
                page.wait_for_timeout(300)
            assert active, "No next turn was assigned"
            switch(active["user"]["name"])
            expect(page.locator(".composer")).to_be_visible(timeout=15000)
            expect(page.locator(".suggestions button")).to_have_count(3, timeout=15000)
            page.locator(".suggestions button").first.click()
            text = page.get_by_label("Your contribution").input_value()
            page.get_by_label("Your contribution").fill(text + " I asked for a receipt.")
            # A non-turn command and refresh must not discard an in-progress draft.
            page.locator(".story-meta .like-button").click()
            expect(page.get_by_label("Your contribution")).to_have_value(text + " I asked for a receipt.")
            page.get_by_role("button", name="Submit & Pass").click()
            expect(page.locator(".composer")).not_to_be_visible(timeout=15000)
        expect(page.get_by_role("heading", name="And that’s a wrap.")).to_be_visible(timeout=15000)
        chain = story()
        assert chain["status"] == "completed" and len(chain["turns"]) == 2
        assert all(t["ai_assisted"] and not t["ai_generated"] for t in chain["turns"])

        switch("Alex")
        page.get_by_role("button", name="Request publication").click()
        expect(page.locator(".approval-count")).to_have_text("1 of 3 approved")
        for name in ["Jamie", "Sam"]:
            switch(name)
            page.get_by_role("button", name="Approve", exact=True).click()
        expect(page.get_by_role("heading", name="Out in the world.")).to_be_visible(timeout=15000)
        assert story()["visibility"] == "published"
        page.get_by_role("button", name="Discover", exact=True).click()
        expect(page.locator(".story-card").filter(has_text=premise)).to_be_visible(timeout=15000)

        # Private unpublished content remains unavailable to someone outside its cast.
        response = context.request.post(
            base + "/api/chains",
            headers={"Origin": base},
            data={
                "setup": "A private side quest.",
                "member_ids": [next(a["id"] for a in accounts if a["name"] == "Alex")],
            },
        )
        assert response.status == 201, response.text()
        private_id = response.json()["id"]
        switch("Riley")
        assert context.request.get(base + f"/api/chains/{private_id}").status == 404

        # Group page must settle rather than triggering a fetch/refresh loop.
        page.get_by_role("button", name="My people", exact=True).click()
        expect(page.get_by_role("heading", name="Saved groups")).to_be_visible()
        page.wait_for_timeout(500)
        assert not errors, errors

        page.get_by_role("button", name="Discover", exact=True).click()
        page.screenshot(path="/tmp/passit-desktop.png", full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        page.evaluate("window.scrollTo(0, 0)")
        assert not page.evaluate("document.documentElement.scrollWidth > innerWidth")
        assert page.locator(".brand").is_visible()
        nav = page.locator(".header nav").bounding_box()
        assert nav and nav["y"] > 700, nav
        page.screenshot(path="/tmp/passit-mobile.png", full_page=True)
        print(
            "Browser smoke passed: creation, human turns with suggestions, draft retention, publication, discovery, privacy, and mobile layout."
        )
        browser.close()


if __name__ == "__main__":
    main()
