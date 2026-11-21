"""Tests for RSS feed generation."""

import pytest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

from fmhy_tracker.rss_generator import RSSGenerator


@pytest.fixture
def rss_generator():
    """Create an RSS generator instance."""
    return RSSGenerator()


@pytest.fixture
def sample_data_with_commits():
    """Sample tracker data with multiple commits (ordered oldest to newest, like real data)."""
    return {
        "lastUpdated": "2024-01-15T10:30:00Z",
        "totalAdded": 5,
        "totalRemoved": 2,
        "totalNew": 3,
        "totalUpdated": 2,
        "totalCommits": 3,
        "commits": [
            {
                "sha": "ghi789jkl012345678901234567890cdef",
                "date": "2024-01-13T08:00:00Z",
                "message": "Remove deprecated links",
                "added": [],
                "removed": [
                    {
                        "link": "* ⭐ **[DeadSite](https://dead.example.com)** - No longer available",
                        "source": "misc",
                        "type": "removed",
                    }
                ],
            },
            {
                "sha": "def456ghi789012345678901234567890bcde",
                "date": "2024-01-14T09:00:00Z",
                "message": "Update tools and remove old site",
                "added": [
                    {
                        "link": "* ⭐ **[AudioApp](https://audio.example.com)** - Audio player",
                        "source": "audio",
                        "type": "new",
                    }
                ],
                "removed": [
                    {
                        "link": "* [OldSite](https://old.example.com) - Deprecated",
                        "source": "video",
                        "type": "removed",
                    }
                ],
            },
            {
                "sha": "abc123def456789012345678901234567890abcd",
                "date": "2024-01-15T10:30:00Z",
                "message": "Add new streaming sites",
                "added": [
                    {
                        "link": "* ⭐ **[StreamSite](https://stream.example.com)** - Best streaming",
                        "source": "video",
                        "type": "new",
                    },
                    {
                        "link": "* [ToolName](https://tool.example.com) - A useful tool",
                        "source": "tools",
                        "type": "updated",
                    },
                ],
                "removed": [],
            },
        ],
    }


@pytest.fixture
def empty_data():
    """Sample tracker data with no commits."""
    return {
        "lastUpdated": "2024-01-15T10:30:00Z",
        "totalAdded": 0,
        "totalRemoved": 0,
        "totalNew": 0,
        "totalUpdated": 0,
        "totalCommits": 0,
        "commits": [],
    }


