"""team.find: an alias resolves before any fragment match, and a short query never matches inside a name.
Offline: a fixed roster and a stubbed site."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "skills", "team"))
import team  # noqa: E402

PEOPLE = [
    {"name": "Summer Chen", "email": "summer@example.com", "slack": "U0TEST0001", "jira": "j1"},
    {"name": "Owner Person", "email": "owner@example.com", "slack": "U0TEST0002", "jira": "j2"},
    {"name": "Lina Wu", "email": "lina@example.com", "slack": "U0TEST0003", "jira": "j3"},
]


class Find(unittest.TestCase):
    def setUp(self):
        self._site = team.site
        team.site = lambda: {"emails": {"me": "owner@example.com", "alt": "someone@elsewhere.example"}}

    def tearDown(self):
        team.site = self._site

    def test_me_is_the_owner_not_a_name_containing_me(self):
        self.assertEqual([p["name"] for p in team.find(PEOPLE, "me")], ["Owner Person"])

    def test_an_alias_off_the_roster_finds_nobody(self):
        self.assertEqual(team.find(PEOPLE, "alt"), [])

    def test_a_short_query_matches_only_whole(self):
        self.assertEqual(team.find(PEOPLE, "li"), [])
        self.assertEqual(team.find(PEOPLE, "wu"), [])

    def test_names_and_fragments_still_match(self):
        self.assertEqual([p["name"] for p in team.find(PEOPLE, "lina")], ["Lina Wu"])
        self.assertEqual([p["name"] for p in team.find(PEOPLE, "sum")], ["Summer Chen"])
        self.assertEqual([p["name"] for p in team.find(PEOPLE, "U0TEST0003")], ["Lina Wu"])


if __name__ == "__main__":
    unittest.main()
