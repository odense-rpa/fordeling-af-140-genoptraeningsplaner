"""GOP message parsing: fetch MedCom message, classify diagnosis, calculate age."""

from datetime import date

from kmd_nexus_client import NexusClientManager
from medcom_beskeder import MedcomBesked

from .diagnose_opslag import find_diagnose_kategori

KENDTE_AFSENDERE = {
    "5790002282157",
    "5790000184552",
    "5790002006159",
    "550811000005108",
    "5790001352721",
    "5790001373283",
    "5790000184293",
    "5790002014178",
}


def indlæs_gop(
    besked_id: int,
    borger: dict,
    nexus: NexusClientManager,
    diagnosekoder: list[dict],
) -> dict:
    """Fetch MedCom inbox, find message by ID, parse GGOP, classify.

    Returns dict with keys: besked, besked_id, gop_dato, gop_type,
    diagnoser, diagnose, basal_avanceret_diagnose, afsender, alder,
    aldersgruppe, xml.
    """
    # 1. Fetch all messages and find the one matching besked_id
    beskeder = nexus.medcom.hent_alle_beskeder(borger)
    besked_ref = next((b for b in beskeder if b.get("id") == besked_id), None)
    if besked_ref is None:
        raise ValueError(f"MedCom besked med id {besked_id} ikke fundet")

    # 2. Fetch full message and decode XML
    besked = nexus.medcom.hent_besked(besked_ref)
    xml = nexus.medcom.dekoder_medcom_xml(besked)
    if xml is None:
        raise ValueError(f"Kunne ikke dekode MedCom XML for besked {besked_id}")

    # 3. Parse MedCom message
    medcom = MedcomBesked(xml)
    ggop_felter = medcom.ggop_felter
    diagnoser = medcom.diagnoser
    afsender = medcom.afsender

    # 4. Determine GOP type
    gop_type = ggop_felter.get("Type", "").lower()

    # 5. Determine placering for specialiseret
    placering = ""
    if gop_type == "specialiseret":
        placering = "Genoptræning Syd"

    # 6. Classify diagnosis
    diagnose, basal_avanceret_diagnose = find_diagnose_kategori(
        diagnoser, diagnosekoder
    )

    # 7. Determine sender
    afsender_ean = afsender.get("Ean", "")
    if not afsender_ean or afsender_ean == "-":
        afsender_value = "Ukendt"
    elif afsender_ean in KENDTE_AFSENDERE:
        afsender_value = afsender_ean
    else:
        afsender_value = "Ukendt"

    # 8. Calculate age and age group from CPR
    cpr = borger.get("patientIdentifier", {}).get("identifier", "").replace("-", "")
    if not cpr:
        cpr = (
            besked.get("patients", {})
            .get("patientIdentifier", {})
            .get("identifier", "")
            .replace("-", "")
        )
    alder = beregn_alder(cpr)
    aldersgruppe = bestem_aldersgruppe(alder)

    return {
        "besked": besked,
        "gop_dato": besked.get("date", ""),
        "gop_type": gop_type,
        "diagnoser": diagnoser,
        "diagnose": diagnose,
        "basal_avanceret_diagnose": basal_avanceret_diagnose,
        "afsender": afsender_value,
        "alder": alder,
        "aldersgruppe": aldersgruppe,
        "placering": placering,
        "xml": xml,
    }


def beregn_alder(cpr: str) -> int:
    """Calculate age from CPR number's first 6 digits (ddMMyy format).

    Uses the 7th digit to determine century:
      0-3 → 1900, 4-9 depends on year (4 → 2000 if yy<=36, else 1900, etc.)
    """
    if len(cpr) < 7:
        raise ValueError(f"CPR nummer er for kort: {cpr}")

    dag = int(cpr[0:2])
    maaned = int(cpr[2:4])
    aar_2 = int(cpr[4:6])
    cifre_7 = int(cpr[6])

    # Determine century based on 7th digit and year
    if cifre_7 in (0, 1, 2, 3):
        aarhundrede = 1900
    elif cifre_7 in (4, 9):
        aarhundrede = 2000 if aar_2 <= 36 else 1900
    elif cifre_7 in (5, 6, 7, 8):
        aarhundrede = 2000 if aar_2 <= 57 else 1800
    else:
        aarhundrede = 1900

    foedselsdato = date(aarhundrede + aar_2, maaned, dag)
    i_dag = date.today()

    alder = i_dag.year - foedselsdato.year
    if (i_dag.month, i_dag.day) < (foedselsdato.month, foedselsdato.day):
        alder -= 1

    return alder


def bestem_aldersgruppe(alder: int) -> str:
    """Classify age into group string matching Sue model categories."""
    if alder < 67:
        return "< 67"
    elif alder <= 74:
        return "67 - 74"
    else:
        return "> 74"
