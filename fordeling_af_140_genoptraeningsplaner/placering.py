"""Placement decision logic: Sue ML predictions + business rules."""

import logging

from sue import SueClient

logger = logging.getLogger(__name__)

PLACEMENT_MODEL = "4168139e-ef93-4290-acec-d2cd175daab4"
TREATMENT_MODEL = "e32580fb-e778-473d-a104-0013bc23f441"

# Maps Sue/BP placement names → Nexus organization names
ORG_MAPPING = {
    "Genoptræning Nord": "Genoptræning Team Nord",
    "Genoptræning Syd": "Genoptræning Team Syd",
    "Team Odense": "Genoptræning Team Odense",
    "CKOP": "Rehabilitering og palliation",
    "Lysningen": "Lysningen Træning",
}


async def beslut_placering(item_data: dict, sue: SueClient) -> dict:
    """Determine placement and treatment form for a GOP item.

    Applies business rules for children and specialiseret plans,
    then falls back to Sue ML predictions for adult almen plans.
    """
    # Skip if already decided (e.g. specialiseret → set in indlæs_gop)
    if item_data.get("placering"):
        item_data["organisation_navn"] = _map_organisation(item_data["placering"])
        item_data["behandlingsform"] = await _beslut_behandlingsform(item_data, sue)
        return item_data

    alder = item_data["alder"]
    diagnose = item_data["diagnose"]
    adresse = item_data.get("adresse", "")

    # Children under 18
    if alder < 18:
        if diagnose == "Hånd":
            if "Nord" in adresse:
                item_data["placering"] = "Genoptræning Team Nord"
            else:
                item_data["placering"] = "Genoptræning Team Syd"
        else:
            item_data["placering"] = "Genoptræning Team Odense"

        item_data["organisation_navn"] = item_data["placering"]
        item_data["behandlingsform"] = await _beslut_behandlingsform(item_data, sue)
        return item_data

    # Adults: ask Sue for placement
    values = {
        "Adresse": item_data.get("adresse", ""),
        "Alder": item_data["aldersgruppe"],
        "Diagnose": item_data["diagnose"],
        "Hjemmepleje": item_data.get("hjemmepleje", "Nej"),
    }

    prediction = await sue.spørg_sue(PLACEMENT_MODEL, values)
    item_data["placering"] = prediction.categorical_answer
    item_data["organisation_navn"] = _map_organisation(item_data["placering"])

    # Determine treatment form
    item_data["behandlingsform"] = await _beslut_behandlingsform(item_data, sue)

    return item_data


async def _beslut_behandlingsform(item_data: dict, sue: SueClient) -> str:
    """Ask Sue ML model for basal/avanceret treatment form."""
    values = {
        "Afdeling": item_data.get("afsender", "Ukendt"),
        "Diagnose": item_data.get("basal_avanceret_diagnose", "Ukendt"),
    }

    try:
        prediction = await sue.spørg_sue(TREATMENT_MODEL, values)
        return prediction.categorical_answer
    except Exception:
        logger.warning("Sue behandlingsform model fejlede, falder tilbage til Basal")
        return "Basal"


def _map_organisation(placering: str) -> str:
    """Map a placement name to the Nexus organization name."""
    return ORG_MAPPING.get(placering, placering)


def bestem_adresse_område(lokation: dict) -> str:
    """Classify address area from Gadefortegnelsen data.

    Returns one of: "5000 Nord", "5000 Syd", "Nord", "Syd".
    """
    omr_alt_navn = lokation.get("omrAltNavn", "")
    borger_omraade = lokation.get("borgerOmraade", "")

    if omr_alt_navn == "Nord Centrum":
        return "5000 Nord"
    elif omr_alt_navn == "Syd Centrum":
        return "5000 Syd"
    elif borger_omraade.startswith("Nord"):
        return "Nord"
    elif borger_omraade.startswith("Syd"):
        return "Syd"
    else:
        raise ValueError(
            f"Kunne ikke bestemme adresseområde: "
            f"omrAltNavn={omr_alt_navn!r}, borgerOmraade={borger_omraade!r}"
        )


def kontroller_lysningen(borger: dict) -> bool:
    """Check if citizen lives at Lysningen (supplementary address).

    Returns True if the citizen's supplementary address contains
    'østerdalen 2' or 'lysningen'.
    """
    if borger.get("currentAddressIndicator") != "SUPPLEMENTARY_ADDRESS":
        return False

    supp = borger.get("supplementaryAddress", {})
    adresse_lines = " ".join(
        str(supp.get(f"addressLine{i}", "") or "") for i in range(1, 6)
    ).lower()

    return "østerdalen 2" in adresse_lines or "lysningen" in adresse_lines
