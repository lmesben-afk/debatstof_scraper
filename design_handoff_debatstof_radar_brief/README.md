# Handoff: Debatstof-radar — Retning B "Brief"

## Overview
Debatstof-radar er et internt redaktionelt værktøj til Jyllands-Posten. Det samler debatartikler fra danske medier i ét feed, scorer hver artikel efter dens "debatstof-potentiale" (0–100), og lader redaktionen hurtigt scanne, stjernemarkere og prioritere de mest interessante. Dette dokument beskriver **Overblik-skærmen** (hovedlisten) i designretning **B "Brief"** — et varmt, redaktionelt og lyst kort-feed.

## About the Design Files
Filerne i denne pakke er **design-referencer lavet i HTML** — en prototype, der viser det tilsigtede udseende og opførsel, **ikke produktionskode der skal kopieres direkte**. Opgaven er at **gen-skabe dette design i jeres eksisterende kodebase** (React, Vue, Svelte, hvad I nu bruger) med jeres etablerede mønstre, komponenter og biblioteker. Findes der endnu ikke et miljø, så vælg det mest passende framework til projektet og implementér designet der.

HTML-prototypen indeholder **to** retninger side om side (A "Clarity" og B "Brief"). **Kun retning B skal implementeres** — den højre frame i prototypen. Retning A er kun med som reference for, hvad der blev fravalgt.

## Fidelity
**High-fidelity (hifi).** Farver, typografi, spacing og layout er færdige og skal gen-skabes så tæt på pixel-perfekt som muligt med jeres egne komponenter. Eksakte hex-værdier, font-størrelser og mål står nedenfor.

---

## Screen: Overblik (hovedlisten)

### Purpose
Brugeren (en redaktør) lander her og scanner dagens indkomne debatartikler sorteret efter score (højest øverst). De kan stjernemarkere artikler, se hvilke der er læst, klikke en rubrik for at åbne artiklen, og filtrere/sortere.

### Overordnet layout
- **To-kolonne layout**, fuld højde, ingen topbar.
- **Venstre sidebar:** fast bredde **218px**, baggrund hvid, `border-right: 1px solid #EEE8DC`. Vertikal flex-kolonne med padding `22px 14px`.
- **Hovedindhold:** fylder resten (`flex: 1`), baggrund **#FBFAF6** (varm off-white). Vertikal flex-kolonne: header-blok øverst, scrollbart kort-feed nedenunder.
- Hele app-shellen i prototypen har `border-radius: 12px` og skygge — det er kun fordi den vises som mockup-kort på et lærred. **I en rigtig app fylder shellen hele viewporten uden radius/skygge.**

---

### Component: Sidebar

**Logo-blok** (padding `0 8px 20px`):
- Ikon: 22×22px firkant, `border-radius: 7px`, baggrund **#0E7C66** (teal, app-accent). Indeni et hvidt radar-/sigtekorn-ikon (cirkel + centrum-prik + 4 små streger ud, stroke #fff).
- Titel: "Debatstof-radar" — font **Newsreader** (serif), 17px, weight 600, color **#211D16**, `letter-spacing: -.01em`. Står ved siden af ikonet (gap 8px).
- Undertitel: "Internt JP-værktøj" — 11px, color **#A99F8C**, indrykket så den flugter med titlen (`padding-left: 30px`).

