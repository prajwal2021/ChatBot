from app.extract import extract

PAGE = "<p>" + "Real page text about modules and how to add them. " * 6 + "</p>"


def test_skip_link_is_not_taken_for_the_main_area():
    html = f'<html><body><a id="skip-to-main-content" href="#m">Skip to main content</a><h1>TEKS</h1>{PAGE}</body></html>'
    d = extract(html, "https://example.org/")
    assert d["sections"] and "Real page text" in d["text"]


def test_noscript_fallback_only_when_nothing_else_is_readable():
    app_shell = f'<html><body><div id="app"></div><noscript><article><h1>How do I add a module?</h1>{PAGE}</article></noscript></body></html>'
    d = extract(app_shell, "https://example.org/kb/1")
    assert d["title"] == "How do I add a module?" and "Real page text" in d["text"]

    normal = f'<html><body><main><h1>Normal</h1>{PAGE}</main><noscript><p>{"Enable JavaScript please. " * 20}</p></noscript></body></html>'
    d = extract(normal, "https://example.org/")
    assert "Enable JavaScript" not in d["text"] and "Real page text" in d["text"]
