from pathlib import Path


STARTUP_PAGE = Path(__file__).parents[1] / "desktop" / "ui" / "index.html"


def test_startup_page_reports_one_ga4_page_view_per_page_session():
    source = STARTUP_PAGE.read_text(encoding="utf-8")

    assert "__FREELLM_GA_MEASUREMENT_ID__" in source
    assert "https://www.googletagmanager.com/gtag/js?id=" in source
    assert "send_page_view: false" in source
    assert "event', 'page_view'" in source
    assert "freellm_ga_page_view_sent" in source


def test_startup_page_skips_google_analytics_without_measurement_id():
    source = STARTUP_PAGE.read_text(encoding="utf-8")

    assert "if (!GA_MEASUREMENT_ID) return;" in source