**Navigation** (flex-kolonne, `gap: 2px`). Hvert punkt: `display:flex; align-items:center; gap:10px; padding:9px 10px; border-radius:9px; font-size:13.5px`. Ikon 16×16px (line-icon, `stroke: currentColor`, stroke-width ~1.9) til venstre for label.
- **Overblik** — AKTIVT punkt: baggrund **#EEF3EF**, color **#0E7C66**, weight 600. Ikon: 2×2 grid.
- **Interessante** — inaktiv: color **#6B6354**, weight 500. Ikon: stjerne (outline).
- **Prioriterede** — inaktiv. Ikon: pil op.
- **Debatspor** — inaktiv, med dropdown-indikator: et lille chevron-ned-ikon (13×13, stroke **#C9BFAD**) yderst til højre (`justify-content: space-between`). Ikon: tag/label.
- **Medier** — inaktiv, samme dropdown-chevron. Ikon: avis.
- **Statistik** — inaktiv. Ikon: søjlediagram.

Inaktive punkter har ingen baggrund. (Tilføj gerne en hover-state: baggrund **#F7F4ED**.)

**Bruger-blok** (nederst, `margin-top: auto`): `padding:10px; border-radius:11px; background:#F7F4ED; display:flex; gap:9px`.
- Avatar: 28×28px cirkel, baggrund **#0E7C66**, hvide initialer "MK", 12px weight 600.
- Tekst: navn "M. Krarup" (12.5px, weight 600, **#211D16**) over rolle "Redaktionen" (10.5px, **#A99F8C**).

---

### Component: Header-blok (hovedindhold)

`display:flex; align-items:flex-end; justify-content:space-between; padding:22px 26px 12px`.

**Venstre:**
- Titel "Dagens debatstof" — font **Newsreader**, 24px, weight 600, color **#211D16**, `letter-spacing: -.01em`.
- Metalinje under: 12.5px, color **#A99F8C**. Tekst: "**347** artikler i feedet · opdateret 25. jun 2026, 09:14", hvor tallet 347 er **#6B6354** weight 600.

**Højre (knapper, flex gap 8px):** begge er pille-formede (`border-radius: 20px`, padding `7px 13px`, 12.5px).
- "Filtrér": baggrund hvid, `border: 1px solid #E6DFD2`, color **#6B6354**, med lille filter-ikon (3 vandrette streger der bliver kortere).
- "Score ↓": baggrund **#0E7C66**, color hvid, weight 600. (Aktiv sortering — viser at listen er sorteret faldende efter score.)

---

### Component: Artikel-kort (kort-feed)

Feed-container: `flex:1; padding:6px 26px 24px; display:flex; flex-direction:column; gap:9px` (scrollbar ved overflow).

Hvert kort: `display:flex; align-items:stretch; gap:16px; background:#fff; border:1px solid #EFEADF; border-radius:14px; padding:14px 16px; box-shadow:0 1px 2px rgba(40,34,22,.04)`.

Kortet har **tre kolonner** (flex-rækker):

**1) Score-blok** (venstre, fast 54px, `border-right: 1px solid #F1ECE1`, `padding-right:14px`, centreret kolonne):
- Score-tal: font **Newsreader**, 26px, weight 600. **Farve afhænger af score** (se Score-farveskala nedenfor).
- Under tallet: label "SCORE" — 8.5px, weight 600, `letter-spacing:.08em`, uppercase, color **#BCB3A2**.

**2) Indholds-blok** (midten, `flex:1; min-width:0`, centreret lodret):
- **Metalinje** (flex, gap 8px, `margin-bottom:4px`):
  - Medie-navn — 11px, weight 600, **#6B6354**.
  - Lille separator-prik — 3×3px cirkel, **#D6CDBC**.
  - Dato — 11px, **#A99F8C**.
  - **LÆST-badge** (kun hvis artiklen er åbnet): 9px, weight 600, `letter-spacing:.05em`, color **#B0A794**, baggrund **#F4F0E8**, `padding:1px 6px; border-radius:5px`. Teksten er "LÆST".
- **Rubrik:** font **Newsreader**, 17px, weight 500, color **#1C1810**, `line-height:1.28`, `letter-spacing:-.005em`. Klikbart link (åbner artikel-detalje).
- **Manchet:** 12px, color **#8C8474**, `line-height:1.5`, afkortet til **1 linje** (`-webkit-line-clamp:1`, ellipsis). `margin-top:4px`.

**3) Handlings-blok** (højre, fast bredde, `display:flex; flex-direction:column; align-items:flex-end; justify-content:space-between`):
- Øverst: **stjerne-ikon** 18×18px.
  - Markeret: fyldt, fill+stroke **#E0A52E** (gylden).
  - Ikke markeret: outline, `fill:none; stroke:#D6CDBC`.
  - Klik toggler markering.
- Nederst (`margin-top:auto`): **emne-chips** (flex, gap 5px). Hver chip: 10.5px, weight 500, color **#3B6B4A**, baggrund **#E9F1E8**, `padding:3px 9px; border-radius:20px; white-space:nowrap`. En artikel kan have 1–2 chips.

---

### Score-farveskala
Score-tallets farve sættes ud fra værdien:
- **≥ 80** (højt debatstof): **#D34A3C** (varm rød)
- **60–79** (mellem): **#D98A2B** (ravgul/orange)
- **< 60** (lavt): **#9AA1AB** (neutral grå)

---

## Interactions & Behavior
- **Klik på rubrik** → naviger til artikel-detalje (ikke designet endnu — åbn i nyt view eller højre-panel; afklares senere).
- **Klik på stjerne** → toggle markering; opdater ikon (gylden ↔ grå outline) og persistér på artiklen. Markering driver "Interessante"-listen i sidebaren.
- **Klik på medie/dato/manchet** → ingen handling (kun rubrik er link).
- **"Score ↓"-knap** → toggle sorteringsretning (faldende/stigende). Pilen vender. Default: faldende.
- **"Filtrér"-knap** → åbner filterpanel (debatspor, medier, datointerval). Ikke designet endnu.
- **Sidebar "Debatspor" / "Medier"** → chevron indikerer dropdown; udfolder underpunkter (de enkelte spor/medier).
- **LÆST-badge** → vises automatisk når artiklen har været åbnet mindst én gang.
- **Hover på artikel-kort** (anbefalet, ikke i prototypen): hæv skygge let, fx `box-shadow:0 2px 8px rgba(40,34,22,.07)` og/eller border til **#E3DCCD** — for at signalere klikbarhed.
- **Hover på inaktivt nav-punkt** (anbefalet): baggrund **#F7F4ED**.

