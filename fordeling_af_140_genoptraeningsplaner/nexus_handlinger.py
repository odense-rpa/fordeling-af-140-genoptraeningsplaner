"""Nexus operations: calendar check, pathways, organization, interventions, GGOP."""

import logging
from datetime import date, timedelta

from gadefortegnelsen import Gadefortegnelsen
from kmd_nexus_client import NexusClientManager

from .placering import bestem_adresse_område, kontroller_lysningen

logger = logging.getLogger(__name__)


async def hent_oplysninger_fra_nexus(
    borger: dict,
    nexus: NexusClientManager,
    gadefortegnelsen: Gadefortegnelsen,
    cpr: str,
) -> dict:
    """Get home care status + address area from Nexus calendar and Gadefortegnelsen.

    Returns dict with keys: hjemmepleje, adresse, er_lysningen.
    """
    # 1. Check calendar for home care events
    kalender = nexus.kalender.hent_kalender(borger)
    i_dag = date.today()
    begivenheder = nexus.kalender.hent_begivenheder(
        kalender, i_dag, i_dag + timedelta(days=10)
    )

    hjemmepleje = "Nej"
    if isinstance(begivenheder, dict):
        events = begivenheder.get("events", begivenheder.get("items", []))
    elif isinstance(begivenheder, list):
        events = begivenheder
    else:
        events = []

    for event in events:
        desc = (event.get("dashboardDescription") or "").lower()
        supplier = (event.get("supplier") or "").lower()
        if ("personlig hygiejne" in desc and "(indlagt pa sygehus)" not in desc) or (
            "sosu" in supplier
        ):
            hjemmepleje = "Ja"
            break

    # 2. Look up address area via Gadefortegnelsen
    lokation = await gadefortegnelsen.hent_borger(cpr)
    adresse = bestem_adresse_område(lokation)

    # 3. Check if citizen lives at Lysningen
    er_lysningen = kontroller_lysningen(borger)

    return {
        "hjemmepleje": hjemmepleje,
        "adresse": adresse,
        "er_lysningen": er_lysningen,
    }


def opret_forløb(borger: dict, nexus: NexusClientManager) -> None:
    """Create FSIII, Korrespondance, and MedCom pathways on the citizen.

    Only called for 'almen' GOP type.
    """
    forløb_liste = [
        ("Sundhedsfagligt grundforløb", "FSIII"),
        ("Sundhedsfagligt grundforløb", "Korrespondance - Genoptræningsplan SUL §140"),
        ("MedCom", None),
    ]

    for grundforløb, forløb_navn in forløb_liste:
        nexus.forløb.opret_forløb(borger, grundforløb, forløb_navn)


def tilføj_organisation(
    borger: dict, organisation_navn: str, nexus: NexusClientManager
) -> None:
    """Add organization to citizen and set as primary contact."""
    organisation = nexus.organisationer.hent_organisation_ved_navn(organisation_navn)
    if organisation is None:
        raise ValueError(f"Organisation '{organisation_navn}' ikke fundet i Nexus")

    nexus.organisationer.tilføj_borger_til_organisation(borger, organisation)

    # Find the new relation and set as primary
    relationer = nexus.organisationer.hent_organisationer_for_borger(borger)
    relation = next(
        (
            r
            for r in relationer
            if r.get("organization", {}).get("name") == organisation_navn
        ),
        None,
    )
    if relation is None:
        raise ValueError(
            f"Relation til '{organisation_navn}' ikke fundet efter tilknytning"
        )

    nexus.organisationer.opdater_borger_organisations_relation(
        relation, slut_dato=None, primær_organisation=True
    )


