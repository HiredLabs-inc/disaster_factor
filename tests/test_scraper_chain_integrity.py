
from pathlib import Path
from xml.etree import ElementTree as ET

DATA = Path(__file__).parent / "data"

def _all_attr_urls(root):
    urls = []
    for el in root.iter():
        for k,v in el.attrib.items():
            if k.lower() in ("href","src","url","link"):
                urls.append(v)
    return urls

def _parse(path):
    return ET.parse(path).getroot()

def test_chain_integrity():
    # 1) Top-level RSS must reference the event RSS
    rss = _parse(DATA / "gdacs_rss_sample.xml")
    rss_urls = _all_attr_urls(rss)
    event_rss_url = "https://www.gdacs.org//datareport/resources/EQ/1508599/rss_1508599.xml"
    assert any(event_rss_url in u for u in rss_urls), "Top-level RSS should contain the event RSS URL"

    # 2) Event RSS must reference the calculation (impact) XML
    ev = _parse(DATA / "downstream1.xml")
    ev_urls = _all_attr_urls(ev)
    calc_url = r"https://www.gdacs.org/gis/calculation/EQ1_WPS/-071\eq_-07150_-02745.xml"
    assert any(calc_url in u for u in ev_urls), "Event RSS should contain the impact calculation XML URL"

    # 3) Impact XML must contain City datums with NAME and COUNTRY
    impact = _parse(DATA / "downstream2.xml")
    datums = [d for d in impact.iter() if d.tag.endswith('datums') and d.attrib.get('alias') == 'City']
    assert datums, "Impact XML should contain <datums alias='City'>"
    has_name = False
    has_country = False
    for datum in datums:
        for scalar in datum.iter():
            if scalar.tag.endswith('name') and (scalar.text or '').strip() == 'NAME':
                has_name = True
            if scalar.tag.endswith('name') and (scalar.text or '').strip() == 'COUNTRY':
                has_country = True
    assert has_name, "Expected a scalar NAME in City datums"
    assert has_country, "Expected a scalar COUNTRY in City datums"
