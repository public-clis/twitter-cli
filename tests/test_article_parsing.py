"""Tests for Twitter Article (long-form) Draft.js rich content parsing."""

from __future__ import annotations

from twitter_cli.parser import (
    _extract_atomic_content,
    _normalize_article_entity_map,
    _parse_article,
    _render_article_text_block,
)


class TestRenderArticleTextBlock:
    def test_plain_text_unchanged(self):
        block = {"text": "hello world", "entityRanges": [], "inlineStyleRanges": []}
        assert _render_article_text_block(block, {}) == "hello world"

    def test_empty_text(self):
        assert _render_article_text_block({"text": "", "entityRanges": [], "inlineStyleRanges": []}, {}) == ""

    def test_bold_italic_code_strikethrough(self):
        block = {
            "text": "bold italic code strike",
            "entityRanges": [],
            "inlineStyleRanges": [
                {"offset": 0, "length": 4, "style": "Bold"},
                {"offset": 5, "length": 6, "style": "Italic"},
                {"offset": 12, "length": 4, "style": "Code"},
                {"offset": 17, "length": 6, "style": "Strikethrough"},
            ],
        }
        assert _render_article_text_block(block, {}) == "**bold** *italic* `code` ~~strike~~"

    def test_bold_and_link_mixed_non_overlapping(self):
        block = {
            "text": "Click here for more",
            "entityRanges": [{"key": 0, "offset": 6, "length": 4}],
            "inlineStyleRanges": [{"offset": 0, "length": 5, "style": "Bold"}],
        }
        entity_map = {"0": {"type": "LINK", "data": {"url": "https://example.com"}}}
        result = _render_article_text_block(block, entity_map)
        assert result == "**Click** [here](https://example.com) for more"

    def test_overlapping_style_and_link_preserves_link_without_corruption(self):
        block = {
            "text": "Read docs now",
            "entityRanges": [{"key": 0, "offset": 5, "length": 4}],
            "inlineStyleRanges": [{"offset": 5, "length": 4, "style": "Bold"}],
        }
        entity_map = {"0": {"type": "LINK", "data": {"url": "https://example.com"}}}
        result = _render_article_text_block(block, entity_map)
        assert result == "Read [docs](https://example.com) now"

    def test_out_of_bounds_style_ignored(self):
        block = {
            "text": "short",
            "entityRanges": [],
            "inlineStyleRanges": [{"offset": 0, "length": 100, "style": "Bold"}],
        }
        assert _render_article_text_block(block, {}) == "short"


class TestExtractAtomicContent:
    def test_divider(self):
        block = {"entityRanges": [{"key": 0, "length": 1, "offset": 0}]}
        entity_map = {"0": {"type": "DIVIDER", "data": {}}}
        assert _extract_atomic_content(block, entity_map) == ["---"]

    def test_embedded_tweet(self):
        block = {"entityRanges": [{"key": 0, "length": 1, "offset": 0}]}
        entity_map = {"0": {"type": "TWEET", "data": {"tweetId": "123456"}}}
        result = _extract_atomic_content(block, entity_map)
        assert result == ["> [Embedded Tweet](https://x.com/i/status/123456)"]

    def test_markdown_block(self):
        block = {"entityRanges": [{"key": 0, "length": 1, "offset": 0}]}
        entity_map = {"0": {"type": "MARKDOWN", "data": {"markdown": "# Heading"}}}
        assert _extract_atomic_content(block, entity_map) == ["# Heading"]


class TestNormalizeAndParseArticle:
    def test_list_and_dict_entity_map(self):
        assert _normalize_article_entity_map([{"key": "0", "value": {"type": "DIVIDER"}}]) == {
            "0": {"type": "DIVIDER"}
        }
        assert _normalize_article_entity_map({"0": {"type": "DIVIDER"}}) == {"0": {"type": "DIVIDER"}}

    def test_parse_article_divider_and_image(self):
        tweet_data = {
            "article": {
                "article_results": {
                    "result": {
                        "title": "Test Article",
                        "content_state": {
                            "blocks": [
                                {"type": "unstyled", "text": "Intro", "entityRanges": [], "inlineStyleRanges": []},
                                {"type": "atomic", "text": " ", "entityRanges": [{"key": 0, "length": 1, "offset": 0}]},
                                {"type": "atomic", "text": " ", "entityRanges": [{"key": 1, "length": 1, "offset": 0}]},
                            ],
                            "entityMap": [
                                {"key": "0", "value": {"type": "DIVIDER", "data": {}}},
                                {
                                    "key": "1",
                                    "value": {
                                        "type": "MEDIA",
                                        "data": {"caption": "Diagram", "mediaItems": [{"mediaId": "111"}]},
                                    },
                                },
                            ],
                        },
                        "media_entities": [
                            {
                                "media_id": "111",
                                "media_info": {"original_img_url": "https://pbs.twimg.com/media/test.jpg"},
                            }
                        ],
                    }
                }
            }
        }
        result = _parse_article(tweet_data)
        assert result["article_title"] == "Test Article"
        assert "---" in result["article_text"]
        assert "![Diagram](https://pbs.twimg.com/media/test.jpg)" in result["article_text"]
