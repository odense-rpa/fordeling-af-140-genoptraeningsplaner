from fordeling_af_140_genoptraeningsplaner.diagnose_opslag import (
    find_diagnose_kategori,
    indlæs_diagnosekoder,
)


def _make_diagnosekoder(entries: list[tuple[str, str]]) -> list[dict]:
    """Helper to create sorted diagnosekoder from (name, search_text) pairs."""
    result = []
    for name, search_text in entries:
        result.append(
            {
                "Diagnose": name,
                "Sogetekst": search_text.lower(),
                "Laengde": len(search_text),
            }
        )
    result.sort(key=lambda d: d["Laengde"], reverse=True)
    return result


class TestFindDiagnoseKategori:
    def test_long_search_term_matches_in_tekst(self):
        diagnosekoder = _make_diagnosekoder(
            [
                ("Cancer", "cancer"),
                ("Hånd", "hånd"),
            ]
        )
        diagnoser = [
            {"Kode": "DZ960", "Type": "A", "Tekst": "Kræft og cancer behandling"}
        ]

        kategori, _ = find_diagnose_kategori(diagnoser, diagnosekoder)
        assert kategori == "Cancer"

    def test_long_search_term_matches_in_kode(self):
        diagnosekoder = _make_diagnosekoder(
            [
                ("Neurologi", "dm30"),
            ]
        )
        diagnoser = [{"Kode": "DM301", "Type": "A", "Tekst": "Skulder"}]

        kategori, _ = find_diagnose_kategori(diagnoser, diagnosekoder)
        assert kategori == "Neurologi"

    def test_short_search_term_exact_word_match(self):
        diagnosekoder = _make_diagnosekoder(
            [
                ("Hofte", "dz964"),
                ("Knæ", "knæ"),
            ]
        )
        diagnoser = [{"Kode": "DZ964", "Type": "A", "Tekst": "Hofte operation"}]

        # "dz964" appears as a word when split on spaces
        kategori, _ = find_diagnose_kategori(diagnoser, diagnosekoder)
        assert kategori == "Hofte"

    def test_short_search_term_no_partial_match(self):
        """Short terms (<=3) should only match exact words, not substrings."""
        diagnosekoder = _make_diagnosekoder(
            [
                ("Test", "abc"),
            ]
        )
        # "abcdef" contains "abc" but it's not an exact word
        diagnoser = [{"Kode": "X", "Type": "A", "Tekst": "abcdef"}]

        kategori, _ = find_diagnose_kategori(diagnoser, diagnosekoder)
        assert kategori == "Andet"

    def test_longest_match_wins(self):
        diagnosekoder = _make_diagnosekoder(
            [
                ("Kort", "can"),
                ("Lang", "cancer"),
            ]
        )
        diagnoser = [{"Kode": "X", "Type": "A", "Tekst": "cancer behandling"}]

        # "cancer" (6 chars) should match before "can" (3 chars)
        kategori, _ = find_diagnose_kategori(diagnoser, diagnosekoder)
        assert kategori == "Lang"

    def test_no_match_returns_andet(self):
        diagnosekoder = _make_diagnosekoder(
            [
                ("Cancer", "cancer"),
            ]
        )
        diagnoser = [{"Kode": "DZ123", "Type": "A", "Tekst": "Knæ operation"}]

        kategori, _ = find_diagnose_kategori(diagnoser, diagnosekoder)
        assert kategori == "Andet"

    def test_empty_diagnoser(self):
        diagnosekoder = _make_diagnosekoder([("Cancer", "cancer")])
        kategori, _ = find_diagnose_kategori([], diagnosekoder)
        assert kategori == "Andet"

    def test_empty_diagnosekoder(self):
        diagnoser = [{"Kode": "DZ123", "Type": "A", "Tekst": "Cancer"}]
        kategori, _ = find_diagnose_kategori(diagnoser, [])
        assert kategori == "Andet"


class TestBasalAvanceretDiagnose:
    def test_known_categories_pass_through(self):
        diagnosekoder = _make_diagnosekoder([("Cancer", "cancer")])
        diagnoser = [{"Kode": "C50", "Type": "A", "Tekst": "cancer"}]

        _, basal = find_diagnose_kategori(diagnoser, diagnosekoder)
        assert basal == "Cancer"

    def test_amputation(self):
        diagnosekoder = _make_diagnosekoder([("Amputation", "amputation")])
        diagnoser = [{"Kode": "X", "Type": "A", "Tekst": "amputation af ben"}]

        _, basal = find_diagnose_kategori(diagnoser, diagnosekoder)
        assert basal == "Amputation"

    def test_neurologi(self):
        diagnosekoder = _make_diagnosekoder([("Neurologi", "neurologi")])
        diagnoser = [{"Kode": "X", "Type": "A", "Tekst": "neurologi behandling"}]

        _, basal = find_diagnose_kategori(diagnoser, diagnosekoder)
        assert basal == "Neurologi"

    def test_laenderygbesvaer(self):
        diagnosekoder = _make_diagnosekoder([("Ryg", "ryg")])
        diagnoser = [
            {"Kode": "X", "Type": "lænderygbesværer", "Tekst": "Ryg operation"}
        ]

        _, basal = find_diagnose_kategori(diagnoser, diagnosekoder)
        assert basal == "Kronisk lænderygbesværer"

    def test_unknown_returns_ukendt(self):
        diagnosekoder = _make_diagnosekoder([("Hofte", "hofte")])
        diagnoser = [{"Kode": "X", "Type": "A", "Tekst": "hofte operation"}]

        _, basal = find_diagnose_kategori(diagnoser, diagnosekoder)
        assert basal == "Ukendt"


class TestIndlæsDiagnosekoder:
    def test_loads_and_sorts_from_excel(self, tmp_path):
        """Integration test with a real Excel file."""
        from openpyxl import Workbook

        wb = Workbook()
        ws = wb.active
        ws.title = "Diagnoser"
        ws.append(["Cancer", "cancer"])
        ws.append(["Hånd", "hånd"])
        ws.append(["Neurologi", "dm30"])
        ws.append(["", ""])  # empty row should be filtered out

        path = tmp_path / "test_diagnoser.xlsx"
        wb.save(path)

        result = indlæs_diagnosekoder(str(path))

        assert len(result) == 3
        # Sorted by length descending: "neurologi" is not — dm30=4, hånd=4, cancer=6
        assert result[0]["Diagnose"] == "Cancer"
        assert result[0]["Laengde"] == 6
        # All search texts should be lowercase
        assert all(d["Sogetekst"] == d["Sogetekst"].lower() for d in result)
