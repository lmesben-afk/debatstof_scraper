"""Versioned, explainable editorial signals. These are heuristics, not fact checks."""
from functools import lru_cache
import re

SCORING_VERSION = 'editorial-2026-10-v3'
SCORE_LEVELS = {'high': 60, 'interesting': 40, 'watch': 20}
WEIGHTS = {'relevance': 30, 'combination': 35, 'evidence': 30,
           'concrete': 15, 'consequences': 10, 'conflict': 5, 'geography': 5, 'format': 5}

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
             'lovforslag*', 'reform*', 'foreslå*', 'planlæg*', 'lukker', 'kræver', 'pålæg*', 'tilladelse*', 'ekspropriation*', 'afviser']
INSTITUTIONS = ['kommune*', 'byråd*', 'folketing*', 'christiansborg', 'minister*', 'regering*',
                'ministerie*', 'justitsminister*', 'netselskab*', 'myndighed*', 'styrelse*', 'virksomhed*', 'arbejdsgiver*', 'svømmehal*', 'skole*']
AFFECTED = ['borger*', 'familie*', 'forældre*', 'virksomhed*', 'beboer*', 'lodsejer*',
            'patient*', 'boligejer*', 'iværksæt*', 'forbruger*', 'medarbejder*', 'landmand*', 'barn', 'børn', 'nabo*', 'arbejdsplads*']
CONSEQUENCES = ['arbejdsplads*', 'arbejdskraft*', 'arbejdsudbud*', 'omkostning*', 'mister',
                'million*', 'milliard*', 'fyre*', 'konkurs*', 'støj*', 'ekspropriation*',
                'ejendomsret', 'tilskud*', 'diskrimination*', 'adgang', 'lukker', 'forsink*']
DISAGREEMENT = ['kritiser*', 'modstand*', 'protest*', 'indsigelse*', 'afviser', 'uenighed',
                'strid', 'konflikt*', 'forbud*', 'tvang*']
GEOGRAPHY = ['jylland', 'fyn', 'bornholm', 'landdistrikt*', 'landsby*', 'provinsen', 'udkanten',
             'sydsjælland', 'vestsjælland', 'fynbo*', 'nordjylland', 'vestjylland', 'sønderjylland', 'midtjylland', 'lolland', 'falster',
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
    """Award partial evidence in short texts; each component has its own ceiling."""
    text = f'{item.title or ""} {item.deck or ""}'
    components = []
    topic_count = len({topic['mikroemne'] for topic in micro_topics})
    topic_relevance = min(WEIGHTS['relevance'], 8 + topic_count * 5) if topic_count else 0
    value_relevance = 25 if keyword_hits(text, SPECIFIC_VALUES) else 0
    relevance = max(topic_relevance, value_relevance)
    if relevance:
        components.append((relevance, 'Emne- og værdirelevans'))

    candidates = []
    for label, groups in PATTERNS.items():
        matched = [bool(keyword_hits(text, group)) for group in groups]
        if not matched[0]:
            continue
        if all(matched):
            points, strength = WEIGHTS['combination'], 'samlet sammenhæng'
        elif sum(matched) >= 2:
            points, strength = 20, 'flere hensyn omtalt'
        else:
            points, strength = max(0, 10 - relevance), 'relevant spor, begrænset kontekst'
        candidates.append((points, label + ' (' + strength + ')'))
    combination = max(candidates, key=lambda c:c[0], default=(0,''))
    if combination[0]:
        components.append(combination)

    decision = bool(keyword_hits(text, DECISIONS))
    institution = bool(keyword_hits(text, INSTITUTIONS))
    affected = bool(keyword_hits(text, AFFECTED))
    # A lone actor is not evidence of a decision. A proposal is not an enacted law.
    concrete = 15 if decision and institution and affected else (10 if decision and (institution or affected) else (3 if decision else 0))
    consequence_hits = keyword_hits(text, CONSEQUENCES)
    consequences = min(10, 1 + len(consequence_hits) * 3) if consequence_hits and (affected or decision or combination[0]) else 0
    conflict = 5 if keyword_hits(text, DISAGREEMENT) and (decision or affected or institution) else 0
    # Strong combinations already encode opposition, so no extra conflict bonus.
    if combination[0] == WEIGHTS['combination']:
        conflict = 0
    evidence = min(WEIGHTS['evidence'], concrete + consequences + conflict)
    if concrete:
        components.append((concrete, 'Signaler om beslutning, praksis eller forslag'))
    if consequences:
        components.append((consequences, 'Mulige konsekvenser omtalt'))
    if conflict:
        components.append((conflict, 'Modstridende interesser eller kritik omtalt'))
    geography = 5 if keyword_hits(text, GEOGRAPHY) and (relevance or combination[0] or decision) else 0
    if geography:
        components.append((geography, 'Geografisk relevans i indholdet'))
    format_points = 5 if (item.debate_type or '').casefold() in {'kronik','kommentar','læserbrev','debat','analyse','leder'} else 0
    if format_points:
        components.append((format_points, 'Debatformat'))
    score = relevance + combination[0] + evidence + geography + format_points
    return min(score,100), [f'{label}: +{points}' for points,label in components]