def opret_indsatser(
    borger: dict,
    behandlingsform: str,
    placering: str,
    gop_dato: str,
    nexus: NexusClientManager,
) -> None:
    """Create interventions: 'Kroppens funktioner' + basal/avanceret grant."""
    indsatser_at_oprette = [
        {
            "indsats": "Kroppens funktioner SUL § 140",
            "forløb": "FSIII",
            "grundforløb": "Sundhedsfagligt grundforløb",
            "oprettelsesform": "Tildel, Bestil",
        },
    ]

    if behandlingsform == "Basal":
        indsatser_at_oprette.append(
            {
                "indsats": "Genoptræning basal genoptræning (SUL § 140)",
                "forløb": "FSIII",
                "grundforløb": "Sundhedsfagligt grundforløb",
                "oprettelsesform": "Tildel, Bestil",
            }
        )
    else:
        indsatser_at_oprette.append(
            {
                "indsats": "Genoptræning avanceret genoptræning (SUL § 140)",
                "forløb": "FSIII",
                "grundforløb": "Sundhedsfagligt grundforløb",
                "oprettelsesform": "Tildel, Bestil",
            }
        )

    # Check existing active interventions to avoid duplicates
    visning = nexus.borgere.hent_visning(borger) or {}
    referencer = nexus.borgere.hent_referencer(visning)
    indsatsreferencer = nexus.indsatser.filtrer_indsats_referencer(
        referencer,
        kun_aktive=True,
    )

    eksisterende_navne = {ref.get("name", "") for ref in indsatsreferencer}

    felter = {
        "allocationDate": gop_dato,
        "orderedDate": gop_dato,
        "entryDate": gop_dato,
    }

    for indsats_def in indsatser_at_oprette:
        if indsats_def["indsats"] in eksisterende_navne:
            logger.info(
                f"Indsats '{indsats_def['indsats']}' eksisterer allerede, springer over"
            )
            continue

        nexus.indsatser.opret_indsats(
            borger=borger,
            grundforløb=indsats_def["grundforløb"],
            forløb=indsats_def["forløb"],
            indsats=indsats_def["indsats"],
            felter=felter,
            leverandør=placering,
            oprettelsesform=indsats_def["oprettelsesform"],
        )


def afslut_ggop(
    borger: dict,
    besked_id: int,
    placering: str,
    gop_dato: date,
    nexus: NexusClientManager,
) -> None:
    """Assign message to MedCom pathway, create task, accept message."""
    # Find MedCom forløb
    forløb_liste = nexus.borgere.hent_aktive_forløb(borger)
    medcom_forløb = next((f for f in forløb_liste if f.get("name") == "MedCom"), None)

    # Fetch the message again by ID
    beskeder = nexus.medcom.hent_alle_beskeder(borger)
    besked_ref = next((b for b in beskeder if b.get("id") == besked_id), None)
    if besked_ref is None:
        raise ValueError(f"MedCom besked {besked_id} ikke fundet")
    besked = nexus.medcom.hent_besked(besked_ref) or {}

    # Assign message to MedCom pathway
    if medcom_forløb is not None:
        nexus.medcom.tildel_til_forloeb_ved_navn(besked, "MedCom")

    # Create task (skip for Lysningen Træning)
    if placering != "Lysningen Træning":
        nexus.opgaver.opret_opgave(
            objekt=besked,
            opgave_type="Venter på planlægning § 140",
            titel="Behandlet af Tyra",
            ansvarlig_organisation=placering,
            start_dato=gop_dato,
            forfald_dato=gop_dato + timedelta(days=7),
        )

    # Accept the message
    try:
        nexus.medcom.accepter_besked(besked)
    except Exception as e:
        if "accept" in str(e).lower():
            logger.warning(f"Accepter besked fejlede (ignorerer): {e}")
        else:
            raise


def opret_diagnoseskemaer(
    borger: dict, diagnoser: list[dict], nexus: NexusClientManager
) -> None:
    """Create ICD-10 diagnosis schemas for each diagnosis code.

    Skips creation if an active schema with the same diagnosis code already exists.
    """
    for diag in diagnoser:
        kode = diag.get("Kode", "")
        if not kode:
            continue

        # Check for existing active schema with same code
        if _har_aktivt_diagnoseskema(borger, kode, nexus):
            logger.info(f"Aktivt diagnoseskema for {kode} eksisterer allerede")
            continue

        try:
            nexus.skemaer.opret_komplet_skema(
                borger=borger,
                skematype_navn="Diagnose ICD-10",
                handling_navn="Aktivt",
                data={"Diagnose": kode},
            )
        except Exception as e:
            logger.error(f"Fejl ved oprettelse af diagnoseskema for {kode}: {e}")
            continue


def _har_aktivt_diagnoseskema(
    borger: dict, kode: str, nexus: NexusClientManager
) -> bool:
    """Check if an active ICD-10 diagnosis schema exists for the given code."""
    try:
        skemareferencer = nexus.skemaer.hent_skemareferencer(borger)
    except Exception:
        return False

    for ref in skemareferencer:
        form_def = ref.get("formDefinition", {})
        if form_def.get("title") != "Diagnose ICD-10":
            continue
        if not form_def.get("active", False):
            continue

        try:
            skema = nexus.hent_fra_reference(ref)
            diagnose_value = nexus.skemaer.get_field_value(skema, "Diagnose")
            if diagnose_value == kode:
                return True
        except Exception:
            continue

    return False
