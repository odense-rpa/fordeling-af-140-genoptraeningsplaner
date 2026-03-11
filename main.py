"""Entry point: populate queue and process §140 rehabilitation plan distribution."""

import argparse
import asyncio
import logging
from datetime import date

from automation_server_client import (
    AutomationServer,
    Credential,
    WorkItemError,
    WorkItemStatus,
    Workqueue,
)
from datafordeler import Datafordeler
from gadefortegnelsen import Gadefortegnelsen
from kmd_nexus_client import NexusClientManager
from odk_tools.reporting import report
from odk_tools.tracking import Tracker
from sue import SueClient

from fordeling_af_140_genoptraeningsplaner.diagnose_opslag import indlæs_diagnosekoder
from fordeling_af_140_genoptraeningsplaner.indlaes_borger import indlæs_borger
from fordeling_af_140_genoptraeningsplaner.indlaes_gop import indlæs_gop
from fordeling_af_140_genoptraeningsplaner.nexus_handlinger import (
    afslut_ggop,
    hent_oplysninger_fra_nexus,
    opret_diagnoseskemaer,
    opret_henvisningsskema,
    opret_forløb,
    opret_indsatser,
    sæt_ggop_niveau,
    tilføj_organisation,
)
from fordeling_af_140_genoptraeningsplaner.placering import beslut_placering


PROCESS_NAME = "Fordeling af §140 genoptræningsplaner"
PROCESS_ID = "fordeling_af_140_genoptraeningsplaner"


async def populate_queue(workqueue: Workqueue, nexus: NexusClientManager):
    logger = logging.getLogger(__name__)

    """Fetch MedCom GOP activity list and add items to queue."""
    aktiviteter = nexus.aktivitetslister.hent_aktivitetsliste(
        "MedCom - Genoptræningsplaner", None, None, 5
    )

    if not aktiviteter:
        logger.info("Ingen aktiviteter fundet")
        return

    for aktivitet in aktiviteter:
        cpr = (
            aktivitet.get("patients", {})[0]
            .get("patientIdentifier", {})
            .get("identifier", "")
            .replace("-", "")
        )

        workqueue.add_item(
            {
                "Id": aktivitet.get("id"),
                "Cpr": cpr,
                "Gop dato": aktivitet.get("date", ""),
            },
            cpr,
        )

    logger.info(f"Tilføjede {len(aktiviteter)} aktiviteter til køen")


async def process_workqueue(
    workqueue,
    nexus: NexusClientManager,
    sue: SueClient,
    gadefortegnelsen: Gadefortegnelsen,
    datafordeler: Datafordeler,
    diagnosekoder: list[dict],
    tracker: Tracker,
):
    logger = logging.getLogger(__name__)

    """Process each work queue item: load citizen, parse GOP, decide placement."""
    for item in workqueue:
        with item:
            data = item.data

            try:
                # 1. Load citizen (municipality check + Nexus fetch)
                borger = indlæs_borger(data["Cpr"], nexus, datafordeler)

                # 2. Parse GOP message
                gop_data = indlæs_gop(data["Id"], borger, nexus, diagnosekoder)

                # 3. Get home care status and address area
                nexus_data = await hent_oplysninger_fra_nexus(
                    borger, nexus, gadefortegnelsen, data["Cpr"]
                )

                # 4. Merge all data
                item_data = {**data, **gop_data, **nexus_data}

                # 5. Override placement if citizen lives at Lysningen
                if nexus_data["er_lysningen"]:
                    item_data["placering"] = "Lysningen Træning"

                # 6. Decide placement and treatment form
                item_data = await beslut_placering(item_data, sue)

                # 7. Create pathways (only for almen)
                if item_data["gop_type"] == "almen":
                    opret_forløb(borger, nexus)

                    # 8. Add organization
                    tilføj_organisation(borger, item_data["organisation_navn"], nexus)

                    # 9. Create interventions
                    opret_indsatser(
                        borger,
                        item_data["behandlingsform"],
                        item_data["organisation_navn"],
                        item_data.get("gop_dato", ""),
                        nexus,
                    )

                    # 10. Opret henvisningsskema
                    opret_henvisningsskema(borger, item_data.get("gop_dato", ""), nexus)

                    # 11. Finalize GGOP
                    afslut_ggop(
                        borger,
                        data["Id"],
                        item_data["organisation_navn"],
                        item_data.get("gop_dato", ""),
                        nexus,
                    )

                    sæt_ggop_niveau(borger, data["Id"], "BASIC", nexus)

                    # 11. Create diagnosis schemas
                    opret_diagnoseskemaer(borger, item_data["diagnoser"], nexus)

                    # 12. Reporting - Ikke for specialicerede.
                    _log_placering(item_data)
                    if item_data.get("diagnose") == "Andet":
                        _log_diagnoser(item_data)
                    tracker.track_task(PROCESS_NAME)
                else:
                    sæt_ggop_niveau(borger, data["Id"], "ADVANCED", nexus)

            except WorkItemError as e:
                logger.error(f"Fejl ved behandling af item: {data}. Fejl: {e}")
                item.fail(str(e))


