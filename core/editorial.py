"""Versioned, explainable editorial signals. These are heuristics, not fact checks."""
from functools import lru_cache
import re

SCORING_VERSION = 'editorial-2026-10-v2'
SCORE_LEVELS = {'high': 60, 'interesting': 40, 'watch': 20}
WEIGHTS = {'relevance': 20, 'combination': 25, 'concrete': 15, 'consequences': 10,
           'conflict': 10, 'geography': 5, 'format': 5}

PATTERNS = {
    'Familievalg over for arbejdsmarked og fællesskab': [
        ['hjemmepas*', 'passe egne børn', 'hjemmegående', 'passe børn hjemme'],
        ['arbejdsmarked*', 'arbejdsudbud*', 'arbejdskraft*', 'ligestilling', 'tilskud*', 'økonomi*', 'institution*', 'dagtilbud*']],
    'Ligestilling, religion og adgang til fælles faciliteter': [
        ['kønsopdelt*', 'kønsadskilt*', 'kun for kvinder', 'kun for mænd'],
        ['svøm*', 'svømmehal*', 'idræt*', 'offentlig*', 'kommune*'],
        ['ligestilling', 'religion*', 'muslim*', 'integration*', 'adgang', 'lige adgang', 'diskrimination*']],
    'Klima- og energiprojekter over for lokale hensyn': [
        ['vindmølle*', 'solcelle*', 'energipark*', 'energiø*', 'klimaprojekt*', 'grøn omstilling', 'skovrejsning'],
        ['lokal*', 'nabo*', 'borger*', 'lodsejer*', 'landsby*', 'kommune*', 'ejendomsret'],
        ['modstand*', 'protest*', 'indsigelse*', 'tvang*', 'ekspropriation*', 'støj*', 'besluttet', 'vedtaget', 'christiansborg']],
    'Erhvervslivets konkrete vilkår og konsekvenser': [
        ['virksomhed*', 'erhverv*', 'iværksæt*', 'landmand*', 'landbrug*'],
        ['arbejdsplads*', 'investering*', 'eksport*', 'omkostning*', 'lukke*', 'fyre*', 'konkurs*', 'million*'],
        ['afgift*', 'regulering*', 'regel*', 'krav', 'forbud*', 'tilladelse*', 'mangel', 'forsink*', 'besluttet']],
}
DECISIONS = ['indfør*', 'vedtaget', 'besluttet', 'forbyd*', 'forbud*', 'afskaff*', 'nedlæg*',
             'lukker', 'kræver', 'pålæg*', 'tilladelse*', 'ekspropriation*', 'afviser']
INSTITUTIONS = ['kommune*', 'byråd*', 'folketing*', 'christiansborg', 'minister*', 'regering*',
                'myndighed*', 'styrelse*', 'virksomhed*', 'arbejdsgiver*', 'svømmehal*', 'skole*']
AFFECTED = ['borger*', 'familie*', 'forældre*', 'virksomhed*', 'beboer*', 'lodsejer*',
            'medarbejder*', 'landmand*', 'barn', 'børn', 'nabo*', 'arbejdsplads*']
CONSEQUENCES = ['arbejdsplads*', 'arbejdskraft*', 'arbejdsudbud*', 'omkostning*', 'mister',
                'million*', 'milliard*', 'fyre*', 'konkurs*', 'støj*', 'ekspropriation*',
                'ejendomsret', 'tilskud*', 'diskrimination*', 'adgang', 'lukker', 'forsink*']
DISAGREEMENT = ['kritiser*', 'modstand*', 'protest*', 'indsigelse*', 'afviser', 'uenighed',
                'strid', 'konflikt*', 'forbud*', 'tvang*']
GEOGRAPHY = ['jylland', 'fyn', 'bornholm', 'landdistrikt*', 'landsby*', 'provinsen', 'udkanten',
             'nordjylland', 'vestjylland', 'sønderjylland', 'midtjylland', 'lolland', 'falster',
             'aarhus', 'århus', 'aalborg', 'odense', 'esbjerg', 'kolding', 'viborg', 'holstebro',
             'herning', 'aabenraa', 'sønderborg', 'ringkøbing', 'silkeborg', 'nakskov', 'hjørring']