class TestRSSGenerator:
    """Tests for RSSGenerator class."""

    def test_initialization(self, rss_generator):
        """Test RSS generator initializes with correct defaults."""
        assert rss_generator.title == "FMHY Tracker - Changes Feed"
        assert rss_generator.link == "https://nuson999.github.io/fmhy-tracker"
        assert "FMHY" in rss_generator.description
        assert rss_generator.repo == "fmhy/edit"

    def test_initialization_accepts_custom_repo(self):
        """Test RSS commit links follow tracker-level repository overrides."""
        rss_generator = RSSGenerator(repo="owner/custom")

        assert rss_generator.repo == "owner/custom"

    def test_format_rfc822_date(self, rss_generator):
        """Test ISO to RFC 822 date conversion."""
        iso_date = "2024-01-15T10:30:00Z"
        rfc822_date = rss_generator._format_rfc822_date(iso_date)

        # Should contain day, month, year and time
        assert "2024" in rfc822_date
        assert "Jan" in rfc822_date
        assert "10:30:00" in rfc822_date
        assert "GMT" in rfc822_date

    def test_format_rfc822_date_with_timezone(self, rss_generator):
        """Test RFC 822 date conversion with timezone offset."""
        iso_date = "2024-01-15T10:30:00+00:00"
        rfc822_date = rss_generator._format_rfc822_date(iso_date)

        assert "2024" in rfc822_date
        assert "Jan" in rfc822_date

    def test_format_rfc822_date_invalid(self, rss_generator):
        """Invalid commit dates do not become the current time."""
        assert rss_generator._format_rfc822_date("invalid-date") is None

    def test_invalid_commit_date_does_not_emit_pubdate(
        self, rss_generator, temp_directory
    ):
        output = temp_directory / "feed.xml"
        rss_generator.generate(
            {
                "commits": [
                    {
                        "sha": "invalid-date-commit",
                        "date": "not-a-date",
                        "message": "Unparseable upstream timestamp",
                    }
                ]
            },
            str(output),
        )

        item = ET.parse(output).find("channel/item")
        assert item is not None
        assert item.find("pubDate") is None
        assert "GMT" in ET.parse(output).findtext("channel/lastBuildDate")

    def test_extract_link_text_basic(self, rss_generator):
        """Test extracting text from basic markdown link."""
        markdown = "* [SiteName](https://example.com) - Description"
        text = rss_generator._extract_link_text(markdown)

        assert "SiteName" in text
        assert "Description" in text
        assert "https://" not in text

    def test_extract_link_text_starred(self, rss_generator):
        """Test extracting text from starred markdown link."""
        markdown = "* ⭐ **[StreamSite](https://stream.example.com)** - Best streaming"
        text = rss_generator._extract_link_text(markdown)

        assert "StreamSite" in text
        assert "Best streaming" in text
        assert "⭐" not in text
        assert "**" not in text
        assert "https://" not in text

    def test_extract_link_text_multiple_links(self, rss_generator):
        """Test extracting text with multiple markdown links."""
        markdown = "* [Site1](https://site1.com) - Desc / [Site2](https://site2.com)"
        text = rss_generator._extract_link_text(markdown)

        assert "Site1" in text
        assert "Site2" in text
        assert "https://" not in text

    def test_generate_item_title(self, rss_generator):
        """Test RSS item title generation."""
        commit = {
            "message": "Add new sites",
            "added": [
                {"link": "test", "type": "new"},
                {"link": "test2", "type": "updated"},
            ],
            "removed": [{"link": "old"}],
        }
        title = rss_generator._generate_item_title(commit)

        assert "1 added" in title
        assert "1 updated" in title
        assert "1 removed" in title

    def test_generate_item_title_empty_commit(self, rss_generator):
        """Test title generation for empty commit."""
        commit = {"message": "Minor update", "added": [], "removed": []}
        title = rss_generator._generate_item_title(commit)

        assert title == "No changes"

    def test_generate_item_description(self, rss_generator):
        """Test RSS item description generation."""
        commit = {
            "sha": "abc123def456789012345678901234567890abcd",
            "message": "Add streaming site",
            "added": [
                {
                    "link": "* ⭐ **[StreamSite](https://stream.example.com)**",
                    "source": "video",
                    "type": "new",
                }
            ],
            "removed": [],
        }
        description = rss_generator._generate_item_description(commit)

        assert "<p><strong>Commit:</strong>" in description
        assert "Add streaming site" in description
        assert "abc123de" in description  # Short SHA
        assert "<h3>Added Links (1)</h3>" in description
        assert "[video]" in description
        assert "StreamSite" in description

    def test_generate_item_description_with_removed(self, rss_generator):
        """Test description with removed links."""
        commit = {
            "sha": "abc123def456789012345678901234567890abcd",
            "message": "Remove old site",
            "added": [],
            "removed": [
                {
                    "link": "* [OldSite](https://old.example.com)",
                    "source": "misc",
                    "type": "removed",
                }
            ],
        }
        description = rss_generator._generate_item_description(commit)

        assert "<h3>Removed Links (1)</h3>" in description
        assert "[misc]" in description
        assert "OldSite" in description

    def test_generate_item_description_empty(self, rss_generator):
        """Test description for empty commit."""
        commit = {
            "sha": "abc123def456789012345678901234567890abcd",
            "message": "No changes",
            "added": [],
            "removed": [],
        }
        description = rss_generator._generate_item_description(commit)

        assert "No link changes in this commit" in description

    def test_generate_item_description_escapes_untrusted_content(self, rss_generator):
        """Test commit and link content is escaped in RSS descriptions."""
        commit = {
            "sha": "abc123def456789012345678901234567890abcd",
            "message": '<script>alert("xss")</script>',
            "added": [
                {
                    "link": '* [Bad<script>](javascript:alert("xss")) - <img src=x>',
                    "source": 'video"><script>',
                    "type": "new",
                }
            ],
            "removed": [],
        }

        description = rss_generator._generate_item_description(commit)

        assert "<script>" not in description
        assert "javascript:alert" not in description
        assert "&lt;script&gt;" in description
        assert "&lt;img src=x&gt;" in description
        assert "[video&quot;&gt;&lt;script&gt;]" in description

    def test_generate_rss_file(
        self, rss_generator, sample_data_with_commits, temp_directory
    ):
        """Test RSS file generation."""
        output_file = temp_directory / "test_feed.xml"
        rss_generator.generate(sample_data_with_commits, str(output_file))

        assert output_file.exists()

        # Parse and validate XML
        tree = ET.parse(output_file)
        root = tree.getroot()

        assert root.tag == "rss"
        assert root.get("version") == "2.0"

    def test_failed_replace_preserves_previous_feed(
        self, rss_generator, sample_data_with_commits, temp_directory
    ):
        output_file = temp_directory / "test_feed.xml"
        previous_feed = "<rss>previous feed</rss>\n"
        output_file.write_text(previous_feed, encoding="utf-8")

        with (
            patch(
                "fmhy_tracker.storage.os.replace",
                side_effect=PermissionError("replace failed"),
            ),
            pytest.raises(PermissionError, match="replace failed"),
        ):
            rss_generator.generate(sample_data_with_commits, str(output_file))

        assert output_file.read_text(encoding="utf-8") == previous_feed
        assert list(temp_directory.glob(".test_feed.xml.*.tmp")) == []

    def test_rss_channel_metadata(
        self, rss_generator, sample_data_with_commits, temp_directory
    ):
        """Test RSS channel has correct metadata."""
        output_file = temp_directory / "test_feed.xml"
        rss_generator.generate(sample_data_with_commits, str(output_file))

        # Read and parse
        content = output_file.read_text(encoding="utf-8")

        assert "FMHY Tracker - Changes Feed" in content
        assert "https://nuson999.github.io/fmhy-tracker" in content
        assert "<generator>FMHY Tracker</generator>" in content
        assert "<language>en-us</language>" in content

    def test_rss_item_count(
        self, rss_generator, sample_data_with_commits, temp_directory
    ):
        """Test RSS contains correct number of items."""
        output_file = temp_directory / "test_feed.xml"
        rss_generator.generate(sample_data_with_commits, str(output_file))

        content = output_file.read_text(encoding="utf-8")

        # Should have 3 items (one per commit)
        assert content.count("<item>") == 3
        assert content.count("</item>") == 3

    def test_rss_channel_link_points_to_tracker(
        self, rss_generator, sample_data_with_commits, temp_directory
    ):
        """Test RSS channel link points to tracker dashboard."""
        output_file = temp_directory / "test_feed.xml"
        rss_generator.generate(sample_data_with_commits, str(output_file))

        content = output_file.read_text(encoding="utf-8")

        # Channel link should point to tracker (only one link element in channel)
        assert "<link>https://nuson999.github.io/fmhy-tracker</link>" in content
        # Count occurrences - should be exactly 1 (channel link only, no item links)
        assert (
            content.count("<link>https://nuson999.github.io/fmhy-tracker</link>") == 1
        )

    def test_rss_guid_uses_github_commit(
        self, rss_generator, sample_data_with_commits, temp_directory
    ):
        """Test RSS GUID uses GitHub commit URL."""
        output_file = temp_directory / "test_feed.xml"
        rss_generator.generate(sample_data_with_commits, str(output_file))

        content = output_file.read_text(encoding="utf-8")

        # GUIDs should use GitHub commit URLs
        assert "https://github.com/fmhy/edit/commit/abc123" in content
        assert 'isPermaLink="true"' in content

    def test_rss_cdata_wrapping(
        self, rss_generator, sample_data_with_commits, temp_directory
    ):
        """Test RSS description content is wrapped in CDATA."""
        output_file = temp_directory / "test_feed.xml"
        rss_generator.generate(sample_data_with_commits, str(output_file))

        content = output_file.read_text(encoding="utf-8")

        # Descriptions should be in CDATA
        assert "<![CDATA[" in content
        assert "]]>" in content

    def test_rss_xml_declaration(
        self, rss_generator, sample_data_with_commits, temp_directory
    ):
        """Test RSS has proper XML declaration."""
        output_file = temp_directory / "test_feed.xml"
        rss_generator.generate(sample_data_with_commits, str(output_file))

        content = output_file.read_text(encoding="utf-8")

        assert content.startswith('<?xml version="1.0" encoding="UTF-8"?>')

    def test_rss_empty_data(self, rss_generator, empty_data, temp_directory):
        """Test RSS generation with no commits."""
        output_file = temp_directory / "test_feed.xml"
        rss_generator.generate(empty_data, str(output_file))

        assert output_file.exists()

        content = output_file.read_text(encoding="utf-8")

        # Should have channel but no items
        assert "<channel>" in content
        assert "<item>" not in content

    def test_rss_items_ordered_newest_first(
        self, rss_generator, sample_data_with_commits, temp_directory
    ):
        """Test RSS items are ordered with newest first."""
        output_file = temp_directory / "test_feed.xml"
        rss_generator.generate(sample_data_with_commits, str(output_file))

        content = output_file.read_text(encoding="utf-8")

        # Input data is ordered oldest to newest (like real tracker data)
        # RSS should reverse to show newest first
        # abc123 is newest (2024-01-15), ghi789 is oldest (2024-01-13)
        first_sha_pos = content.find("abc123")  # Newest - should appear first
        second_sha_pos = content.find("def456")  # Middle
        third_sha_pos = content.find("ghi789")  # Oldest - should appear last

        assert first_sha_pos < second_sha_pos < third_sha_pos

    def test_rss_separate_sections(
        self, rss_generator, sample_data_with_commits, temp_directory
    ):
        """Test RSS has separate sections for Added and Updated links."""
        output_file = temp_directory / "test_feed.xml"
        rss_generator.generate(sample_data_with_commits, str(output_file))

        content = output_file.read_text(encoding="utf-8")

        assert "Added Links" in content
        assert "Updated Links" in content

    def test_rss_source_categories(
        self, rss_generator, sample_data_with_commits, temp_directory
    ):
        """Test RSS includes source categories."""
        output_file = temp_directory / "test_feed.xml"
        rss_generator.generate(sample_data_with_commits, str(output_file))

        content = output_file.read_text(encoding="utf-8")

        assert "[video]" in content
        assert "[tools]" in content
        assert "[audio]" in content

    def test_rss_html_in_description(
        self, rss_generator, sample_data_with_commits, temp_directory
    ):
        """Test RSS description contains proper HTML formatting."""
        output_file = temp_directory / "test_feed.xml"
        rss_generator.generate(sample_data_with_commits, str(output_file))

        content = output_file.read_text(encoding="utf-8")

        # HTML elements should be present (inside CDATA)
        assert "<h3>" in content
        assert "</h3>" in content
        assert "<ul>" in content
        assert "</ul>" in content
        assert "<li>" in content
        assert "</li>" in content
        assert "<strong>" in content

    def test_rss_commit_link_in_description(
        self, rss_generator, sample_data_with_commits, temp_directory
    ):
        """Test RSS description contains clickable commit link."""
        output_file = temp_directory / "test_feed.xml"
        rss_generator.generate(sample_data_with_commits, str(output_file))

        content = output_file.read_text(encoding="utf-8")

        # Should have clickable SHA link
        assert '<a href="https://github.com/fmhy/edit/commit/' in content


