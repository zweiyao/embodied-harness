# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Browser journeys against a disposable, read-only workbench."""

import json
import os
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from rpent.dashboard.server import DashboardServer
from rpent.dashboard.state import DashboardState
from tests.unit_tests.rpent.dashboard.test_server_contracts import DASHBOARD_SPEC
from tests.unit_tests.rpent.dashboard.test_workbench import bench as bench

INSTRUCTION = "Move the synthetic block."


@pytest.fixture(autouse=True)
def isolated_configuration(monkeypatch):
    for key in ("RPENT_DASHBOARD_SETUP", "RPENT_TOOL_CATALOG"):
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def workbench_url(bench):
    bench.config["setup"] = {
        "profiles": [
            {"robot": "libero", "label": "LIBERO", "suites": {"demo": ["A", "B"]}}
        ]
    }
    root = bench.root / "session/tasks/0001_demo"
    root.mkdir(parents=True)
    for filename, data in {
        "dashboard_config.json": {
            "model": "fixture",
            "task": {"suite": "demo", "task": 0, "seed": 0},
        },
        "outcome.json": {"status": "completed", "environment_success": True},
        "states.json": {
            "steps": [
                {"step_idx": 0, "extras": {"task_language": INSTRUCTION}},
                {"step_idx": 1, "command": {"action": "observe"}},
            ]
        },
    }.items():
        (root / filename).write_text(json.dumps(data))
    state = DashboardState(
        output_dir=bench.root / "session", dashboard_spec=DASHBOARD_SPEC
    )
    state.workbench = bench
    state.shared_services_ready()
    server = DashboardServer(
        state=state, robot_name="libero", planner="api", model="fixture"
    )
    try:
        yield server.start()
    finally:
        if server._server is not None:
            server._server.should_exit = True


@pytest.fixture
def browser_page(workbench_url, tmp_path, request):
    from playwright.sync_api import sync_playwright

    root = Path(os.environ.get("VERIFY_APP_ARTIFACTS", tmp_path))
    root.mkdir(parents=True, exist_ok=True)
    evidence = Path(tempfile.mkdtemp(prefix=request.node.name + "-", dir=root))
    errors = []
    origin = urlsplit(workbench_url)
    with sync_playwright() as pw, pw.chromium.launch() as browser:
        context = browser.new_context(
            service_workers="block", viewport={"width": 1280, "height": 900}
        )
        context.tracing.start(screenshots=True, snapshots=True, sources=True)
        page = context.new_page()
        page.set_default_timeout(7000)

        def guard(route):
            req = route.request
            url = urlsplit(req.url)
            if (url.scheme, url.netloc) != (
                origin.scheme,
                origin.netloc,
            ) or req.method != "GET":
                errors.append(f"blocked {req.method} {url.path}")
                route.abort()
            else:
                route.continue_()

        context.route("**/*", guard)
        page.on(
            "console",
            lambda msg: (
                errors.append("console: " + msg.text) if msg.type == "error" else None
            ),
        )
        page.on("pageerror", lambda exc: errors.append(f"page: {exc}"))
        page.on(
            "requestfailed",
            lambda req: errors.append(
                f"request: {req.failure} {urlsplit(req.url).path}"
            ),
        )
        page.on(
            "response",
            lambda res: (
                errors.append(f"HTTP {res.status} {urlsplit(res.url).path}")
                if res.status >= 400
                else None
            ),
        )
        try:
            yield page
        finally:
            try:
                page.screenshot(path=evidence / "screen.png")
            finally:
                (evidence / "browser-errors.json").write_text(
                    json.dumps(errors, ensure_ascii=False, indent=2)
                )
                context.tracing.stop(path=evidence / "trace.zip")
                context.close()
            assert not errors, f"{errors} (evidence: {evidence})"


def test_setup_preview(workbench_url, browser_page):
    from playwright.sync_api import expect

    page = browser_page
    page.goto(workbench_url)
    expect(page.locator("#status")).to_contain_text("服务已就绪")
    page.locator("#task").select_option("1")
    page.locator("#seed").select_option("3")
    expect(page.locator("#command")).to_have_text("/rpent-task demo 1 3")
    expect(page.locator("#enter")).to_be_disabled()


def test_tool_details(workbench_url, browser_page):
    from playwright.sync_api import expect

    page = browser_page
    page.goto(workbench_url + "/tools")
    expect(page.locator("#status")).to_contain_text("目录只读查看")
    card = page.locator("article").filter(has=page.get_by_text("move_to", exact=True))
    card.get_by_role("button").click()
    dialog = page.get_by_role("dialog")
    expect(dialog.get_by_role("heading", name="move_to", exact=True)).to_be_visible()
    expect(dialog.get_by_role("heading", name="参数", exact=True)).to_be_visible()
    dialog.get_by_role("button", name="关闭").click()
    expect(dialog).to_have_count(0)


def test_run_replay(workbench_url, browser_page):
    from playwright.sync_api import expect

    page = browser_page
    page.goto(workbench_url + "/runs")
    expect(page.locator("#status")).to_contain_text("1 次实验")
    page.get_by_text("demo / task 0 · A · 1 条记录", exact=True).click()
    expect(page.locator(".task-instruction")).to_contain_text(INSTRUCTION)
    expect(page.get_by_text("任务成功", exact=True)).to_be_visible()
    page.get_by_role("link", name="查看过程").click()
    expect(page.locator("#status")).to_contain_text("历史实验")
    expect(page.get_by_text("官方成功：是", exact=False)).to_be_visible()
    expect(page.get_by_role("heading", name="第 1 步 · observe")).to_be_visible()
    page.get_by_role("button", name="0 初始").click()
    expect(page.get_by_role("heading", name="第 0 步 · 初始状态")).to_be_visible()


def test_console_stream(workbench_url, browser_page):
    from playwright.sync_api import expect

    page = browser_page
    page.goto(workbench_url + "/console", wait_until="domcontentloaded")
    expect(page.locator("#connMeta")).to_contain_text("live")
    expect(page.locator("#runIdentity")).to_have_text("尚未开始实验")
    expect(page.locator("#abortExperiment")).to_be_disabled()
