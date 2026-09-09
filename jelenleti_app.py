"""Sofőrök havi jelenléti összesítője.

Függőség: streamlit (pip install streamlit)
Indítás: python -m streamlit run jelenleti_app.py
A CSV az alkalmazásban tölthető fel; nincs beégetett személyes adat.
"""
import csv
import hashlib
import io
import unicodedata
from collections import defaultdict
from datetime import datetime

KNOWN = {'Mun', 'Szab', 'Táp', 'HPih', 'Ünn'}
ACTIVE = {'Mun', 'Szab', 'Táp'}
MONTHS = ['január', 'február', 'március', 'április', 'május', 'június',
          'július', 'augusztus', 'szeptember', 'október', 'november', 'december']


def read_csv(data):
    """A fejléc előtti jelentéssorokat átugorja, a hibás adatsorokat jelzi."""
    for encoding in ('utf-8-sig', 'cp1250'):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError('A fájl kódolása nem támogatott. UTF-8 CSV szükséges.')
    # A jelentés első sorai miatt a teljes fájlra futtatott Sniffer nem megbízható.
    for delimiter in (',', ';', '\t'):
        rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
        header = next((i for i, r in enumerate(rows)
                       if len(r) >= 4 and r[0].strip() == 'Név'
                       and r[2].strip() == 'Nap' and r[3].strip() == 'Jogcím'), None)
        if header is not None:
            break
    else:
        raise ValueError('Nem található a Név / azonosító / Nap / Jogcím fejléc.')
    records, errors = [], []
    for line, row in enumerate(rows[header + 1:], header + 2):
        if not any(cell.strip() for cell in row):
            continue
        try:
            if len(row) < 4:
                raise ValueError('Hiányzó oszlop')
            name, identifier, date_text, code = [v.strip() for v in row[:4]]
            day = datetime.strptime(date_text, '%Y-%m-%d').date()
            if not name:
                raise ValueError('Hiányzó sofőrnév')
            # Az azonosító elsőbbséget élvez, az üres azonosítóknál a pontos név a kulcs.
            driver = ('id', identifier) if identifier else ('name', name)
            records.append(dict(driver=driver, name=name, day=day, code=code, line=line))
        except ValueError as exc:
            errors.append(f'{line}. sor: {exc}')
    if not records:
        raise ValueError('Nincs feldolgozható dátummal és névvel rendelkező adatsor.')
    return records, errors


def group_days(records, mapping=None):
    """Egyedi sofőr–dátum kulcs: a több munkaszakasz nem növeli a napok számát."""
    mapping = mapping or {}
    groups = defaultdict(set)
    for r in records:
        groups[(mapping.get(r['driver'], r['driver']), r['day'])].add(r['code'])
    return groups


def summarize(groups, selected):
    result = {driver: {code: 0 for code in KNOWN} for driver in selected}
    for (driver, day), codes in groups.items():
        if driver in result:
            for code in codes & KNOWN:
                result[driver][code] += 1
    return result


def ratio(numerator, denominator):
    return numerator / denominator if numerator is not None and denominator else None


def number(value, decimals=0):
    return '—' if value is None else f'{value:,.{decimals}f}'.replace(',', ' ').replace('.', ',')


