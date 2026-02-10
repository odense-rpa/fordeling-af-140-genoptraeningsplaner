# Fordeling af §140 genoptræningsplaner

Fordeler genoptræningsplaner (GOP) modtaget via MedCom-beskeder til de rette afdelinger i Odense Kommune.

## Hvad gør processen?

1. Henter nye GOP-aktiviteter fra Nexus' MedCom-aktivitetsliste
2. For hver plan:
   - Kontrollerer at borgeren bor i Odense (kommunekode 461)
   - Indlæser og klassificerer diagnoser ud fra en Excel-opslagstabel
   - Beregner alder og aldersgruppe fra CPR
   - Tjekker for hjemmepleje via Nexus-kalender
   - Bestemmer placering via Sue-prædiktionsmodel (eller faste regler for børn/specialiserede)
   - Opretter forløb, organisation, indsatser og diagnoseskemaer i Nexus
   - Accepterer MedCom-beskeden og opretter opgave

## Kørsel

```bash
# Fyld arbejdskøen
python -m fordeling_af_140_genoptraeningsplaner.main --excel-file diagnosekoder.xlsx --queue

# Behandl køen
python -m fordeling_af_140_genoptraeningsplaner.main --excel-file diagnosekoder.xlsx
```

`--excel-file` peger på Excel-filen med diagnosekoder (arket "Diagnoser").

## Afhængigheder

| Pakke | Formål |
|-------|--------|
| `kmd-nexus-client` | Borger, forløb, indsatser, MedCom, skemaer |
| `sue` | Prædiktionsmodeller for placering og behandlingsform |
| `gadefortegnelsen` | Adresseområde-opslag |
| `medcom-beskeder` | Parsing af MedCom XML (GGOP) |
| `datafordeler` | Kommunekode-tjek via Datafordeleren |
| `odk-tools` | Rapportering og opgaveafregning |
| `automation-server-client` | Arbejdskø og credentials |

## Licens

MIT
