# PROJECT_CONTEXT.md

## Formål

Debatstof Scraper er et internt redaktionelt værktøj udviklet til Jyllands-Posten.

Målet er ikke blot at indsamle debatindlæg og opinionsstof, men at hjælpe journalister, redaktører og nyhedschefer med at identificere historier, vinkler og debatter, som kan udvikles til journalistik.

Systemet skal derfor prioritere:

* Historiepotentiale frem for datamængde.
* Relevans frem for komplethed.
* Redaktionel værdi frem for teknisk perfektion.

---

## Bruger

Primær bruger er Esben Larsen Mikkelsen, journalist på Jyllands-Posten.

Brugeren har begrænset programmeringserfaring og arbejder primært via:

* GitHub Desktop
* Claude Code
* Claude Chat

Forklaringer bør derfor være konkrete og trin-for-trin.

---

## Nuværende arkitektur

### Centrale filer

* `run_scraper.py`

  * Hovedorkestrering af hele scraper-flowet.
  * Indlæser kilder.
  * Finder artikler.
  * Udtrækker metadata.
  * Klassificerer.
  * Eksporterer data.

* `sources.yaml`

  * Konfiguration af medier.
  * URL'er.
  * Filtreringsregler.
  * Debatsektioner.

### Mapper

#### `media_scrapers/`

Indeholder kildespecifikke scrapers.

Eksempler:

* altinget.py
* avisen_danmark.py
* berlingske.py
* fyens.py
* jydskevestkysten.py
* nordjyske.py
* sjaellandske_nyheder.py
* viborg_folkeblad.py
* stiften.py

#### `core/`

Fælles logik og datamodeller.

#### `config/`

Konfiguration.

#### `app/`

Flask-baseret webinterface til gennemgang og redaktionel feedback.

---

## Aktuelle medier

### Nationale

* Altinget
* Information
* Politiken
* Berlingske
* Kristeligt Dagblad
* Avisen Danmark

### Regionale

* Nordjyske
* Aarhus Stiftstidende
* Fyens Stiftstidende
* JydskeVestkysten
* Viborg Folkeblad
* Sjællandske Nyheder

---

## Vigtige scraping-regler

### Altinget

Altingets debatindlæg har generelt ikke manchetter.

Der skal ikke forsøges at opfinde eller generere manchetter.

Manglende manchet er korrekt adfærd.

---

### Sjællandske Nyheder

Debatindlæg identificeres typisk ved:

```text
/debat-sjaelland/
```

i URL'en.

Eksempel:

```text
https://www.sn.dk/.../debat-sjaelland/...
```

Debatsektionen er ikke triviel at scrape fra HTML alene.

Data-bridge-endpoints har vist sig mere stabile.

Ved Sjællandske Nyheder bruges billedtekst ofte som manchet.

Hvis en artikel mangler traditionel manchet, bør scraperen forsøge at hente billedtekst.

---

### JydskeVestkysten

Debatartikler kan være markeret med geografisk område i stedet for debattype.

Eksempel:

```text
Aabenraa
```

kan stå samme sted som:

```text
Læserbrev
```

hos andre medier.

Scraperen skal derfor ikke alene basere sig på typebetegnelser.

---

### Viborg Folkeblad

Debatindlæg er generelt tydeligt markeret med debattype.

---

## Produktmål

Systemet skal hjælpe med at identificere:

* Nye konflikter.
* Nye debatter.
* Nye aktører.
* Potentielle JP-historier.

Systemet er ikke bygget som et arkiv.

Systemet er bygget som et redaktionelt opdagelsesværktøj.

---

## GitHub-strategi

### Stabil branch

```text
main
```

skal altid være fungerende.

### Feature branches

Større ændringer udvikles på separate branches.

Eksempler:

```text
sqlite-output
fix-sn-manchet
add-newspaper
```

### Arbejdsgang

1. Opret branch fra main.
2. Implementér ændring.
3. Test.
4. Commit.
5. Push.
6. Merge til main.

Undgå direkte udvikling på main.

---

## Claude Code-regler

Ved større ændringer:

1. Lav først en plan.
2. Forklar hvilke filer der ændres.
3. Forklar hvorfor ændringen er nødvendig.
4. Foretag ikke omfattende ændringer uden godkendelse.

Ved arkitekturændringer skal Claude Code først præsentere et forslag.

---

## Næste større projekt

### SQLite-output

Mål:

Gem alle artikler i SQLite parallelt med eksisterende Google Sheets-output.

Google Sheets skal fortsat fungere.

SQLite skal fungere som:

* historik
* analysegrundlag
* søgeindeks
* fremtidigt datalag for webinterface

Aktuel arbejdsbranch:

```text
sqlite-output
```

SQLite skal implementeres så simpelt som muligt og uden at bryde eksisterende funktionalitet.

---

## Generelle designprincipper

Foretræk:

* Enkelhed.
* Robusthed.
* Få afhængigheder.
* Let debugging.

Undgå:

* Unødig abstraktion.
* Komplekse frameworks.
* Over-engineering.

Brugeren foretrækker forståelig kode frem for teknisk elegante, men komplekse løsninger.
