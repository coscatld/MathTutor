"""Browser student path against a separately started, disposable product runtime.

Requires Python Playwright. No API/WS mocks or live model credentials are used.
Pass a backend with a fresh data directory; this script creates conversations
and skips provider onboarding in that test runtime.
"""
import argparse
import json
import re
from pathlib import Path
from time import time
from uuid import uuid4

from playwright.sync_api import expect, sync_playwright


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:3197")
    parser.add_argument("--api", default="http://127.0.0.1:8197")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    findings = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.set_default_timeout(20000)
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        assert page.request.post(args.api + "/api/v2/math-tutor/desktop/settings/onboarding/skip").ok

        def snapshot(session):
            response = page.request.get(args.api + "/api/v2/math-tutor/sessions/" + session)
            if response.status == 404:
                return {}
            assert response.ok, response.text()
            return response.json()

        def wait_for(session, predicate):
            deadline = time() + 20
            while time() < deadline:
                state = snapshot(session)
                if predicate(state):
                    expect(page.get_by_role("textbox", name="聊天输入")).to_be_enabled()
                    return state
                page.wait_for_timeout(100)
            raise AssertionError("Expected state was not reached: " + json.dumps(state, ensure_ascii=False))

        def send(text, *, write=False):
            if write:
                page.get_by_role("region", name="下一步学习").get_by_role("button", name="我来写", exact=True).click()
            box = page.get_by_role("textbox", name="聊天输入")
            expect(box).to_be_enabled()
            box.fill(text)
            box.press("Enter")

        def capture(name):
            page.screenshot(path=str(args.output / name), full_page=True)

        try:
            session = "browser-student-" + uuid4().hex[:8]
            page.goto(args.base + "/math-tutor?session=" + session)
            page.wait_for_load_state("networkidle")
            welcome = page.get_by_role("region", name="开始数学辅导")
            expect(welcome).to_be_visible()
            expect(welcome.get_by_role("button")).to_have_count(3)
            capture("01-welcome-desktop.png")
            welcome.get_by_role("button", name=re.compile("先练移项")).click()
            original = wait_for(session, lambda s: s.get("state") == "awaiting_attempt")
            step = page.get_by_role("region", name="下一步学习")
            expect(step).to_be_visible()
            for label in ("提示", "我来写", "看一步", "再来一道"):
                expect(step.get_by_role("button", name=label, exact=True)).to_be_visible()
            step.get_by_role("button", name="我来写", exact=True).click()
            expect(page.get_by_role("textbox", name="聊天输入")).to_be_focused()
            step.get_by_role("button", name="提示", exact=True).click()
            wait_for(session, lambda s: s.get("effective_assistance_level", 0) > 0)
            capture("02-inline-next-step.png")
            findings.append("Three starter problems, inline actions and composer focus work through real API/WS.")

            step.get_by_role("button", name="我懂了，检查一下", exact=True).click()
            checking = wait_for(session, lambda s: (s.get("problem_context") or {}).get("understanding_check") is True)
            assert checking["cycle_id"] != original["cycle_id"]
            expect(step.get_by_role("heading", name="用一道小题检查一下")).to_be_visible()
            capture("03-understanding-check.png")
            text = checking["problem_context"]["display_text"]
            equation = re.search(r"3\s*z\s*\+\s*2\s*=\s*(\d+)", text.replace("\\", ""))
            assert equation, text
            rhs = int(equation.group(1)) - 2
            send(f"3z={rhs}", write=True)
            wait_for(session, lambda s: s["state_version"] > checking["state_version"])
            assert snapshot(session)["cycle_id"] == checking["cycle_id"], "An intermediate step must not finish the check."
            send(f"z={rhs // 3}", write=True)
            resumed = wait_for(session, lambda s: s.get("cycle_id") == original["cycle_id"])
            assert resumed["problem_context"]["lifecycle"].lower() == "active"
            capture("04-return-to-original.png")
            page.reload()
            page.wait_for_load_state("networkidle")
            expect(step).to_be_visible()
            assert snapshot(session)["cycle_id"] == original["cycle_id"]
            findings.append("Understanding check takes two steps, returns to the unfinished original and survives reload.")

            page.set_viewport_size({"width": 390, "height": 844})
            page.emulate_media(reduced_motion="reduce")
            expect(step.get_by_role("button", name="我来写", exact=True)).to_be_visible()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), "Narrow screen overflow"
            capture("05-inline-mobile.png")
            page.set_viewport_size({"width": 1280, "height": 800})
            session = "browser-unsupported-" + uuid4().hex[:8]
            page.goto(args.base + "/math-tutor?session=" + session)
            page.wait_for_load_state("networkidle")
            send("解不等式 2x+3>7")
            offered = wait_for(session, lambda s: s.get("recovery_problem") is not None)
            recovery = page.get_by_role("region", name="相关的可核验练习")
            expect(recovery).to_be_visible()
            capture("06-unsupported-recovery.png")
            assert offered.get("problem_context") is None
            page.reload()
            page.wait_for_load_state("networkidle")
            expect(recovery).to_be_visible()
            recovery.get_by_role("button", name="练这道题", exact=True).click()
            accepted = wait_for(session, lambda s: s.get("state") == "awaiting_attempt" and s.get("problem_context") is not None)
            assert accepted.get("recovery_problem") is None
            expect(recovery).to_have_count(0)
            findings.append("Unsupported input offers a durable verified exercise and switches only when the student chooses it.")
            findings.append("390px viewport, reduced motion and reload preserve the student path without horizontal overflow.")
            assert not errors, errors
            (args.output / "browser-report.json").write_text(json.dumps({"passed": True, "findings": findings, "page_errors": errors}, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps({"passed": True, "findings": findings, "output": str(args.output)}, ensure_ascii=False))
        except Exception:
            capture("failure.png")
            (args.output / "failure-dom.html").write_text(page.content(), encoding="utf-8")
            raise
        finally:
            browser.close()


if __name__ == "__main__":
    main()