@pytest.mark.parametrize("order", [(0, 1, 2), (2, 1, 0), (1, 2, 0)])
def test_feed_sorts_dates_independently_of_input_order(
    rss_generator, sample_data_with_commits, temp_directory, order
):
    data = dict(sample_data_with_commits)
    data["commits"] = [data["commits"][index] for index in order]
    output = temp_directory / "feed.xml"
    rss_generator.generate(data, str(output))
    items = ET.parse(output).findall("channel/item")
    assert [item.findtext("guid").split("/")[-1][:6] for item in items] == [
        "abc123",
        "def456",
        "ghi789",
    ]
    assert all(item.findtext("link") == item.findtext("guid") for item in items)
    assert all(item.find("guid").get("isPermaLink") == "true" for item in items)


def test_feed_self_link(rss_generator, empty_data, temp_directory):
    output = temp_directory / "feed.xml"
    rss_generator.generate(empty_data, str(output))
    self_link = ET.parse(output).find("channel/{http://www.w3.org/2005/Atom}link")
    assert self_link.get("href") == "https://nuson999.github.io/fmhy-tracker/feed.xml"
    assert self_link.get("rel") == "self"
    assert self_link.get("type") == "application/rss+xml"


def test_legacy_added_links_and_starred_updates(rss_generator):
    commit = {
        "sha": "abc123",
        "message": "Legacy and updated links",
        "added": [
            {"link": "* ⭐ [Legacy](https://example.com/legacy)", "source": "video"},
            {
                "link": "* ⭐ [New](https://example.com/new)",
                "source": "video",
                "type": "updated",
                "relatedLink": "* ⭐ [Old](https://example.com/old)",
            },
        ],
        "removed": [],
    }
    assert rss_generator._generate_item_title(commit) == "1 added, 1 updated"
    description = rss_generator._generate_item_description(commit)
    assert "Legacy" in description
    assert "⭐" in description
    assert "<strong>Before:</strong>" in description
    assert "<strong>After:</strong>" in description
    assert "https://example.com/old" in description


