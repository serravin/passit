"""Verify dashboard date controls, comparisons, translations and admin-only access."""

import json
import os
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

LOCALES = Path(__file__).resolve().parents[2] / "frontend" / "src" / "locales"


def main():
    base = os.getenv("PASSIT_WEB_URL", "http://localhost:5173")
    today = datetime.now(UTC).date()
    with sync_playwright() as p:
        executable = os.getenv("PLAYWRIGHT_CHROMIUM_PATH") or shutil.which("chromium")
        browser = p.chromium.launch(
            **({"executable_path": executable} if executable else {}), args=["--no-sandbox"]
        )
        context = browser.new_context(locale="en-US", viewport={"width": 1440, "height": 1000})
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(base)
        expect(page.locator(".demo-bar")).to_be_visible()

        def switch(name):
            page.locator(".demo-bar button").click()
            page.locator(".account-list button").filter(has_text=name).click()
            expect(page.get_by_role("dialog")).not_to_be_visible()

        def ready():
            expect(page.locator(".statistics-page")).to_have_attribute("aria-busy", "false")
            expect(page.locator('[data-metric="active_users"]')).to_be_visible()

        def change(work):
            with page.expect_response(lambda response: "/api/admin/statistics?" in response.url) as pending:
                work()
            response = pending.value
            assert response.ok, response.text()
            ready()
            return response.json()

        switch("Alex")
        original = context.request.get(base + "/api/me").json()["settings"]
        page.locator(".profile-button").click()
        change(lambda: page.get_by_role("button", name="Admin dashboard", exact=True).click())
        expect(page.get_by_role("heading", name="Admin dashboard.")).to_be_visible()
        page.get_by_label("Reporting timezone", exact=True).fill("UTC")
        change(lambda: page.get_by_role("button", name="Apply range").click())
        for preset, label, start in (
            ("today", "Today", today),
            ("this_week", "This week", today - timedelta(days=today.weekday())),
            ("mtd", "MTD", today.replace(day=1)),
            ("ytd", "YTD", today.replace(month=1, day=1)),
            ("last7", "Last 7 days", today - timedelta(days=6)),
            ("last30", "Last 30 days", today - timedelta(days=29)),
        ):
            data = change(lambda: page.get_by_role("button", name=label, exact=True).click())
            assert data["period"]["preset"] == preset and data["period"]["start_date"] == start.isoformat()
            expect(page.get_by_label("Start date", exact=True)).to_have_value(start.isoformat())
            expect(page.get_by_label("End date", exact=True)).to_have_value(today.isoformat())
            expect(page.locator('[data-metric="active_users"] strong')).to_have_text(
                str(data["current"]["metrics"]["active_users"])
            )
        page.get_by_role("button", name="Custom", exact=True).click()
        custom_start = (today - timedelta(days=10)).isoformat()
        page.get_by_label("Start date", exact=True).fill(custom_start)
        page.get_by_label("End date", exact=True).fill(today.isoformat())
        data = change(lambda: page.get_by_role("button", name="Apply range").click())
        assert data["period"]["preset"] == "custom" and data["period"]["start_date"] == custom_start
        page.reload()
        ready()
        expect(page.get_by_label("Start date", exact=True)).to_have_value(custom_start)
        assert page.get_by_role("button", name="Custom", exact=True).get_attribute("aria-pressed") == "true"
        expect(page.locator('[data-metric="mrr"] strong')).to_have_text("Unavailable")
        compare = page.get_by_label("Compare with the previous equivalent period", exact=True)
        compare.uncheck()
        expect(page.locator(".metric-card small")).to_have_count(0)
        compare.check()
        expect(page.locator('[data-metric="active_users"] small')).to_contain_text("Previous")
        page.get_by_role("button", name="View chart data").click()
        expect(page.locator(".chart-panel table")).to_be_visible()
        all_time = change(lambda: page.get_by_role("button", name="All time", exact=True).click())
        assert all_time["comparison"] is None
        expect(page.locator(".metric-card small")).to_have_count(0)
        page.get_by_label("Reporting timezone", exact=True).fill("Europe/Berlin")
        data = change(lambda: page.get_by_role("button", name="Apply range").click())
        assert data["period"]["timezone"] == "Europe/Berlin"
        expect(page.locator(".report-caption")).to_contain_text("Europe/Berlin")

        # Locale changes retain the chosen range and localized dashboard controls.
        for language in ("de", "fr", "it"):
            catalog = json.loads((LOCALES / f"{language}.json").read_text())
            page.locator(".language-selector").select_option(language)
            expect(page.locator(".language-selector")).to_be_enabled()
            ready()
            expect(page.get_by_role("heading", name=catalog["Admin dashboard."])).to_be_visible()
            expect(page.get_by_role("button", name=catalog["Apply range"])).to_be_visible()
            expect(page.locator('[data-metric="mrr"] strong')).to_have_text(catalog["Unavailable"])
            for width in (320, 390, 768, 1440):
                page.set_viewport_size({"width": width, "height": 1000})
                assert not page.evaluate("document.documentElement.scrollWidth > innerWidth"), (
                    language,
                    width,
                )
            page.set_viewport_size({"width": 1440, "height": 1000})
        page.locator(".language-selector").select_option("en")
        expect(page.locator(".language-selector")).to_be_enabled()
        ready()
        page.get_by_role("button", name="Configuration", exact=True).click()
        expect(page.get_by_label("Input price per 1M tokens (USD)")).to_be_visible()
        expect(page.get_by_label("Output price per 1M tokens (USD)")).to_be_visible()
        page.get_by_role("button", name="Admin dashboard", exact=True).click()
        ready()
        page.screenshot(path="/tmp/passit-dashboard-desktop.png", full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        page.screenshot(path="/tmp/passit-dashboard-mobile.png", full_page=True)
        page.set_viewport_size({"width": 1440, "height": 1000})

        switch("Jamie")
        expect(page.get_by_role("heading", name="Administrator access required")).to_be_visible()
        expect(page.locator(".statistics-page")).to_have_count(0)
        assert context.request.get(base + "/api/admin/statistics").status == 403
        page.locator(".profile-button").click()
        expect(page.get_by_role("button", name="Admin dashboard", exact=True)).to_have_count(0)
        anonymous = browser.new_context(locale="en-US")
        assert anonymous.request.get(base + "/api/admin/statistics").status == 401
        anon_page = anonymous.new_page()
        anon_page.goto(base + "/#dashboard")
        expect(anon_page.get_by_role("heading", name="Your story starts here")).to_be_visible()
        expect(anon_page.locator(".statistics-page")).to_have_count(0)
        anonymous.close()
        # Restore the administrator’s language without changing another player's preferences.
        switch("Alex")
        context.request.put(base + "/api/me/settings", headers={"Origin": base}, data=original)
        assert not errors, errors
        browser.close()
        print(
            "Dashboard smoke passed: custom dates, all presets, timezones, comparisons, charts, persistence, translations, mobile layouts, price controls and admin-only access."
        )


if __name__ == "__main__":
    main()
