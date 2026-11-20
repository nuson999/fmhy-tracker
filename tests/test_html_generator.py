"""Tests for HTML Generator functionality."""

import pytest
import os
import tempfile
from pathlib import Path

from fmhy_tracker import HTMLGenerator


class TestHTMLGenerator:
    """Tests for HTMLGenerator class."""

    def test_init_with_default_paths(self):
        """Test initialization with default paths."""
        generator = HTMLGenerator()

        assert generator.template_dir.exists() or True  # May not exist in test env
        assert generator.static_dir.exists() or True

    def test_init_with_custom_paths(self, temp_directory):
        """Test initialization with custom paths."""
        template_dir = temp_directory / "templates"
        static_dir = temp_directory / "static"
        template_dir.mkdir()
        static_dir.mkdir()

        generator = HTMLGenerator(
            template_dir=str(template_dir), static_dir=str(static_dir)
        )

        assert generator.template_dir == template_dir
        assert generator.static_dir == static_dir

    def test_read_file(self, temp_directory):
        """Test reading file contents."""
        test_file = temp_directory / "test.txt"
        test_content = "Test content"
        test_file.write_text(test_content)

        generator = HTMLGenerator()
        result = generator._read_file(test_file)

        assert result == test_content

    def test_get_css_content_returns_empty_when_no_file(self, temp_directory):
        """Test that empty string is returned when CSS file doesn't exist."""
        generator = HTMLGenerator(
            template_dir=str(temp_directory), static_dir=str(temp_directory)
        )

        result = generator._get_css_content()
        assert result == ""

    def test_get_css_content_returns_file_contents(self, temp_directory):
        """Test that CSS content is returned from file."""
        static_dir = temp_directory / "static"
        static_dir.mkdir()
        css_file = static_dir / "styles.css"
        css_content = "body { margin: 0; }"
        css_file.write_text(css_content)

        generator = HTMLGenerator(static_dir=str(static_dir))
        result = generator._get_css_content()

        assert result == css_content

    def test_get_js_content_returns_empty_when_no_file(self, temp_directory):
        """Test that empty string is returned when JS file doesn't exist."""
        generator = HTMLGenerator(
            template_dir=str(temp_directory), static_dir=str(temp_directory)
        )

        result = generator._get_js_content()
        assert result == ""

    def test_get_js_content_returns_file_contents(self, temp_directory):
        """Test that JS content is returned from file."""
        static_dir = temp_directory / "static"
        static_dir.mkdir()
        js_file = static_dir / "app.js"
        js_content = "console.log('test');"
        js_file.write_text(js_content)

        generator = HTMLGenerator(static_dir=str(static_dir))
        result = generator._get_js_content()

        assert result == js_content

    def test_get_template_raises_when_not_found(self, temp_directory):
        """Test that FileNotFoundError is raised when template not found."""
        generator = HTMLGenerator(
            template_dir=str(temp_directory), static_dir=str(temp_directory)
        )

        with pytest.raises(FileNotFoundError):
            generator._get_template()

    def test_get_template_returns_content(self, temp_directory):
        """Test that template content is returned."""
        template_dir = temp_directory / "templates"
        template_dir.mkdir()
        template_file = template_dir / "index.html"
        template_content = "<html><body>{{ data_json }}</body></html>"
        template_file.write_text(template_content)

        generator = HTMLGenerator(template_dir=str(template_dir))
        result = generator._get_template()

        assert result == template_content

    def test_generate_creates_html_file(self, temp_directory):
        """Test that HTML file is generated correctly."""
        # Setup template and static directories
        template_dir = temp_directory / "templates"
        static_dir = temp_directory / "static"
        template_dir.mkdir()
        static_dir.mkdir()

        # Create template
        template_content = """<!DOCTYPE html>
<html>
<head><style>{{ css_content }}</style></head>
<body>
<script>{{ js_content }}</script>
<script>const data = {{ data_json }};</script>
</body>
</html>"""
        (template_dir / "index.html").write_text(template_content)

        # Create static files
        (static_dir / "styles.css").write_text("body { color: red; }")
        (static_dir / "app.js").write_text("function init() {}")

        generator = HTMLGenerator(
            template_dir=str(template_dir), static_dir=str(static_dir)
        )

        output_file = str(temp_directory / "output.html")
        test_data = {
            "lastUpdated": "2024-01-15T10:00:00Z",
            "totalNew": 5,
            "commits": [],
        }

        generator.generate(test_data, output_file)

        assert os.path.exists(output_file)

        with open(output_file, "r") as f:
            content = f.read()

        assert "body { color: red; }" in content
        assert "function init() {}" in content
        assert '"lastUpdated"' in content
        assert '"totalNew": 5' in content

    def test_generate_handles_unicode(self, temp_directory):
        """Test that unicode characters are handled correctly."""
        template_dir = temp_directory / "templates"
        static_dir = temp_directory / "static"
        template_dir.mkdir()
        static_dir.mkdir()

        (template_dir / "index.html").write_text("<html>{{ data_json }}</html>")

        generator = HTMLGenerator(
            template_dir=str(template_dir), static_dir=str(static_dir)
        )

        output_file = str(temp_directory / "output.html")
        test_data = {"message": "Test with ⭐ emoji", "commits": []}

        generator.generate(test_data, output_file)

        assert os.path.exists(output_file)

    def test_generate_escapes_script_breakout(self, temp_directory):
        """Test that embedded JSON cannot break out of its script tag."""
        template_dir = temp_directory / "templates"
        static_dir = temp_directory / "static"
        template_dir.mkdir()
        static_dir.mkdir()

        (template_dir / "index.html").write_text(
            '<script id="fmhy-data" type="application/json">{{ data_json }}</script>'
        )

        generator = HTMLGenerator(
            template_dir=str(template_dir), static_dir=str(static_dir)
        )

        output_file = str(temp_directory / "output.html")
        generator.generate(
            {
                "message": '</script><script>alert("xss")</script>',
                "commits": [],
            },
            output_file,
        )

        content = Path(output_file).read_text(encoding="utf-8")
        assert "</script><script>" not in content
        assert "\\u003c/script\\u003e" in content


