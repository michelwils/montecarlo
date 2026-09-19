from montecarlo.constants import ALL_SCORES, SCORES, SCORES_FR


class TestAllScores:
    def test_contains_both_languages(self):
        assert "Small" in ALL_SCORES
        assert "Petit" in ALL_SCORES

    def test_english_and_french_tiers_carry_the_same_points(self):
        assert SCORES["X-Small"] == SCORES_FR["Très petit"] == 0.5
        assert SCORES["Small"] == SCORES_FR["Petit"] == 1
        assert SCORES["Medium"] == SCORES_FR["Moyen"] == 3
        assert SCORES["Large"] == SCORES_FR["Grand"] == 5
        assert SCORES["X-Large"] == SCORES_FR["Très grand"] == 8

    def test_no_key_collisions_between_languages(self):
        assert set(SCORES) & set(SCORES_FR) == set()
        assert len(ALL_SCORES) == len(SCORES) + len(SCORES_FR)