def main():
    import streamlit as st
    st.set_page_config(page_title='Sofőrök havi összesítője', page_icon='🚛', layout='wide')
    st.title('Sofőrök havi összesítője')
    st.caption('Jelenléti napok · átlagos munkanapszám · kilométer / sofőrnap')
    upload = st.file_uploader('Jelenléti ív feltöltése (CSV)', type=['csv'])
    if upload is None:
        st.info('Töltsd fel a jelenléti rendszerből exportált CSV-fájlt.')
        return
    data = upload.getvalue()
    try:
        records, errors = read_csv(data)
    except (ValueError, csv.Error) as exc:
        st.error(str(exc))
        return
    months = sorted({r['day'].strftime('%Y-%m') for r in records})
    month = st.selectbox('Elszámolási hónap', months, index=len(months)-1,
                        format_func=lambda m: f'{m[:4]}. {MONTHS[int(m[5:])-1]}')
    scope = hashlib.sha256(data).hexdigest()[:16] + month
    records = [r for r in records if r['day'].strftime('%Y-%m') == month]
    labels = {}
    for r in records:
        suffix = f" [{r['driver'][1]}]" if r['driver'][0] == 'id' else ''
        labels[r['driver']] = r['name'] + suffix
    mapping = {}
    similar = defaultdict(set)
    for driver, label in labels.items():
        key = unicodedata.normalize('NFKC', label).casefold()
        similar[' '.join(key.split())].add(driver)
    with st.expander('Névegyezések ellenőrzése'):
        candidates = [sorted(v) for v in similar.values() if len(v) > 1]
        if not candidates:
            st.write('Nincs kizárólag kis-/nagybetűben vagy szóközökben eltérő név.')
        for i, drivers in enumerate(candidates):
            title = ' / '.join(labels[d] for d in drivers)
            if st.checkbox(f'Ugyanaz a személy: {title}', key=f'{scope}_merge_{i}'):
                mapping.update({d: drivers[0] for d in drivers})
        st.caption('Csak jóváhagyott neveket von össze. Más elírásokat nem ismer fel automatikusan.')
    groups = group_days(records, mapping)
    drivers = sorted({d for d, day in groups}, key=lambda d: labels[d].casefold())
    defaults = [d for d in drivers if any(k == d and codes & ACTIVE
                                         for (k, day), codes in groups.items())]
    selection_scope = scope + hashlib.sha256(repr(mapping).encode()).hexdigest()[:8]
    with st.expander('Számításba bevont sofőrök', expanded=True):
        selected = st.multiselect('Sofőrök — a lista szabadon módosítható', drivers,
                                  default=defaults, format_func=lambda d: labels[d],
                                  key=f'{selection_scope}_drivers')
        st.caption('Alapból bekerül, akinek van Mun, Szab vagy Táp napja. '
                   'A többiek kimaradnak; ez nem a munkaviszony ellenőrzése.')
        excluded = [labels[d] for d in drivers if d not in selected]
        st.write(f'Bevont: {len(selected)} fő · Kizárt: {len(excluded)} fő')
        if excluded:
            st.text('Kizárt sofőrök: ' + ', '.join(excluded))
    totals = summarize(groups, selected)
    work = sum(v['Mun'] for v in totals.values())
    leave = sum(v['Szab'] for v in totals.values())
    sick = sum(v['Táp'] for v in totals.values())
    working = sum(v['Mun'] > 0 for v in totals.values())
    conflicts = [(d, day, codes) for (d, day), codes in groups.items() if len(codes) > 1]
    unknown = sorted({r['code'] or '(üres)' for r in records if r['code'] not in KNOWN})
    if errors or conflicts or unknown:
        st.warning('Ellenőrizendő adatok vannak. Az eredményeket ezek figyelembevételével használd.')
    with st.expander('Adatellenőrzés és számítási szabályok'):
        st.write(f'{len(conflicts)} sofőr–dátum párhoz több jogcím tartozik.')
        for d, day, codes in conflicts:
            st.text(f"{labels[d]} · {day} · {', '.join(sorted(codes))}")
        if unknown:
            st.write('Nem összesített jogcímek: ' + ', '.join(unknown))
        if errors:
            st.write('Kihagyott hibás sorok (a teljes feltöltött fájlból):')
            st.text('\n'.join(errors))
        st.write('Egy dátum jogcímenként egyszer számít. Ha ugyanazon a napon Mun és Szab '
                 'is szerepel, mindkét kategóriában egy nap jelenik meg. '
                 'Ezért a kategóriák összege nem feltétlenül egyezik az egyedi napok számával.')
        st.write('Az éjszakai munkaszakasz a CSV Nap oszlopának dátumához tartozik. '
                 'A hónap közben belépő vagy kilépő sofőr egy főnek számít; nincs időarányosítás.')
    km = st.number_input('Havi összes megtett kilométer', min_value=0.0, value=None,
                         step=1000.0, format='%.2f', placeholder='Nem kötelező',
                         key=f'{selection_scope}_km')
    st.caption('A kilométer ugyanarra a hónapra és a kiválasztott sofőrökre vonatkozzon. '
               'Sofőrlista módosításakor ellenőrizd a megadott kilométert is.')
    a, b, c = st.columns(3)
    a.metric('Ledolgozott sofőrnap', number(work))
    b.metric('Szabadság', number(leave) + ' nap')
    c.metric('Táppénz', number(sick) + ' nap')
    a, b, c = st.columns(3)
    a.metric('Átlag · minden bevont sofőr', number(ratio(work, len(selected)), 2) + ' nap/fő')
    b.metric('Átlag · ténylegesen dolgozók', number(ratio(work, working), 2) + ' nap/fő')
    c.metric('Átlagos napi futás', number(ratio(km, work), 2) + ' km/sofőrnap')
    st.caption(f'Bevont sofőr: {len(selected)} fő · Ténylegesen dolgozott: {working} fő. '
               'Napi futás = havi kilométer / ledolgozott sofőrnap.')
    if not selected:
        st.info('Az átlagokhoz válassz legalább egy sofőrt.')
    elif not work:
        st.info('Nincs ledolgozott nap; kilométerátlag nem számítható.')
    with st.expander('Sofőrönkénti összesítés'):
        for d, values in totals.items():
            st.text(f"{labels[d]}: {values['Mun']} munkanap · {values['Szab']} szabadság · "
                    f"{values['Táp']} táppénz")
    st.caption('A kiválasztások és a kilométermező az aktuális böngésző-munkamenetre szólnak.')


if __name__ == '__main__':
    main()