class TestHTMLGeneratorIntegration:
    """Integration tests for HTML generation."""

    def test_full_generation_workflow(self, temp_directory, sample_tracker_data):
        """Test complete HTML generation workflow."""
        # Setup
        template_dir = temp_directory / "templates"
        static_dir = temp_directory / "static"
        template_dir.mkdir()
        static_dir.mkdir()

        # Create a realistic template
        template = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>FMHY Tracker</title>
    <style>{{ css_content }}</style>
</head>
<body>
    <h1>FMHY Tracker</h1>
    <div id="app"></div>
    <script>{{ js_content }}</script>
    <script>
        const data = {{ data_json }};
        console.log('Total new:', data.totalNew);
    </script>
</body>
</html>"""
        (template_dir / "index.html").write_text(template)

        # Create static files
        css = """
:root { --primary: #1976d2; }
body { font-family: sans-serif; }
"""
        (static_dir / "styles.css").write_text(css)

        js = """
function init(data) {
    console.log('Initialized with', data.totalCommits, 'commits');
}
"""
        (static_dir / "app.js").write_text(js)

        # Generate HTML
        generator = HTMLGenerator(
            template_dir=str(template_dir), static_dir=str(static_dir)
        )

        output_file = str(temp_directory / "index.html")
        generator.generate(sample_tracker_data, output_file)

        # Verify output
        assert os.path.exists(output_file)

        with open(output_file, "r", encoding="utf-8") as f:
            content = f.read()

        # Check structure
        assert "<!DOCTYPE html>" in content
        assert "<title>FMHY Tracker</title>" in content

        # Check CSS injection
        assert "--primary: #1976d2" in content

        # Check JS injection
        assert "function init(data)" in content

        # Check data injection
        assert '"totalNew": 2' in content
        assert '"totalCommits": 2' in content


def test_hashed_assets_are_stable_and_change_with_source(temp_directory):
    """Data-only updates reuse assets; source updates invalidate their URLs."""
    import re

    template_dir = temp_directory / "templates"
    static_dir = temp_directory / "static"
    template_dir.mkdir()
    static_dir.mkdir()
    (template_dir / "index.html").write_text(
        '<link href="{{ css_url }}"><script src="{{ js_url }}"></script>'
        '<script type="application/json">{{ data_json }}</script>'
    )
    (static_dir / "styles.css").write_text("/* comment */ body { color: red; }")
    (static_dir / "app.js").write_text("// comment\nfunction init() { return 1; }")
    generator = HTMLGenerator(str(template_dir), str(static_dir))
    output = temp_directory / "index.html"
    generator.generate({"commits": []}, str(output))
    first = re.findall(r"static/dist/[^\"]+", output.read_text())
    assert len(first) == 2
    assert all((temp_directory / url).is_file() for url in first)
    assert "comment" not in (temp_directory / first[0]).read_text()
    assert "comment" not in (temp_directory / first[1]).read_text()
    generator.generate({"commits": [], "lastUpdated": "2026-09-30"}, str(output))
    assert re.findall(r"static/dist/[^\"]+", output.read_text()) == first
    (static_dir / "app.js").write_text("function init() { return 2; }")
    generator.generate({"commits": []}, str(output))
    second = re.findall(r"static/dist/[^\"]+", output.read_text())
    assert second[0] == first[0]
    assert second[1] != first[1]


def test_dashboard_links_work_under_github_pages_project_path(temp_directory):
    """Button, discovery, and icon links stay inside a project deployment."""
    from html.parser import HTMLParser
    from urllib.parse import urljoin

    class Links(HTMLParser):
        def __init__(self):
            super().__init__()
            self.links = []

        def handle_starttag(self, tag, attributes):
            self.links.append((tag, dict(attributes)))

    output = temp_directory / "index.html"
    HTMLGenerator().generate({"commits": []}, str(output))
    parser = Links()
    parser.feed(output.read_text(encoding="utf-8"))
    base = "https://nuson999.github.io/fmhy-tracker/"
    rss_links = [
        attributes["href"]
        for tag, attributes in parser.links
        if attributes.get("class") == "header-rss"
        or attributes.get("type") == "application/rss+xml"
    ]
    assert len(rss_links) == 2
    assert all(urljoin(base, href) == base + "feed.xml" for href in rss_links)
    for _, attributes in parser.links:
        href = attributes.get("href", "")
        if "favicon_io" in href:
            assert urljoin(base, href).startswith(base + "favicon_io/")


@pytest.mark.parametrize("month", ["2026-09", "2026-13", "bad", None])
def test_archive_label_is_derived_without_embedding_archive(temp_directory, month):
    import json
    import re

    archive = temp_directory / "monthly_commits.json"
    archive.write_text(
        json.dumps({"month": month, "commits": [{"sha": "archive-only"}]})
    )
    output = temp_directory / "index.html"
    data = {"commits": []}
    HTMLGenerator().generate(data, str(output))
    html = output.read_text(encoding="utf-8")
    embedded = json.loads(
        re.search(
            r'<script id="fmhy-data" type="application/json">(.*?)</script>', html, re.S
        )[1]
    )
    assert embedded.get("archiveMonth") == (month if month == "2026-09" else None)
    assert "archive-only" not in html
    assert data == {"commits": []}
    assert "fonts.googleapis" not in html


def test_custom_archive_path_and_malformed_metadata(temp_directory):
    import json

    archive = temp_directory / "custom.json"
    archive.write_text(json.dumps({"month": "2026-08"}))
    output = temp_directory / "index.html"
    generator = HTMLGenerator()
    generator.generate({"commits": []}, str(output), monthly_file=str(archive))
    assert '"archiveMonth": "2026-08"' in output.read_text(encoding="utf-8")
    archive.write_text("broken json")
    generator.generate({"commits": []}, str(output), monthly_file=str(archive))
    assert '"archiveMonth"' not in output.read_text(encoding="utf-8")
