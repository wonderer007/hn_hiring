from hn_ingest.html_text import html_to_text


def test_plain_text_passthrough():
    assert html_to_text("Hello world") == "Hello world"


def test_strips_tags():
    assert html_to_text("<b>bold</b> text") == "bold text"


def test_link_preserved_with_url():
    result = html_to_text('<a href="https://example.com">Apply here</a>')
    assert "Apply here" in result
    assert "https://example.com" in result


def test_link_no_href():
    result = html_to_text('<a>just text</a>')
    assert result == "just text"


def test_p_tag_adds_newline():
    result = html_to_text("<p>First</p><p>Second</p>")
    assert "First" in result
    assert "Second" in result
    assert "\n" in result


def test_br_adds_newline():
    result = html_to_text("line1<br>line2")
    assert "\n" in result


def test_entity_decoding():
    assert "&amp;" not in html_to_text("AT&amp;T")
    assert "AT&T" in html_to_text("AT&amp;T")


def test_html_entities():
    assert html_to_text("&lt;b&gt;") == "<b>"


def test_nbsp():
    result = html_to_text("hello&nbsp;world")
    assert "hello" in result
    assert "world" in result


def test_nested_tags():
    result = html_to_text("<p><b>Title:</b> some <i>text</i></p>")
    assert "Title:" in result
    assert "some" in result
    assert "text" in result


def test_empty_string():
    assert html_to_text("") == ""


def test_none_like_empty():
    assert html_to_text("") == ""


def test_multiple_links():
    html = '<a href="http://a.com">A</a> and <a href="http://b.com">B</a>'
    result = html_to_text(html)
    assert "http://a.com" in result
    assert "http://b.com" in result
    assert "A" in result
    assert "B" in result


def test_strips_script_content():
    result = html_to_text("<p>Hello</p><script>bad();</script><p>World</p>")
    assert "Hello" in result
    assert "World" in result
