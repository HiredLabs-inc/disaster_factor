# IMPORTS

from bs4 import BeautifulSoup
import requests
import re
import csv

from .helpers import serve_static_and_open


# DATA RETRIEVAL
def track_disasters():
  #TODO: Add disaster categories
  url = 'http://www.gdacs.org/XML/RSS.xml'
  resp = requests.get(url)
  soup = BeautifulSoup(resp.content, features="xml")
  items = soup.find_all('item')
  print(items)
  resources = []
  disasters = {}
  counter = 0
  total_red = 0

  for i in items:
    resources.append(i.resources.find_all('resource'))

    # Grabbing only the most severe disasters
    # if i.find('alertlevel').text == 'Red':
    #   resources.append(i.resources.find_all('resource'))
    #   total_red += 1

  impact_xmls = []
  impact_data = []

  for r in resources:
    for i in r:
      if i['id'] == 'impact_xml':
        impact_xmls.append(i['url'])
      elif i['id'] == 'impact_data':
        impact_data.append(i['url'])

  xml_calculations = []
  xml_contentdata = []

  for xml in impact_xmls:
    calc_match = re.search('calculation', xml)
    # data_match = re.search('contentdata', xml)
    if calc_match:
      xml_calculations.append(xml)

    # if data_match:
    #   xml_contentdata.append(xml)

  for site in xml_calculations:
    resp_3 = requests.get(site)
    soup_3 = BeautifulSoup(resp_3.content, features="xml")
    datums = soup_3.find_all('datums')
    for d in datums:
      if d['alias'] == 'City':
        data = d.find_all('datum')
        for i in data:
          # ensure we always have a fresh disaster dict for each datum
          disaster = {}
          scalars = i.find_all('scalar')
          for scalar in scalars:
            name = scalar.find('name')
            if name.text == 'NAME':
              counter += 1
              disaster['city'] = scalar.value.text

            if name.text == 'COUNTRY':
              disaster['country'] = scalar.value.text
              disaster['type'] = soup_3.find('model-name').text
              disasters[counter] = disaster

  for link in impact_data:
    resp_4 = requests.get(link)
    soup_4 = BeautifulSoup(resp_4.content, 'lxml')
    pre = soup_4.pre.find_all('a')
    for a in pre:
      if a.text == 'final':
        url = 'http://webcritech.jrc.ec.europa.eu' + a['href'] + 'locations.xml'
        resp_5 = requests.get(url)
        soup_5 = BeautifulSoup(resp_5.content, features="xml")
        items = soup_5.find_all('item')
        for item in items:
          if item.cityName != None:
            disaster = {}
            counter += 1
            disaster['city'] = item.cityName.text
            disaster['country'] = item.country.text
            disaster['type'] = soup_5.title.text.lower()
            disasters[counter] = disaster
  print(disasters)


  # DATA INPUT
  # TODO: Create db based on xml

  # cities_list = csv.reader(open('cities.csv', 'r'))
  cities_list = {}
  cities = {}
  for k, v in cities_list:
     cities[k] = v

  #countries_list = csv.reader(open('countries.csv', 'r'))
  countries_list = {}
  countries = {}
  for k, v in countries_list:
    countries[k] = v


  # DATA PROCESSING

  city_match_all = []
  country_match_all = []

  for city in disasters:
    for k in cities:
      if disasters[city]['city'] == cities[k]:
        city_match_all.append(k)

  for country in disasters:
    for k in countries:
      if disasters[country]['country'] == countries[k]:
        country_match_all.append(k)

  both_match = set(country_match_all).intersection(city_match_all)

  affected = {}
  affected_counter = 0

  # print(f'Tere are {len(disasters)} cities recently affected by natural disasters worldwide.')
  # print()

  # print(f'According to our platform data, the contractors below are in one of the affected cities:')
  # print()

  outreach_list = []


  # OUTPUT

  for disaster in disasters:
    for person in affected:
      if disasters[disaster]['city'] == affected[person]['city'] and disasters[disaster]['country'] == affected[person]['country']:
        freelancer = []
        freelancer.append(affected[person]["unique_id"])
        freelancer.append(disasters[disaster]["type"])
        outreach_list.append(freelancer)
        print(f'Freelancer unique id: {affected[person]["unique_id"]}')
        print(f'Location: {disasters[disaster]["city"]}, {disasters[disaster]["country"]}')
        if disasters[disaster]['type'] == 'EQ':
          print(f'Disaster type: earthquake')
        else:
          print(f'Disaster type: {disasters[disaster]["type"]}')
        print()

  print("TOTAL NUMBER OF RED-LEVEL ALERTS:")
  print(total_red)
  srv = serve_static_and_open()

  # Keep process alive briefly so linked assets (CSS/JS/SVG) can be fetched before daemon thread dies
  import time as _time
  _time.sleep(3)

  with open('affected.csv', 'w') as csvFile:
    writer = csv.writer(csvFile)
    writer.writerows(outreach_list)