"""Focused Chromium pass through the stock webclient's actual input widget."""

import re
import secrets
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

from .client import visible


def run_browser(session, timeout=30):
    host = session.host
    diagnostics = {"console_errors": [], "page_errors": [], "failed_requests": [], "websockets": []}
    results = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        contexts = []
        pages = {}
        try:
            for actor in ("browser", "browser-observer"):
                context = browser.new_context(viewport={"width": 1440, "height": 900})
                context.set_default_timeout(timeout * 1000)
                contexts.append(context)
                page = context.new_page()
                pages[actor] = page
                page.on("pageerror", lambda error: diagnostics["page_errors"].append(str(error)))
                page.on(
                    "console",
                    lambda message: (
                        diagnostics["console_errors"].append(message.text)
                        if message.type == "error"
                        else None
                    ),
                )
                page.on(
                    "requestfailed",
                    lambda request: diagnostics["failed_requests"].append(
                        {"url": request.url, "error": request.failure}
                    ),
                )

                def websocket_open(socket, actor=actor):
                    diagnostics["websockets"].append(socket.url)
                    socket.on(
                        "framereceived",
                        lambda payload: host.evidence.event(actor, "receive", str(payload)),
                    )
                    socket.on(
                        "framesent",
                        lambda payload: host.evidence.event(actor, "send", str(payload)),
                    )

                page.on("websocket", websocket_open)
                response = page.goto(f"http://127.0.0.1:{host.ports['http']}/webclient/")
                assert response.status == 200
                expect(page.locator("body")).to_contain_text(
                    re.compile(r"[Cc]onnect|\[Placeholder\]")
                )
                spec = host.credentials[actor]
                field = page.locator(
                    "textarea.inputfield:visible, textarea#inputfield:visible"
                ).first
                field.fill(f"connect {spec['name']} {spec['password']}")
                field.press("Enter")
                expect(page.locator("body")).to_contain_text("Playtest browser laboratory")
                field.fill("")
            results.append(
                {
                    "name": "browser: anonymous webclient and real password login in independent contexts",
                    "passed": True,
                }
            )
            page = pages["browser"]
            observer = pages["browser-observer"]

            def command(text, expected):
                field = page.locator(
                    "textarea.inputfield:visible, textarea#inputfield:visible"
                ).first
                token = secrets.token_hex(8)
                field.fill(f"+playtest/arm {token}")
                field.press("Enter")
                expect(page.locator("body")).to_contain_text(token)
                cursor = host.evidence.cursor
                field.fill(text)
                field.press("Enter")
                # Existing Telnet staff receives the same dispatch boundary. Wait
                # for the DOM as well: socket receipt alone is not UI rendering.
                session.clients["staff"].frame("boundary", token, cursor)
                expect(page.locator("body")).to_contain_text(re.compile(expected, re.I))
                expect(observer.locator("body")).to_contain_text(token)
                return visible(page.locator("body").inner_text()), visible(
                    observer.locator("body").inner_text()
                )

            command("look", "Playtest browser laboratory")
            own, other = command("+sheet", "Charisma")
            assert "B ++" in own and "B ++" not in other
            command("+scene/open Live browser laboratory", "opened|created|Scene #")
            command("+scene/privacy public", "Public")
            command("+test/set A=Charisma/Performance~Browser audience", "Browser audience")
            own, other = command("+test #1=Charisma/Performance", "Narrow Success")
            assert "Narrow Success" in other
            for private in ("B ++", "55.2", '"roll"', "actor_score"):
                assert private not in other
            state = session.snapshot()
            browser_id = state["actors"]["browser"]["id"]
            record = next(row for row in state["checks"] if row["character_id"] == browser_id)
            assert record["outcome_key"] == "narrow_success"
            assert len(diagnostics["websockets"]) == 2, diagnostics
            for url in diagnostics["websockets"]:
                address = urlsplit(url)
                assert address.scheme == "ws" and address.hostname == "127.0.0.1", url
                assert address.port == host.ports["websocket"], url
            results.append(
                {
                    "name": "browser: look, private sheet and public RP outcome over localhost WebSocket",
                    "passed": True,
                }
            )
            for name, viewport in (
                ("desktop", {"width": 1440, "height": 900}),
                ("narrow", {"width": 390, "height": 844}),
            ):
                page.set_viewport_size(viewport)
                assert all(
                    spec["password"] not in page.locator("body").inner_text()
                    for spec in host.credentials.values()
                ), "Credential visible in screenshot"
                page.screenshot(path=str(host.artifacts / f"webclient-{name}.png"), full_page=True)
                width = page.evaluate(
                    "({viewport: innerWidth, content: document.documentElement.scrollWidth})"
                )
                assert width["content"] <= width["viewport"] + 1, (
                    f"Webclient {name} overflow: {width}"
                )
            scene_page = contexts[1].new_page()
            response = scene_page.goto(
                f"http://127.0.0.1:{host.ports['http']}/scenes/{record['scene_id']}/"
            )
            assert response.status == 200
            expect(scene_page.locator("body")).to_contain_text("Narrow Success")
            content = scene_page.locator("body").inner_text()
            for private in ("B ++", "55.2", '"roll"', "actor_score"):
                assert private not in content
            scene_page.screenshot(path=str(host.artifacts / "scene-public.png"), full_page=True)
            assert not diagnostics["page_errors"], diagnostics
            assert not diagnostics["console_errors"], diagnostics
            assert not diagnostics["failed_requests"], diagnostics
            results.append(
                {
                    "name": "browser: desktop/narrow rendering, public scene privacy and browser diagnostics",
                    "passed": True,
                }
            )
        finally:
            host.evidence.write("browser-diagnostics.json", diagnostics)
            for actor, page in pages.items():
                (host.artifacts / f"browser-dom-{actor}.txt").write_text(
                    host.evidence.clean(page.locator("body").inner_text()), encoding="utf-8"
                )
            for context in contexts:
                context.close()
            browser.close()
    return results
