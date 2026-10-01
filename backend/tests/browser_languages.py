"""Exercise localization against a running demo API, worker and Vite client."""

import json
import os
import shutil
from pathlib import Path
from uuid import uuid4

from playwright.sync_api import expect, sync_playwright

LOCALES = Path(__file__).resolve().parents[2] / "frontend" / "src" / "locales"


def main():
    base = os.getenv("PASSIT_WEB_URL", "http://localhost:5173")
    with sync_playwright() as p:
        executable = os.getenv("PLAYWRIGHT_CHROMIUM_PATH") or shutil.which("chromium")
        browser = p.chromium.launch(
            **({"executable_path": executable} if executable else {}), args=["--no-sandbox"]
        )
        context = browser.new_context(locale="de-DE", viewport={"width": 1440, "height": 1000})
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(base)
        selector = page.locator(".language-selector")
        expect(selector).to_have_value("de")
        expect(page.locator("html")).to_have_attribute("lang", "de")
        expect(page.get_by_role("heading", name="Geschichten, die es geschafft haben.")).to_be_visible()
        for language in ("de", "fr", "it"):
            catalog = json.loads((LOCALES / f"{language}.json").read_text())
            selector.select_option(language)
            expect(page.locator("html")).to_have_attribute("lang", language)
            expect(page.get_by_role("heading", name=catalog["The stories that made it."])).to_be_visible()
            expect(page.get_by_role("button", name=catalog["Discover"], exact=True)).to_be_visible()
            expect(page.get_by_role("tab", name=catalog["🤯 Plot twists"])).to_be_visible()
            expect(page.locator(".premise p")).to_have_text(
                catalog["“The hotel handed me a crown instead of a room key.”"]
            )
            for width in (320, 390, 768, 1024, 1440):
                page.set_viewport_size({"width": width, "height": 1000})
                assert not page.evaluate("document.documentElement.scrollWidth > innerWidth"), (
                    language,
                    width,
                )
            page.set_viewport_size({"width": 1440, "height": 1000})
            page.reload()
            expect(selector).to_have_value(language)
        selector.select_option("en")

        def switch(name):
            page.locator(".demo-bar button").click()
            page.locator(".account-list button").filter(has_text=name).click()
            expect(page.get_by_role("dialog")).not_to_be_visible()

        switch("Alex")
        original = context.request.get(base + "/api/me").json()["settings"]
        try:
            for language in ("de", "fr", "it"):
                selector.select_option(language)
                expect(selector).to_be_enabled()
                for route in ("chains", "groups", "settings", "admin"):
                    page.goto(base + "/#" + route)
                    expect(page.locator(".page h1")).to_be_visible()
                    for width in (320, 390):
                        page.set_viewport_size({"width": width, "height": 844})
                        assert not page.evaluate("document.documentElement.scrollWidth > innerWidth"), (
                            language,
                            route,
                            width,
                        )
                    page.set_viewport_size({"width": 1440, "height": 1000})
            selector.select_option("fr")
            expect(selector).to_be_enabled()
            assert context.request.get(base + "/api/me").json()["settings"]["language"] == "fr"
            page.locator(".profile-button").click()
            expect(page.get_by_role("heading", name="Vos paramètres.")).to_be_visible()
            page.locator(".settings-page select").select_option("it")
            page.get_by_role("button", name="Enregistrer les préférences").click()
            expect(selector).to_have_value("it")
            expect(page.get_by_role("heading", name="Le tue impostazioni.")).to_be_visible()
            expect(page.locator(".toast")).to_contain_text("Preferenze salvate.")
            page.reload()
            expect(selector).to_have_value("it")
            page.get_by_role("button", name="Configurazione amministratore").click()
            expect(page.get_by_role("heading", name="Configurazione della piattaforma.")).to_be_visible()
            expect(page.get_by_role("button", name="Crea revisione")).to_be_visible()
            switch("Jamie")
            expect(selector).to_have_value("en")
            switch("Alex")
            expect(selector).to_have_value("it")
            page.locator(".new-chain-button").click()
            draft = f"Il mio frigorifero ha chiesto una vacanza. {uuid4().hex[:8]}"
            page.locator("#setup").fill(draft)
            selector.select_option("de")
            expect(selector).to_be_enabled()
            expect(page.locator("#setup")).to_have_value(draft)
            page.locator(".people-picker label").filter(has_text="Jamie").get_by_role("checkbox").check()
            page.get_by_role("button", name="Starten & weitergeben").click()
            page.wait_for_url("**/#story/*")
            expect(page.locator(".setup-entry p")).to_have_text(draft)
            selector.select_option("fr")
            expect(selector).to_be_enabled()
            expect(page.locator(".setup-entry p")).to_have_text(draft)
            page.get_by_role("button", name="Notifications", exact=True).click()
            expect(page.locator(".notification-panel")).to_contain_text(
                "Vous participez à une nouvelle histoire. Le premier passage se prépare."
            )
            page.get_by_role("button", name="Fermer les notifications").click()
            # A translated API error must survive a language switch without losing its meaning.
            page.route(
                "**/api/friends",
                lambda route: route.fulfill(
                    status=409,
                    content_type="application/json",
                    body='{"detail":"A friendship or request already exists"}',
                ),
            )
            page.get_by_role("button", name="Mes proches", exact=True).click()
            expect(page.get_by_role("alert")).to_have_text("Une amitié ou une demande existe déjà")
            selector.select_option("it")
            expect(page.get_by_role("alert")).to_have_text("Esiste già un’amicizia o una richiesta")
            page.unroute("**/api/friends")
            page.screenshot(path="/tmp/passit-italian.png", full_page=True)
            assert not errors, errors
        finally:
            context.request.put(base + "/api/me/settings", headers={"Origin": base}, data=original)
        browser.close()
        print(
            "Language smoke passed: all locales, mobile layout, browser/account persistence, admin, draft retention, unchanged story text, notifications and errors."
        )


if __name__ == "__main__":
    main()