SPECIFIC_VALUES = ['frit valg', 'valgfrihed', 'selvbestemmelse', 'personligt ansvar', 'ejendomsret',
                   'ytringsfrihed', 'ligestilling', 'religionsfrihed', 'retssikkerhed', 'hjemmepas*',
                   'iværksæt*', 'konkurrenceevne', 'centralisering', 'kønsopdelt*']
TOPIC_KEYWORDS = {
    'familieliv_og_arbejde': ['hjemmepasning', 'hjemmepasse', 'hjemmegående', 'passe egne børn',
                             'familiens frie valg', 'arbejdsudbud', 'pasningstilskud'],
    'ligestilling_religion_og_faellesrum': ['kønsopdelt svømning', 'kønsopdelte svømmetider',
        'kønsadskilt', 'religionsfrihed', 'ligestilling', 'fælles faciliteter', 'lige adgang'],
    'klima_og_lokal_indflydelse': ['energipark', 'vindmøller', 'solcellepark', 'lokal modstand',
                                  'borgerinddragelse', 'ekspropriation', 'ejendomsret'],
}
STRONG_TOPICS = ['hjemmepasning', 'hjemmepasse', 'hjemmegående', 'kønsopdelt svømning',
                 'kønsopdelte svømmetider', 'religionsfrihed', 'lokal modstand', 'ekspropriation',
                 'arveafgift', 'ulvedebat', 'asbestforbud', 'drikkevand', 'retssikkerhed']


@lru_cache(maxsize=4096)
def keyword_pattern(keyword):
    parts = keyword.casefold().split('*')
    pattern = r'\w*'.join(re.escape(part) for part in parts)
    if '*' not in keyword and len(keyword) >= 5:
        pattern += r'(?:en|et|er|ne|erne|ene|s|ens|ets)?'
    return re.compile(r'(?<!\w)' + pattern + r'(?!\w)')


def keyword_hits(text, keywords):
    text = ' '.join(text.casefold().split())
    return sorted({keyword for keyword in keywords
                   if keyword.casefold().split('*', 1)[0] in text
                   and keyword_pattern(keyword).search(text)})


def editorial_score(item, micro_topics):
    text = f'{item.title or ""} {item.deck or ""}'
    combinations = [label for label, groups in PATTERNS.items()
                    if all(keyword_hits(text, group) for group in groups)]
    concrete = all(keyword_hits(text, group) for group in (DECISIONS, INSTITUTIONS, AFFECTED))
    consequences = bool(keyword_hits(text, CONSEQUENCES)) and (concrete or bool(combinations))
    reasons = []
    score = 0
    # A word and the topic it identifies share one relevance budget.
    relevance = max(15 if keyword_hits(text, SPECIFIC_VALUES) else 0,
                    min(len(micro_topics) * 5, WEIGHTS['relevance']))
    if relevance:
        score += relevance
        reasons.append(f'Emne- og værdirelevans: +{relevance}')
    # Overlapping combinations share one bonus, regardless of viewpoint.
    if combinations:
        score += WEIGHTS['combination']
        reasons.append('Værdier/interesser i sammenhæng: ' + '; '.join(combinations) + ' (+25)')
    if concrete:
        score += WEIGHTS['concrete']
        reasons.append('Signaler om beslutning/praksis med berørte aktører: +15')
    if consequences:
        score += WEIGHTS['consequences']
        reasons.append('Mulige konkrete konsekvenser omtalt: +10')
    if concrete and not combinations and keyword_hits(text, DISAGREEMENT):
        score += WEIGHTS['conflict']
        reasons.append('Konflikt om en konkret beslutning: +10')
    if keyword_hits(text, GEOGRAPHY) and (concrete or combinations):
        score += WEIGHTS['geography']
        reasons.append('Geografisk relevans i indholdet: +5')
    if (item.debate_type or '').casefold() in {'kronik','kommentar','læserbrev','debat','analyse','leder'}:
        score += WEIGHTS['format']
        reasons.append('Debatformat: +5')
    return min(score,100), reasons