def test_serialization_preserves_html_escaping_and_cdata_terminators(
    rss_generator, temp_directory
):
    from html.parser import HTMLParser

    class Anchors(HTMLParser):
        def __init__(self):
            super().__init__()
            self.attributes = []

        def handle_starttag(self, tag, attributes):
            if tag == "a":
                self.attributes.append(dict(attributes))

    commit = {
        "sha": "abc123",
        "date": "2026-09-29T00:00:00Z",
        "message": 'quotes " & <script> ]]> entities &quot;',
        "added": [
            {
                "source": "video",
                "type": "new",
                "link": '* [Quoted](https://example.com/" onclick="bad) - <img src=x> ]]> &quot;',
            }
        ],
        "removed": [],
    }
    expected = rss_generator._generate_item_description(commit)
    output = temp_directory / "feed.xml"
    rss_generator.generate({"commits": [commit]}, str(output))
    actual = ET.parse(output).findtext("channel/item/description")
    assert actual == expected
    assert "&lt;script&gt;" in actual
    assert "&lt;img src=x&gt;" in actual
    parser = Anchors()
    parser.feed(actual)
    assert all(set(attributes) == {"href"} for attributes in parser.attributes)


def test_serialization_removes_characters_forbidden_by_xml_10(
    rss_generator, temp_directory
):
    commit = {
        "sha": "abc123",
        "date": "2026-09-29T00:00:00Z",
        "message": "Valid ☀ text\x00\x01 remains",
        "added": [],
        "removed": [],
    }
    output = temp_directory / "feed.xml"

    rss_generator.generate({"commits": [commit]}, str(output))

    description = ET.parse(output).findtext("channel/item/description")
    assert "Valid ☀ text remains" in description
    assert "abc123" in description
    assert "\x00" not in description
    assert "\x01" not in description


def test_naive_feed_dates_are_utc(rss_generator):
    assert rss_generator._format_rfc822_date("2026-09-29T12:00:00") == (
        "Tue, 29 Sep 2026 12:00:00 GMT"
    )
