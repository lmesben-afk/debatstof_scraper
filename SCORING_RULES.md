# Redaktionelle regler, version editorial-2026-10-v2

Formålet er at finde potentielle JP-historier om frihed/ansvar, erhverv, geografiske
konsekvenser og konkrete værdikonflikter. Hver tildeling forklares i artikeldata.
Rubrik og manchet er datagrundlaget; reglerne verificerer ikke påstande og kender
ikke nødvendigvis hele indlæggets argument. De vurderer ikke, hvilken side JP bør støtte.

- Emne- og værdirelevans: højst 20 point. Specifikke værdibegreber kan give 15;
  mikroemner giver fem hver. De to summeres ikke, så samme signal ikke tæller dobbelt.
- Kombination af relevante hensyn: 25 point i alt, uanset antal matchende kombinationer.
  Fire spor: familie/hjemmepasning og arbejdsmarked; kønsopdeling/religion/ligestilling
  og fælles faciliteter; klima/energi og lokal indflydelse; erhvervsvilkår med konsekvenser.
- Signaler om konkret beslutning/praksis, institution og berørte aktører: 15 point.
- Omtalte mulige konsekvenser i forbindelse med en sag eller kombination: 10 point.
- Konflikt om en konkret sag: 10 point, men ikke oven i kombinationsbonussen.
- Geografisk relevans i indholdet: fem point ved en konkret sag eller kombination.
  Mediets regionale status giver ikke længere point alene. Stedlisten er ikke udtømmende.
- Debatformat: fem point.
- Feedback anvendes kun i visningen, højst fem point fra det stærkeste debatspor.
  Ikke-åbnede og ikke-stjernemarkerede artikler straffes ikke. Feedback gemmes ikke
  længere oven i grundscoren ved genscoring.

Nøgleord matches som hele ord/fraser med begrænsede danske bøjningsendelser.
Udtrykkeligt markerede stammer (`*`) kan matche flere endelser. Dublerede nøgleord
skaber ikke flere hits. De eksisterende emneområder bevares og suppleres med tre
nye spor om familie/arbejde, fællesrum/ligestilling og klima/lokal indflydelse.

Den nye skala er strengere end den tidligere. Høj: mindst 60; interessant: mindst
40; overvåg: mindst 20. Topscorere og prioriterede viser mindst 40. Point er en
prioriteringsheuristik, ikke en sandsynlighed eller en valideret kvalitetsmåling.

## Kontrol og udrulning

Ved første opstart med versionen tages en SQLite-sikkerhedskopi i `backups/`, og
hele arkivet genscores. Artikeltekst, URL'er og feedback ændres ikke. Versionen
registreres i `scoring_metadata`; samme versions opstart genscorer ikke igen.
Den normale scraperkørsel vedligeholder derefter scorerne med de nye regler.

Reglerne er kontrolleret med brugerens typer af sager samt negative eksempler,
ordgrænser, feedbackloft og bevaring af feedback ved genscoring. Arkiveksportens
2.464 udviklingsartikler er sammenlignet med deres tidligere grundscorer. Den
første stramme variant udelod for mange emnesignaler og blev rettet inden udrulning.
Kontrolgruppens 606 artikler bruges til efterfølgende fordelingskontrol, ikke som
træningslabels. Der er kun tre stjerner i eksporten og ingen ekspertmærkede
rangeringer; bedre redaktionel præcision er derfor ikke dokumenteret endnu.
Næste skridt er brugerens vurdering af konkrete nye topfund og oversete artikler.
