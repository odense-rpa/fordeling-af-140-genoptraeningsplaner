from unittest.mock import AsyncMock
from dataclasses import dataclass

import pytest

from fordeling_af_140_genoptraeningsplaner.placering import (
    _map_organisation,
    beslut_placering,
    bestem_adresse_område,
    kontroller_lysningen,
)


@dataclass
class MockPrediction:
    categorical_answer: str
    numeric_answer: float | None = None
    confidence: float = 0.95


def _make_sue():
    sue = AsyncMock()
    sue.spørg_sue = AsyncMock(
        return_value=MockPrediction(categorical_answer="Genoptræning Nord")
    )
    return sue


def _base_item_data(**overrides):
    defaults = {
        "alder": 50,
        "aldersgruppe": "< 67",
        "diagnose": "Hofte",
        "basal_avanceret_diagnose": "Ukendt",
        "adresse": "Nord",
        "hjemmepleje": "Nej",
        "afsender": "5790002282157",
        "placering": "",
    }
    defaults.update(overrides)
    return defaults


class TestBeslutPlacering:
    @pytest.mark.asyncio
    async def test_already_decided_skips_sue(self):
        """If placering is already set (e.g. specialiseret), skip Sue."""
        sue = _make_sue()
        item = _base_item_data(placering="Genoptræning Syd")

        result = await beslut_placering(item, sue)

        assert result["placering"] == "Genoptræning Syd"
        assert result["organisation_navn"] == "Genoptræning Team Syd"
        # Sue should still be called for treatment form
        assert sue.spørg_sue.call_count >= 1

    @pytest.mark.asyncio
    async def test_child_non_hand_goes_to_team_odense(self):
        sue = _make_sue()
        item = _base_item_data(alder=10, diagnose="Knæ")

        result = await beslut_placering(item, sue)

        assert result["placering"] == "Genoptræning Team Odense"
        assert result["organisation_navn"] == "Genoptræning Team Odense"

    @pytest.mark.asyncio
    async def test_child_hand_nord(self):
        sue = _make_sue()
        item = _base_item_data(alder=15, diagnose="Hånd", adresse="Nord")

        result = await beslut_placering(item, sue)

        assert result["placering"] == "Genoptræning Team Nord"

    @pytest.mark.asyncio
    async def test_child_hand_syd(self):
        sue = _make_sue()
        item = _base_item_data(alder=15, diagnose="Hånd", adresse="Syd")

        result = await beslut_placering(item, sue)

        assert result["placering"] == "Genoptræning Team Syd"

    @pytest.mark.asyncio
    async def test_child_hand_5000_nord(self):
        sue = _make_sue()
        item = _base_item_data(alder=15, diagnose="Hånd", adresse="5000 Nord")

        result = await beslut_placering(item, sue)

        assert result["placering"] == "Genoptræning Team Nord"

    @pytest.mark.asyncio
    async def test_adult_uses_sue_prediction(self):
        sue = _make_sue()
        sue.spørg_sue = AsyncMock(
            return_value=MockPrediction(categorical_answer="Team Odense")
        )
        item = _base_item_data(alder=50)

        result = await beslut_placering(item, sue)

        assert result["placering"] == "Team Odense"
        assert result["organisation_navn"] == "Genoptræning Team Odense"

    @pytest.mark.asyncio
    async def test_sue_placement_model_receives_correct_params(self):
        sue = _make_sue()
        item = _base_item_data(
            alder=70,
            aldersgruppe="67 - 74",
            diagnose="Hofte",
            adresse="5000 Syd",
            hjemmepleje="Ja",
        )

        await beslut_placering(item, sue)

        # First call = placement model
        call_args = sue.spørg_sue.call_args_list[0]
        assert call_args[0][0] == "4168139e-ef93-4290-acec-d2cd175daab4"
        values = call_args[0][1]
        assert values["Adresse"] == "5000 Syd"
        assert values["Alder"] == "67 - 74"
        assert values["Diagnose"] == "Hofte"
        assert values["Hjemmepleje"] == "Ja"

    @pytest.mark.asyncio
    async def test_treatment_model_defaults_to_basal_on_error(self):
        sue = _make_sue()
        call_count = 0

        async def side_effect(model_id, values, version=-1):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return MockPrediction(categorical_answer="Genoptræning Nord")
            raise Exception("Sue model error")

        sue.spørg_sue = AsyncMock(side_effect=side_effect)
        item = _base_item_data(alder=50)

        result = await beslut_placering(item, sue)

        assert result["behandlingsform"] == "Basal"


class TestOrgMapping:
    def test_all_known_mappings(self):
        assert _map_organisation("Genoptræning Nord") == "Genoptræning Team Nord"
        assert _map_organisation("Genoptræning Syd") == "Genoptræning Team Syd"
        assert _map_organisation("Team Odense") == "Genoptræning Team Odense"
        assert _map_organisation("CKOP") == "Rehabilitering og palliation"
        assert _map_organisation("Lysningen") == "Lysningen Træning"

    def test_unknown_passes_through(self):
        assert _map_organisation("Something Else") == "Something Else"

    def test_already_mapped_passes_through(self):
        assert _map_organisation("Genoptræning Team Nord") == "Genoptræning Team Nord"


class TestBestemAdresseOmraade:
    def test_nord_centrum(self):
        assert bestem_adresse_område({"omrAltNavn": "Nord Centrum"}) == "5000 Nord"

    def test_syd_centrum(self):
        assert bestem_adresse_område({"omrAltNavn": "Syd Centrum"}) == "5000 Syd"

    def test_borger_omraade_nord(self):
        lokation = {"omrAltNavn": "Andet", "borgerOmraade": "Nord Øst"}
        assert bestem_adresse_område(lokation) == "Nord"

    def test_borger_omraade_syd(self):
        lokation = {"omrAltNavn": "Andet", "borgerOmraade": "Syd Vest"}
        assert bestem_adresse_område(lokation) == "Syd"

    def test_unknown_area_raises(self):
        with pytest.raises(ValueError, match="Kunne ikke bestemme"):
            bestem_adresse_område({"omrAltNavn": "X", "borgerOmraade": "X"})


class TestKontrollerLysningen:
    def test_not_supplementary_returns_false(self):
        borger = {"currentAddressIndicator": "PRIMARY_ADDRESS"}
        assert kontroller_lysningen(borger) is False

    def test_supplementary_with_lysningen(self):
        borger = {
            "currentAddressIndicator": "SUPPLEMENTARY_ADDRESS",
            "supplementaryAddress": {
                "addressLine1": "Lysningen",
                "addressLine2": "Østerdalen 2",
                "addressLine3": "",
                "addressLine4": "",
                "addressLine5": "",
            },
        }
        assert kontroller_lysningen(borger) is True

    def test_supplementary_with_osterdalen(self):
        borger = {
            "currentAddressIndicator": "SUPPLEMENTARY_ADDRESS",
            "supplementaryAddress": {
                "addressLine1": "Østerdalen 2",
                "addressLine2": "",
                "addressLine3": "",
                "addressLine4": "",
                "addressLine5": "",
            },
        }
        assert kontroller_lysningen(borger) is True

    def test_supplementary_without_lysningen(self):
        borger = {
            "currentAddressIndicator": "SUPPLEMENTARY_ADDRESS",
            "supplementaryAddress": {
                "addressLine1": "Vestergade 10",
                "addressLine2": "5000 Odense C",
                "addressLine3": "",
                "addressLine4": "",
                "addressLine5": "",
            },
        }
        assert kontroller_lysningen(borger) is False

    def test_missing_indicator_returns_false(self):
        assert kontroller_lysningen({}) is False
