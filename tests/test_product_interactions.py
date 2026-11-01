from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "growthevo" / "web" / "static"


def read(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


def test_shell_controls_have_real_handlers() -> None:
    index = read("index.html")
    app = read("app.js")

    required_ids = {
        "sidebar-collapse",
        "date-filter",
        "channel-filter",
        "notification-open",
        "profile-open",
        "agent-close",
        "agent-mode",
        "agent-attach",
        "agent-voice",
        "product-intro",
        "intro-close",
    }
    for control_id in required_ids:
        assert f'id="{control_id}"' in index
        assert f"$('#{control_id}')" in app

    assert "renderCommandResults(event.target.value)" in app
    assert "document.body.classList.add('agent-collapsed')" in app
    assert "document.body.classList.toggle('sidebar-collapsed')" in app
    assert "$('#agent-file-input').click()" in app
    assert "window.SpeechRecognition||window.webkitSpeechRecognition" in app


def test_agent_is_reversible_and_renders_visible_feedback() -> None:
    app = read("app.js")

    assert "function closeAgent()" in app
    assert "function openAgent()" in app
    assert "appendAgentMessage('user',goal)" in app
    assert "appendAgentMessage('agent',demoAgentResponse(goal))" in app
    assert "const target=$('#agent-achievement')" in app
    assert "执行与演进观测" in app
    assert "api(\'/api/harness/runs\')" in app
    assert "api(\'/api/evolution/candidates\')" in app


def test_dashboard_controls_change_state_or_navigate() -> None:
    dashboard = read("dashboard-page.js")

    assert 'data-dashboard-metric="revenue"' in dashboard
    assert 'data-dashboard-metric="roi"' in dashboard
    assert 'id="trend-granularity"' in dashboard
    assert 'data-dashboard-filter="Campaign"' in dashboard
    assert 'data-dashboard-filter="Experiment"' in dashboard
    assert 'data-go="realtime"' in dashboard
    assert 'class="task-row" type="button" data-go=' in dashboard
    assert 'class="quick-card" type="button" data-go=' in dashboard
    assert "$('#channel-details').onclick=()=>go('evidence')" in dashboard
    assert "bindProductActions();" in dashboard


def test_strategy_rows_have_actionable_controls() -> None:
    views = read("views.js")

    assert 'class="action-view" type="button" data-go="${route}"' in views
    assert 'class="row-more" type="button" data-campaign-more=' in views
    assert 'data-campaign-route="${route}"' in views
    assert 'data-toast=' not in views
    assert "trendChart(values,options={})" in views


def test_real_browser_smoke_covers_primary_interactions() -> None:
    smoke = (ROOT / "scripts" / "browser_interaction_smoke.js").read_text(encoding="utf-8")

    for marker in (
        "#sidebar-collapse",
        "#date-filter",
        "#channel-filter",
        "#command-open",
        "[data-dashboard-metric=\"roi\"]",
        "[data-dashboard-filter=\"Experiment\"]",
        ".quick-card[data-go=\"opportunities\"]",
        "#agent-close",
        "#agent-form",
        "#product-intro",
        "INTERACTION_SMOKE_PASS",
    ):
        assert marker in smoke
