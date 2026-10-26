# Debatstof på Render

Alt kører hos Render. Din computer skal kun have en browser.

## Opret webtjenesten

Koden i denne ændring skal først være tilgængelig på den GitHub-branch, som Render bruger.
Vælg derefter følgende i formularen **New Web Service**:

| Felt | Værdi |
| --- | --- |
| Language | Python 3 |
| Region | Frankfurt |
| Root Directory | Tomt |
| Build Command | `pip install -r requirements.txt` |
| Start Command | `python render_start.py` |
| Compute | Betalt Starter-plan med understøttelse af disk |

Under **Environment Variables** tilføjes:

| Navn | Værdi |
| --- | --- |
| `PYTHON_VERSION` | `3.12.14` |
| `DATA_DIR` | `/var/data` |
| `SQLITE_DB_PATH` | `/var/data/debatstof.db` |
| `SCRAPE_INTERVAL_SECONDS` | `3600` |
| `APP_USERNAME` | Vælg selv et brugernavn |
| `APP_PASSWORD` | Vælg en lang, unik adgangskode |

Indtast adgangskoden direkte i Render. Gem den i din adgangskodeadministrator.
Den må ikke skrives i GitHub, dokumentationen eller chatten.

Tilføj en **Persistent Disk** med:

- Mount path: `/var/data`
- Størrelse: 1 GB til at begynde med

Under avancerede indstillinger sættes **Health Check Path** til `/healthz`.
Kontrollér Render-prisen inklusive disk, før du klikker **Deploy Web Service**.
Filen `render.yaml` beskriver samme opsætning, hvis du i stedet bruger Render Blueprints.
Ved manuel oprettelse læser Render ikke automatisk denne fil.

## Hvad sker der bagefter?

Render installerer pakkerne og starter appen med Gunicorn. Åbn den HTTPS-adresse,
Render viser; browseren beder om det valgte brugernavn og adgangskode.
Brug altid HTTPS. Login er browserens almindelige adgangskodevindue; luk browseren
eller brug et privat vindue, hvis du skal afslutte den gemte login-session.

Scraperen starter automatisk kort efter serverstart og kører igen en time efter,
at sidste kørsel er afsluttet. Intervallet kan ændres med `SCRAPE_INTERVAL_SECONDS`
(minimum 300). Kørsler overlapper ikke. Ved genstart køres scraperen igen.

Database, artikel-JSON og feedback gemmes på disken under `/var/data`.
De overlever genstart og ny udrulning, så længe du beholder disken og samme stier.
Eksisterende lokale artikler overføres ikke automatisk. Start med en tom database,
eller overfør en kopi af din eksisterende SQLite-database til disken inden brug.
En varig disk er ikke i sig selv en uafhængig sikkerhedskopi.

Hold tjenesten på én instans. SQLite og JSON-filer deles mellem app og scraper på
samme disk. Denne opsætning er beregnet til et lille, privat værktøj.
Google Sheets bruges ikke af den aktuelle scraperkørsel og kræver ingen nøgle her.

## Kontrollér første udrulning

1. Kontrollér at tjenesten bliver markeret som **Live**.
2. Åbn appen uden login: der skal vises en adgangskodeforespørgsel.
3. Log ind og kontrollér forsiden, Topscorere og Statistik.
4. Følg scraperens output under **Logs**. Der skal findes rigtige artikler;
   en kørsel med nul artikler eller HTTP 403 beviser ikke, at indsamlingen virker.
5. Markér en artikel som interessant, genstart tjenesten, og kontrollér at artiklen
   og feedbacken stadig findes.

Nogle medier kan afvise cloudservere. HTTP 403 på Render skal undersøges pr. medie;
en tilladelse i Codex' netværksindstillinger ændrer ikke Render-netværket.

## Udvikling og test

Python 3.12 anbefales:

```sh
pip install -r requirements.txt
python -m unittest discover -s tests -v
```

Lokalt bruges som standard `Fælles-data/`. `DATA_DIR` og `SQLITE_DB_PATH` kan ændre
stierne. En eventuel `Config-filer/.env` indlæses, men er ikke påkrævet.
På Render nægter appen at starte uden begge loginvariabler.