## State Management
Nødvendig state pr. skærm:
- `articles: Article[]` — feed-data (se datamodel nedenfor).
- `sortDir: 'desc' | 'asc'` — sorteringsretning for score (default `'desc'`).
- `filters` — valgte debatspor, medier, datointerval (fremtid).
- Pr. artikel: `starred: boolean`, `read: boolean` (persistéres server-side).
- Feed-meta: total antal artikler (347) og sidste opdateringstidspunkt.

**Article-datamodel** (fra prototypen):
```ts
type Article = {
  id: string;
  score: number;        // 0–100
  media: string;        // "Politiken", "DR Nyheder", ...
  date: string;         // visnings-dato, fx "25. jun"
  title: string;        // rubrik
  dek: string;          // manchet
  topics: string[];     // 1–2 emner, fx ["Klima","Regeringen"]
  starred: boolean;
  read: boolean;
};
```

## Design Tokens

**Farver**
- App-accent (teal): `#0E7C66`
- Aktiv nav-baggrund: `#EEF3EF`
- Side-baggrund (indhold): `#FBFAF6`
- Sidebar/kort-baggrund: `#FFFFFF`
- Sidebar border: `#EEE8DC`
- Kort-border: `#EFEADF`
- Kort intern divider: `#F1ECE1`
- Bruger-/hover-blok baggrund: `#F7F4ED`
- Tekst primær (serif rubrik): `#1C1810`
- Tekst overskrift mørk: `#211D16`
- Tekst sekundær: `#6B6354`
- Tekst muted: `#8C8474`
- Tekst svag (meta/dato): `#A99F8C`
- Tekst meget svag (labels): `#BCB3A2`
- Separator-prik: `#D6CDBC`
- Chevron (dropdown): `#C9BFAD`
- Score rød (≥80): `#D34A3C`
- Score orange (60–79): `#D98A2B`
- Score grå (<60): `#9AA1AB`
- Stjerne markeret (gylden): `#E0A52E`
- Stjerne outline: `#D6CDBC`
- Emne-chip baggrund: `#E9F1E8`
- Emne-chip tekst: `#3B6B4A`
- LÆST-badge baggrund: `#F4F0E8`
- LÆST-badge tekst: `#B0A794`
- Filtrér-knap border: `#E6DFD2`

**Typografi**
- Serif (rubrikker, store overskrifter, score-tal): **Newsreader** (Google Fonts), weights 400/500/600.
- Sans (al øvrig UI): **Schibsted Grotesk** (Google Fonts), weights 400/500/600/700.
- Skala: app-titel 24px/600 serif · rubrik 17px/500 serif · score-tal 26px/600 serif · sidebar-titel 17px/600 serif · nav 13.5px · medie/dato/meta 11px · manchet 12px · chips 10.5px · labels 8.5–9px.

**Spacing & form**
- Sidebar bredde: 218px
- Kort-radius: 14px · nav-radius: 9px · pille-knap/chip-radius: 20px · ikon-firkant-radius: 7px
- Kort-padding: `14px 16px` · sidebar-padding: `22px 14px` · indholds-padding (header): `22px 26px 12px` · feed-padding: `6px 26px 24px`
- Kort-gap i feed: 9px
- Skygge kort: `0 1px 2px rgba(40,34,22,.04)`

## Assets
- **Ingen billedfiler.** Alle ikoner er inline SVG line-icons (stroke-baseret, ~1.9 stroke-width): 2×2 grid (Overblik), stjerne, pil-op, tag (Debatspor), avis (Medier), søjlediagram (Statistik), filter, chevron-ned, radar/sigtekorn (logo). Brug jeres eget ikon-bibliotek (fx Lucide/Feather — alle motiver findes der) frem for at kopiere SVG-stierne.
- **Fonts:** Newsreader + Schibsted Grotesk fra Google Fonts (eller self-host).
- Avatar "MK" er rene initialer på farvet cirkel — ingen billedfil.

## Screenshots
- `screenshots/overview-full.png` — hele Overblik-skærmen (retning B) i ét billede.
- `screenshots/detail-cards.png` — nærbillede af artikel-kortene (score, læst-badge, stjerne, emne-chips) i fuld opløsning.

## Files
- `Debatstof-radar.dc.html` — HTML-prototypen med **begge** retninger. **Retning B "Brief" er den højre frame** (`data-screen-label="Overblik B"`). Logikken (data + score-farve-funktion) ligger i `<script>`-blokken nederst i filen.
