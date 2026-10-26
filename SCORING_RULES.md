# Redaktionelle regler, version editorial-2026-10-v3

Formålet er at finde potentielle JP-historier om frihed/ansvar, erhverv, geografiske
konsekvenser og værdikonflikter. Grundlaget er rubrik og manchet. Point er en
prioriteringsheuristik, ikke en sandsynlighed, faktakontrol eller kvalitetskarakter.

V2 krævede for mange samtidige signaler i kort tekst og sammenpressede arkivets
scorer. V3 giver gradvis kredit for delvis evidens og ændrer derfor også rangeringen;
scorerne ganges ikke blot med en faktor, og ingen artikel tvinges til 100.

- Emne-/værdirelevans: højst 30. Et mikroemne giver 13, to 18, tre 23, fire 28 og fem+ 30.
  Specifikke værdibegreber giver 25; højeste af de to bruges, ikke summen.
- Sammenhænge: højst 35 fra det stærkeste spor. Fuld kombination giver 35;
  to af tre nødvendige signalgrupper giver 20. En enkelt karakteristisk emnegruppe
  kan løfte samlet relevans til 10, men lægges ikke oven i et tilsvarende emnematch.
  Sporene er familie/arbejde, kønsopdeling/fællesrum, klima/lokal indflydelse og erhvervsvilkår.
- Beslutning/praksis/forslag: 15 ved omtale af beslutning, institution og berørte;
  10 ved beslutning og enten institution eller berørte; tre ved beslutningssignal alene.
  Et forslag beskrives ikke som en vedtaget lov.
- Mulige konsekvenser: fire, syv eller ti ved ét, to eller flere forskellige
  konsekvensudtryk, når der også er aktører, beslutning eller et relevant spor.
- Kritik/modstridende interesser: fem ved tilknyttet aktør eller beslutning.
  Fuld kombination får ikke yderligere konfliktpoint. Evidensdelen er samlet højst 30.
- Geografisk relevans i tekst: fem med relevant emne eller beslutning.
  Regionalt medie giver fortsat ikke point i sig selv. Stedlisten er ikke udtømmende.
- Debatformat: fem.
- Positiv feedback gives kun i visningen, højst fem fra det stærkeste debatspor.
  Manglende åbninger og stjerner straffes ikke.

Høj: mindst 60; interessant: mindst 40; overvåg: mindst 20. Topscorere viser mindst 40.
Scorer kan gå op til 100; det er ikke et mål at fordele arkivet ligeligt over skalaen.
Reglerne er symmetriske med hensyn til holdning og verificerer ikke kausalitet eller
relationer semantisk. En redaktør skal stadig vurdere fundene.

Ved første opstart tages en ny sikkerhedskopi i `backups/`, og hele arkivet genscores.
Artikeldata og stjerner bevares. Versionen gemmes i `scoring_metadata`, så samme
version ikke migreres igen ved hver genstart. Arkivfordeling, delvise og fulde
signaleksempler samt bevaring af data kontrolleres før udrulning. Ekspertmærkede
rangeringer mangler fortsat; bedre redaktionel præcision kan ikke udledes af større
scorespredning alene.

Fordelingskontrol på den uploadede eksport (3.070 artikler, grundscore uden feedback):
V2 havde interval 0–40, otte forskellige scorer og tre artikler med mindst 40 point.
V3 har interval 0–67, 44 forskellige scorer og 26 artikler med mindst 40 point,
heraf tre med mindst 60. Disse tal beskriver netop eksporten, ikke den senere
voksende live-database, og er ikke mål for redaktionel præcision.