Manuel, begrænset prøve uden SQLite-skrivning:

```sh
python run_scraper.py --dry-run --only Altinget --limit-per-source 1
```

`--dry-run` skriver stadig JSON. Brug en separat `DATA_DIR` ved eksperimenter, så
produktionsfiler ikke erstattes. Statistik kan vises med `python run_scraper.py --db-stats`.

## Importér en tidligere database

Åbn `/import` i appen, mens du er logget ind. Vælg din gamle `debatstof.db` og
klik **Importér artikler**. Filen uploades direkte til din Render-tjeneste og
slettes fra den midlertidige uploadmappe efter behandlingen. Den lægges ikke i GitHub.

Importen tager først en sikkerhedskopi af den aktive SQLite-database i
`/var/data/backups/`. Derefter tilføjes artikler, som ikke allerede findes via id
eller normaliseret URL. Eksisterende artikler og feedback overskrives ikke.
Gamle feedbackmarkeringer tilføjes kun for URL'er, som endnu ikke har feedback.
Gentaget import skaber ikke dubletter. Historiske kørselslogs importeres ikke.

Under **Arkiv – alle artikler** vises både gamle og nye artikler, 100 pr. side.
Forsiden beholder sin afgrænsning til de seneste syv dage. I arkivet kan du også
filtrere efter medie, debatspor og interessante artikler.

## Alle tre apps på den eksisterende tjeneste

TV 2-regionerne og de internationale medier er integreret i Flask-appen på
`/rss/tv2` og `/rss/international`. De bruger samme login, server og disk som
Debatstof. Der skal ikke oprettes en ekstra Render-tjeneste eller installeres
Streamlit. Startkommando og eksisterende miljøvariabler ændres ikke.

Kildekonfigurationen og RSS-arbejdsgangen er overført fra
`lmesben-afk/TV2-regioner_scraper` (render-deployment, 2146c2b). Det oprindelige
repository er bevaret, men behøver ikke deployes separat.

RSS-data gemmes i `DATA_DIR/rss.db`, adskilt fra den eksisterende debatstofdatabase.
`RSS_DB_PATH` kan valgfrit ændre placeringen; det er ikke nødvendigt på Render.
RSS-funktionen overskriver ikke debatstofartikler eller feedback.

Klik **Opdater nu** i den ønskede RSS-app. Opdateringen sættes i kø og kører i
baggrunden; siden viser fremskridt og genindlæses, mens opdateringen er aktiv.
Der kører højst én RSS-opdatering ad gangen, og op til fire feeds hentes parallelt.
Du kan fortsat bruge alle sider imens. Dobbeltklik opretter ikke ekstra job.
Ingen RSS-opdateringer startes automatisk, når siden er lukket.

Dagens artikler og læsemarkeringer gemmes i databasen. Listen viser indsamling
siden dansk midnat (Europe/Copenhagen), ligesom de tidligere RSS-apps. Artikler
forsvinder ikke fra dagens liste, fordi de falder ud af feedet. Det samme feed
skaber ikke dubletter ved gentagen opdatering. “NY” angiver artikler indsamlet
siden seneste besøg på den pågældende region/medie; åbnede artikler markeres “LÆST”.
Manchetter tages fra RSS; mangler de, forsøges metadata fra artikelsiden.

Ved en afbrudt opdatering (fx ved deploy) bevares allerede gemte artikler, og siden
beder om at klikke **Opdater nu** igen. Delvist fejlede feeds vises med navn.
Et HTTP-sundhedstjek på `/healthz` verificerer serveren, ikke medieadgang.

Første kontrol på Render: log ind, åbn begge RSS-sider, klik **Opdater nu**, og
kontrollér rigtige artikler og eventuelle mediefejl. Åbn en artikel og kontrollér
læsemarkering efter genindlæsning/genstart samme dag. Live RSS var afvist af
Codex-netværksproxyen under udvikling og skal derfor verificeres på Render.
De automatiske tests bruger prøvefeeds og verificerer baggrundsjob, dagsskift,
læsemarkeringer, genstart, dubletter og eksisterende debatstoffunktioner.
