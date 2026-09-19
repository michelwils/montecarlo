from montecarlo.constants import ALL_SCORES, SCORES, SCORES_EN


class TestAllScores:
    def test_contains_both_languages(self):
        assert "Petit" in ALL_SCORES
        assert "Small" in ALL_SCORES

    def test_french_and_english_tiers_carry_the_same_points(self):
        assert SCORES["Très petit"] == SCORES_EN["X-Small"] == 0.5
        assert SCORES["Petit"] == SCORES_EN["Small"] == 1
        assert SCORES["Moyen"] == SCORES_EN["Medium"] == 3
        assert SCORES["Grand"] == SCORES_EN["Large"] == 5
        assert SCORES["Très grand"] == SCORES_EN["X-Large"] == 8

    def test_no_key_collisions_between_languages(self):
        assert set(SCORES) & set(SCORES_EN) == set()
        assert len(ALL_SCORES) == len(SCORES) + len(SCORES_EN)
