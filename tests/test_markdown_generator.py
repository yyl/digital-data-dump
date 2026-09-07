import unittest

from src.publish.markdown_generator import MarkdownGenerator


class TestMarkdownGenerator(unittest.TestCase):
    def setUp(self):
        self.generator = MarkdownGenerator()

    def test_markdown_link_skips_mailto_urls(self):
        result = self.generator._markdown_link(
            "Newsletter edition",
            "mailto:newsletter@example.com",
        )

        self.assertEqual(result, "Newsletter edition")

    def test_generate_monthly_summary_adds_next_month_signoff(self):
        result = self.generator.generate_monthly_summary({
            "year": "2026",
            "month": "04",
        })

        self.assertTrue(result.endswith("That's it. See you in May!\n"))

    def test_generate_monthly_summary_signoff_rolls_december_to_january(self):
        result = self.generator.generate_monthly_summary({
            "year": "2026",
            "month": "12",
        })

        self.assertTrue(result.endswith("That's it. See you in January!\n"))

    def test_generate_monthly_summary_orders_sections(self):
        result = self.generator.generate_monthly_summary({
            "year": "2026",
            "month": "04",
            "readwise": {"articles": 0},
            "hardcover": {"books_finished": 0},
            "overcast": {"episodes_played": 0},
            "blog": {"posts": 0},
            "github": {"commits": 0},
            "apple_health": {"workouts": 0},
            "foursquare": {"checkins": 0},
            "letterboxd": {"movies_watched": 0},
        })

        headings = [
            "## Reading",
            "## Books",
            "## Podcasts",
            "## Writing",
            "## Code",
            "## Workout",
            "## Travel",
            "## Movies",
        ]
        positions = [result.index(heading) for heading in headings]

        self.assertEqual(positions, sorted(positions))

    def test_generate_readwise_articles_block_skips_mailto_links(self):
        result = self.generator._generate_readwise_articles_block([
            {
                "title": "Inbox essay",
                "link": "mailto:newsletter@example.com",
                "site_name": "TinyLetter",
                "last_moved_at": "2026-04-04T10:00:00Z",
                "reading_speed_wpm": 250,
            },
            {
                "title": "Web essay",
                "link": "https://example.com/post",
                "site_name": "TinyLetter",
                "last_moved_at": "2026-04-03T10:00:00Z",
                "reading_speed_wpm": 300,
            },
            {
                "title": "Another web essay",
                "link": "https://example.com/post-2",
                "site_name": "TinyLetter",
                "last_moved_at": "2026-04-02T10:00:00Z",
                "reading_speed_wpm": 320,
            },
        ])

        self.assertIn("| 2026-04-04 | Inbox essay | 250 wpm |", result)
        self.assertIn("| 2026-04-03 | [Web essay](https://example.com/post) | 300 wpm |", result)
        self.assertNotIn("[Inbox essay](mailto:newsletter@example.com)", result)

    def test_generate_readwise_articles_block_adds_ranked_source_summary(self):
        result = self.generator._generate_readwise_articles_block([
            {
                "title": "Essay A",
                "link": "https://example.com/a",
                "site_name": "Alpha",
                "last_moved_at": "2026-04-04T10:00:00Z",
                "reading_speed_wpm": 250,
            },
            {
                "title": "Essay B",
                "link": "https://example.com/b",
                "site_name": "Alpha",
                "last_moved_at": "2026-04-03T10:00:00Z",
                "reading_speed_wpm": 260,
            },
            {
                "title": "Essay C",
                "link": "https://example.com/c",
                "site_name": "Beta",
                "last_moved_at": "2026-04-02T10:00:00Z",
                "reading_speed_wpm": 270,
            },
            {
                "title": "Essay D",
                "link": "https://example.com/d",
                "site_name": "Gamma",
                "last_moved_at": "2026-04-01T10:00:00Z",
                "reading_speed_wpm": 280,
            },
        ])

        self.assertIn("| Source | Articles |", result)
        self.assertIn("| Alpha | 2 |", result)
        self.assertIn("| Other | 2 |", result)
        self.assertIn("#### Alpha", result)
        self.assertIn("#### Other", result)
        self.assertNotIn("#### Beta", result)
        self.assertNotIn("#### Gamma", result)

    def test_generate_readwise_articles_block_promotes_new_sources(self):
        result = self.generator._generate_readwise_articles_block([
            {
                "title": "Essay A",
                "link": "https://example.com/a",
                "site_name": "Old Source",
                "last_moved_at": "2026-04-04T10:00:00Z",
                "reading_speed_wpm": 250,
            },
            {
                "title": "Essay B",
                "link": "https://example.com/b",
                "site_name": "New Source 1",
                "last_moved_at": "2026-04-03T10:00:00Z",
                "reading_speed_wpm": 260,
            },
            {
                "title": "Essay C",
                "link": "https://example.com/c",
                "site_name": "New Source 2",
                "last_moved_at": "2026-04-02T10:00:00Z",
                "reading_speed_wpm": 270,
            },
            {
                "title": "Essay D",
                "link": "https://example.com/d",
                "site_name": "New Source 2",
                "last_moved_at": "2026-04-01T10:00:00Z",
                "reading_speed_wpm": 280,
            },
        ], new_sources=["New Source 1", "New Source 2"])

        # Summary table:
        self.assertIn("| Source | Articles |", result)
        self.assertIn("| New Source 2 🆕 | 2 |", result)
        self.assertIn("| New Source 1 🆕 | 1 |", result)
        self.assertIn("| Other | 1 |", result)  # Old Source is count=1, it goes to Other
        
        # Breakdown sections: all new sources are promoted, even with one article
        self.assertIn("#### 🆕 New Source 2", result)
        self.assertIn("#### 🆕 New Source 1", result)
        self.assertIn("| 2026-04-03 | [Essay B](https://example.com/b) | 260 wpm |", result)
        # Breakdown section: Old Source is in Other
        self.assertIn("#### Other", result)
        self.assertIn("| Old Source |", result)

    def test_generate_podcasts_block_adds_ranked_summary_and_groups_other(self):
        result = self.generator._generate_podcasts_block([
            {
                "podcast_title": "Alpha Show",
                "podcast_link": "https://example.com/alpha",
                "episode_title": "Episode 1",
                "episode_link": "https://example.com/alpha-1",
                "userUpdatedDate": "2026-04-04T10:00:00Z",
            },
            {
                "podcast_title": "Alpha Show",
                "podcast_link": "https://example.com/alpha",
                "episode_title": "Episode 2",
                "episode_link": "https://example.com/alpha-2",
                "userUpdatedDate": "2026-04-03T10:00:00Z",
            },
            {
                "podcast_title": "Beta Show",
                "podcast_link": "https://example.com/beta",
                "episode_title": "Episode 3",
                "episode_link": "https://example.com/beta-1",
                "userUpdatedDate": "2026-04-02T10:00:00Z",
            },
            {
                "podcast_title": "Gamma Show",
                "podcast_link": "https://example.com/gamma",
                "episode_title": "Episode 4",
                "episode_link": "https://example.com/gamma-1",
                "userUpdatedDate": "2026-04-01T10:00:00Z",
            },
        ])

        self.assertIn("| Podcast | Episodes |", result)
        self.assertIn("| Alpha Show | 2 |", result)
        self.assertIn("| Other | 2 |", result)
        self.assertIn("#### [Alpha Show](https://example.com/alpha)", result)
        self.assertIn("#### Other", result)
        self.assertIn("| Date | Episode | Podcast |", result)
        self.assertNotIn("#### [Beta Show]", result)

    def test_generate_podcasts_block_promotes_new_feeds(self):
        result = self.generator._generate_podcasts_block([
            {
                "podcast_title": "Old Show",
                "podcast_link": "https://example.com/old",
                "episode_title": "Episode 1",
                "episode_link": "https://example.com/old-1",
                "userUpdatedDate": "2026-04-04T10:00:00Z",
            },
            {
                "podcast_title": "New Show 1",
                "podcast_link": "https://example.com/ns1",
                "episode_title": "Episode 2",
                "episode_link": "https://example.com/ns1-1",
                "userUpdatedDate": "2026-04-03T10:00:00Z",
            },
            {
                "podcast_title": "New Show 2",
                "podcast_link": "https://example.com/ns2",
                "episode_title": "Episode 3",
                "episode_link": "https://example.com/ns2-1",
                "userUpdatedDate": "2026-04-02T10:00:00Z",
            },
            {
                "podcast_title": "New Show 2",
                "podcast_link": "https://example.com/ns2",
                "episode_title": "Episode 4",
                "episode_link": "https://example.com/ns2-2",
                "userUpdatedDate": "2026-04-01T10:00:00Z",
            },
        ], new_feeds=["New Show 1", "New Show 2"])

        # Summary table:
        self.assertIn("| Podcast | Episodes |", result)
        self.assertIn("| New Show 2 🆕 | 2 |", result)
        self.assertIn("| New Show 1 🆕 | 1 |", result)
        self.assertIn("| Other | 1 |", result)  # Old Show is count=1, it goes to Other
        
        # Breakdown section: New Show 2 has its own section
        self.assertIn("#### 🆕 [New Show 2](https://example.com/ns2)", result)
        # Breakdown section: New Show 1 and Old Show are in Other
        self.assertIn("#### Other", result)
        self.assertIn("| New Show 1 🆕 |", result)
        self.assertIn("| Old Show |", result)

    def test_generate_overcast_section_includes_minutes_played(self):
        result = self.generator._generate_overcast_section({
            "feeds_added": 2,
            "feeds_removed": 1,
            "episodes_played": 8,
            "minutes_listened": 245,
            "comparisons": {
                "episodes_played": {"mom": 14.0, "yoy": None},
                "minutes_listened": {"mom": -5.0, "yoy": 20.0},
            },
            "episodes": [],
            "new_feeds": [],
        })

        self.assertIn("- **Episodes Played**: 8 (+14% MoM, N/A YoY)", result)
        self.assertIn("- **Minutes Played**: 245 (-5% MoM, +20% YoY)", result)

    def test_generate_commit_groups_block_adds_ranked_summary_and_groups_other(self):
        result = self.generator._generate_commit_groups_block([
            {
                "repo": "user/alpha",
                "commits": [
                    {"repo": "user/alpha", "message": "feat: one", "author_date": "2026-04-04T10:00:00Z"},
                    {"repo": "user/alpha", "message": "fix: two", "author_date": "2026-04-03T10:00:00Z"},
                ],
            },
            {
                "repo": "user/beta",
                "commits": [
                    {"repo": "user/beta", "message": "chore: three", "author_date": "2026-04-02T10:00:00Z"},
                ],
            },
            {
                "repo": "user/gamma",
                "commits": [
                    {"repo": "user/gamma", "message": "docs: four", "author_date": "2026-04-01T10:00:00Z"},
                ],
            },
        ])

        self.assertIn("| Repo | Commits |", result)
        self.assertIn("| user/alpha | 2 |", result)
        self.assertIn("| Other | 2 |", result)
        self.assertIn("#### [user/alpha](https://github.com/user/alpha)", result)
        self.assertIn("#### Other", result)
        self.assertIn("| Date | Commit Message | Repo |", result)
        self.assertNotIn("#### [user/beta]", result)

    def test_generate_apple_health_section_includes_calories_and_activity_rank(self):
        result = self.generator._generate_apple_health_section({
            "workouts": 5,
            "total_duration_seconds": 7500,
            "total_calories": 1432.4,
            "comparisons": {
                "workouts": {"mom": 25.0, "yoy": 10.0},
                "total_duration_seconds": {"mom": 12.0, "yoy": None},
                "total_calories": {"mom": -5.0, "yoy": 20.0},
            },
            "activity_breakdown": [
                {"activity_type": "run", "workouts": 3},
            ],
        })

        self.assertIn("## Workout", result)
        self.assertIn("- **Workouts**: 5 (+25% MoM, +10% YoY)", result)
        self.assertIn("- **Total Time**: 2h 5m (+12% MoM, N/A YoY)", result)
        self.assertIn("- **Total Calories**: 1,432 kcal (-5% MoM, +20% YoY)", result)
        self.assertIn("| Activity Type | Workouts |", result)
        self.assertIn("| run | 3 |", result)

    def test_generate_blog_section_includes_top_tags(self):
        result = self.generator._generate_blog_section({
            "posts": 3,
            "total_words": 4567,
            "unique_tags": 4,
            "comparisons": {
                "posts": {"mom": 50.0, "yoy": None},
                "total_words": {"mom": 10.0, "yoy": 25.0},
                "unique_tags": {"mom": -20.0, "yoy": 0.0},
            },
            "top_tags": [
                {"tag": "python", "posts": 2},
                {"tag": "hugo", "posts": 1},
            ],
        })

        self.assertIn("## Writing", result)
        self.assertIn("- **Posts**: 3 (+50% MoM, N/A YoY)", result)
        self.assertIn("- **Total Words**: 4,567 (+10% MoM, +25% YoY)", result)
        self.assertIn("- **Unique Tags**: 4 (-20% MoM, +0% YoY)", result)
        self.assertIn("| Tag | Posts |", result)
        self.assertIn("| python | 2 |", result)
        self.assertIn("| hugo | 1 |", result)

    def test_generate_hardcover_section_handles_unrated_books(self):
        result = self.generator._generate_hardcover_section({
            "books_finished": 2,
            "avg_rating": None,
            "comparisons": {
                "books_finished": {"mom": 100.0, "yoy": None},
                "avg_rating": {"mom": None, "yoy": None},
            },
        })

        self.assertIn("- **Books Finished**: 2 (+100% MoM, N/A YoY)", result)
        self.assertIn("- **Average Rating**: N/A", result)

    def test_generate_readwise_highlights_block_uses_quote_format(self):
        result = self.generator._generate_readwise_highlights_block([
            {
                "title": "Interesting Essay",
                "category": "article",
                "link": "https://example.com/essay",
                "highlights": [
                    {
                        "date": "2026-04-04T10:00:00Z",
                        "text": "A memorable line worth quoting.",
                        "note": "This connects to the chapter above.",
                    }
                ],
            },
            {
                "title": "Second Essay",
                "category": "article",
                "link": "https://example.com/second",
                "highlights": [
                    {
                        "date": "2026-04-05T10:00:00Z",
                        "text": "Another great highlight.",
                        "note": "",
                    }
                ],
            }
        ])

        self.assertIn("#### [Interesting Essay](https://example.com/essay) (article)", result)
        self.assertIn("> A memorable line worth quoting.", result)
        self.assertIn("> Note: This connects to the chapter above.", result)
        self.assertIn("*2026-04-04*", result)
        self.assertNotIn("| Date | Highlight | Note |", result)
        self.assertIn("\n---\n", result)
        self.assertIn("#### [Second Essay](https://example.com/second) (article)", result)

    def test_generate_monthly_summary_moves_whats_new_into_source_sections(self):
        result = self.generator.generate_monthly_summary({
            "year": "2026",
            "month": "04",
            "readwise": {
                "new_sources": ["Example Blog"],
            },
            "foursquare": {
                "new_places": ["Neighborhood Cafe"],
            },
            "overcast": {
                "new_feeds": ["Tech Podcast"],
            },
            "github": {
                "new_repos": ["user/new-project"],
            },
        })

        self.assertNotIn("\n## What's new\n", result)
        self.assertIn("## Reading", result)
        self.assertIn("1 new article source:\n- Example Blog", result)
        self.assertIn("## Travel", result)
        self.assertIn("1 new place visited:\n- Neighborhood Cafe", result)
        self.assertIn("## Podcasts", result)
        self.assertIn("1 new podcast channel:\n- Tech Podcast", result)
        self.assertIn("## Code", result)
        self.assertIn("1 new repo:\n- user/new-project", result)

    def test_generate_whats_new_items_handles_plural_labels(self):
        result = self.generator._generate_whats_new_items(
            ["user/new-project", "user/another-new"],
            "new repo",
        )

        self.assertIn("### What's new", result)
        self.assertIn("2 new repos:", result)
        self.assertIn("- user/new-project", result)
        self.assertIn("- user/another-new", result)