def _log_placering(item_data: dict):
    """Report placement data."""
    report(
        PROCESS_ID,
        "Fordelte planer",
        {
            "Dato": str(item_data.get("gop_dato", date.today())),
            "Cpr": item_data.get("Cpr", ""),
            "Alder": item_data.get("alder", ""),
            "Diagnose": item_data.get("diagnose", ""),
            "Område": item_data.get("adresse", ""),
            "Hjemmepleje": item_data.get("hjemmepleje", ""),
            "Placering": item_data.get("placering", ""),
        },
    )


def _log_diagnoser(item_data: dict):
    """Report individual diagnosis codes (only for 'Andet' category)."""
    for diag in item_data.get("diagnoser", []):
        report(
            PROCESS_ID,
            "Diagnoser",
            {
                "Dato": str(item_data.get("gop_dato", date.today())),
                "Cpr": item_data.get("Cpr", ""),
                "Kode": diag.get("Kode", ""),
                "Type": diag.get("Type", ""),
                "Tekst": diag.get("Tekst", ""),
            },
        )


def main():
    parser = argparse.ArgumentParser(description=PROCESS_NAME)
    parser.add_argument(
        "--excel-file", required=True, help="Path to diagnosis codes Excel file"
    )
    args, remaining = parser.parse_known_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    ats = AutomationServer.from_environment()
    workqueue = ats.workqueue()

    # Credentials
    nexus_cred = Credential.get_credential("KMD Nexus - produktion")
    sue_cred = Credential.get_credential("Sue")
    gadefortegnelsen_cred = Credential.get_credential("Gadefortegnelsen")
    roboa_cred = Credential.get_credential("RoboA")
    tracking_cred = Credential.get_credential("Odense SQL Server")

    # Initialize clients
    nexus = NexusClientManager(
        instance=nexus_cred.data["instance"],
        client_id=nexus_cred.username,
        client_secret=nexus_cred.password,
    )

    datafordeler = Datafordeler(
        certifikat_sti="/certifikater/datafordeler.crt",
        certifikat_nøglefil="/certifikater/datafordeler.key",
        # certifikat_sti="certifikater/datafordeler.crt",
        # certifikat_nøglefil="certifikater/datafordeler.key",
    )

    tracker = Tracker(tracking_cred.username, tracking_cred.password)
    diagnosekoder = indlæs_diagnosekoder(args.excel_file)

    if "--queue" in remaining:
        workqueue.clear_workqueue(WorkItemStatus.NEW)
        asyncio.run(populate_queue(workqueue, nexus))
        return

    async def run():
        async with (
            SueClient(sue_cred.username, sue_cred.password) as sue,
            Gadefortegnelsen(
                password=gadefortegnelsen_cred.password,
                ntlm_username=roboa_cred.username,
                ntlm_password=roboa_cred.password,
                verify=False,  # Our internal SSL is broken
            ) as gadefortegnelsen,
        ):
            await process_workqueue(
                workqueue,
                nexus,
                sue,
                gadefortegnelsen,
                datafordeler,
                diagnosekoder,
                tracker,
            )

    asyncio.run(run())


if __name__ == "__main__":
    main()
