"""Citizen loading: municipality verification, Nexus fetch, draft activation."""

from automation_server_client import WorkItemError
from datafordeler import Datafordeler
from kmd_nexus_client import NexusClientManager


def indlæs_borger(
    cpr: str,
    nexus: NexusClientManager,
    datafordeler: Datafordeler,
) -> dict:
    """Load citizen: verify Odense municipality, fetch from Nexus, activate if draft.

    Raises WorkItemError if citizen is not in Odense municipality or
    cannot be activated from draft status.
    """
    # 1. Verify citizen lives in Odense (kommunekode 461)
    adresse = datafordeler.hent_aktiv_adresse(cpr)
    kommunekode = (
        adresse.get("Adresseoplysninger", {})
        .get("CprAdresse", {})
        .get("cprKommunekode", "")
    )
    try:
        if int(kommunekode) != 461:
            raise WorkItemError("Borgeren bor ikke i Odense kommune")
    except (ValueError, TypeError):
        raise WorkItemError("Borgeren bor ikke i Odense kommune")

    # 2. Fetch citizen from Nexus
    borger = nexus.borgere.hent_borger(cpr)
    if borger is None:
        raise WorkItemError(f"Borgeren med CPR {cpr} blev ikke fundet i Nexus")

    # 3. Activate from draft if needed
    if borger.get("patientStatus") == "DRAFT":
        borger = nexus.borgere.aktiver_borger_fra_kladde(borger)
        if borger is None:
            raise WorkItemError("Borgeren kunne ikke sættes ud af draft")

    return borger
