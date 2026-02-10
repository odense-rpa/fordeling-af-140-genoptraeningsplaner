from datetime import date

import pytest

from fordeling_af_140_genoptraeningsplaner.indlaes_gop import (
    beregn_alder,
    bestem_aldersgruppe,
)


class TestBeregnAlder:
    def test_adult_born_1980(self):
        # 0101801234 → born 01-01-1980, 7th digit=1 → 1900s
        alder = beregn_alder("0101801234")
        expected = date.today().year - 1980
        if (date.today().month, date.today().day) < (1, 1):
            expected -= 1
        assert alder == expected

    def test_child_born_2010(self):
        # 0101104234 → born 01-01-2010, 7th digit=4 → 2000s (yy=10 <= 36)
        alder = beregn_alder("0101104234")
        expected = date.today().year - 2010
        if (date.today().month, date.today().day) < (1, 1):
            expected -= 1
        assert alder == expected

    def test_elderly_born_1950(self):
        # 1506501234 → born 15-06-1950, 7th digit=1 → 1900s
        alder = beregn_alder("1506501234")
        expected = date.today().year - 1950
        if (date.today().month, date.today().day) < (6, 15):
            expected -= 1
        assert alder == expected

    def test_century_rule_digit_4_high_year(self):
        # 0101904234 → yy=90, digit=4 → 90>36 → 1900s → 1990
        alder = beregn_alder("0101904234")
        expected = date.today().year - 1990
        if (date.today().month, date.today().day) < (1, 1):
            expected -= 1
        assert alder == expected

    def test_century_rule_digit_9_low_year(self):
        # 0101209234 → yy=20, digit=9 → 20<=36 → 2000s → 2020
        alder = beregn_alder("0101209234")
        expected = date.today().year - 2020
        if (date.today().month, date.today().day) < (1, 1):
            expected -= 1
        assert alder == expected

    def test_century_rule_digit_5_low_year(self):
        # 0101205234 → yy=20, digit=5 → 20<=57 → 2000s → 2020
        alder = beregn_alder("0101205234")
        expected = date.today().year - 2020
        if (date.today().month, date.today().day) < (1, 1):
            expected -= 1
        assert alder == expected

    def test_birthday_not_yet_this_year(self):
        # Person born Dec 31, should be one year younger before their birthday
        alder = beregn_alder("3112001234")  # born 31-12-1900
        today = date.today()
        if today.month < 12 or (today.month == 12 and today.day < 31):
            assert alder == today.year - 1900 - 1
        else:
            assert alder == today.year - 1900

    def test_too_short_cpr_raises(self):
        with pytest.raises(ValueError, match="for kort"):
            beregn_alder("010180")


class TestBestemAldersgruppe:
    def test_under_67(self):
        assert bestem_aldersgruppe(0) == "< 67"
        assert bestem_aldersgruppe(18) == "< 67"
        assert bestem_aldersgruppe(66) == "< 67"

    def test_67_to_74(self):
        assert bestem_aldersgruppe(67) == "67 - 74"
        assert bestem_aldersgruppe(70) == "67 - 74"
        assert bestem_aldersgruppe(74) == "67 - 74"

    def test_75_and_above(self):
        assert bestem_aldersgruppe(75) == "> 74"
        assert bestem_aldersgruppe(80) == "> 74"
        assert bestem_aldersgruppe(100) == "> 74"
