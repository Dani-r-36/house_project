import os
import time
import requests
import pandas as pd
import re
from rapidfuzz import fuzz, process, utils
import itertools
import string
from geopy.geocoders import Nominatim
from datetime import datetime
import ast
from dotenv import load_dotenv

load_dotenv()

POSTCODE = r"^([A-Z]{1,2}\d[A-Z\d]? ?\d[A-Z]{2}|GIR ?0A{2})$"
OUTWARD_CODE = r"^[A-Z]{1,2}\d[A-Z\d]?$"

EFC_API_KEY = os.getenv('ENERGY_PERFORMANCE_KEY')
EFC_BASE_URL = "https://api.get-energy-performance-data.communities.gov.uk/api/domestic/search?"

""""house location validation and search functions"""
def filter_house_df(location_dict):
    Borough, Town_City, County, Postcode = location_dict.get("Borough"), location_dict.get("Town/City"), location_dict.get("County"), location_dict.get("Postcode")
    print(f"Filtering DataFrame for Borough: {Borough}, Town/City: {Town_City}, County: {County}, Postcode: {Postcode}")
    houses_df = pd.read_csv("/Users/danishanrahulan/Downloads/house_prices_formated.csv")
    original_df = houses_df.copy()
    houses_df = houses_df.dropna(subset=["Borough", "Town/City", "County", "Postcode"])
    houses_df = houses_df[houses_df["Price"] > 0]
    houses_df = houses_df.drop_duplicates(subset=["Borough", "Town/City", "County", "Postcode"])
    mask = pd.Series(True, index=houses_df.index)
    mask &= houses_df["Borough"].str.upper() == Borough.upper() if Borough is not None else mask
    mask &= houses_df["Town/City"].str.upper() == Town_City.upper() if Town_City is not None else mask  
    mask &= houses_df["County"].str.upper() == County.upper() if County is not None else mask
    mask &= (
            houses_df["Postcode"].str.replace(" ", "", regex=False).str.upper()
            == Postcode.replace(" ", "").upper()
        ) if Postcode is not None else mask
    return (houses_df[mask], original_df) if Borough or Town_City or County or Postcode else (None, None)

def load_houses_data(file_path):
    houses_df = pd.read_csv(file_path)
    return houses_df

def df_prerequists(houses_df):
    trans_table = str.maketrans('', '', string.punctuation)
    house_df_borough_list = houses_df["Borough"].unique()
    house_df_borough_list = [
        item.translate(trans_table) if isinstance(item, str) else item 
        for item in house_df_borough_list
    ]
    house_df_town_list = houses_df["Town/City"].unique()
    house_df_town_list = [
        item.translate(trans_table) if isinstance(item, str) else item 
        for item in house_df_town_list
    ]
    house_df_county_list = houses_df["County"].unique()
    house_df_county_list = [
        item.translate(trans_table) if isinstance(item, str) else item 
        for item in house_df_county_list
    ]
    house_df_outward_code_list = houses_df["outward_code"].unique()
    house_df_postcode_list = houses_df["Postcode"].str.replace(' ', '').str.strip().unique()
    return house_df_borough_list, house_df_town_list, house_df_county_list, house_df_outward_code_list, house_df_postcode_list

def serach(place_query, house_df_borough_list, house_df_town_list, house_df_county_list, house_df_outward_code_list, house_df_postcode_list):
    matched_place = []
    print(f"place_query is {set(place_query)}")
    for place in set(place_query):
        place = re.sub(r'[^\w\s]', '', place).strip().upper()
        if not place: continue
        if re.match(OUTWARD_CODE, place):
            print(f"{place} hit regex")
            outward_hit = place if place in house_df_outward_code_list else None
            if outward_hit:
                matched_place.append({place: [("outward_code", place, 1, None)]})
            else:
                matched_place.append({place: []})
            continue
        elif re.match(POSTCODE, place):
            place = place.replace(' ', '').strip()
            postcode_hit = place if place in house_df_postcode_list else None
            if postcode_hit:
                matched_place.append({place: [("Postcode", place, 1, None)]})
            else:
                matched_place.append({place: []})
            continue
        matched_place += matches(place, house_df_borough_list, house_df_town_list, house_df_county_list) 
    return matched_place

def matches(place, house_df_borough_list, house_df_town_list, house_df_county_list):
    matched_places = []
    places = []
    location_lists = {
    "Town/City": house_df_town_list,
    "Borough": house_df_borough_list,
    "County": house_df_county_list,
    }
    for col, l in location_lists.items():
        total_matches = 0
        single_column_match = col if place in l else None
        if single_column_match:
            places.extend([(single_column_match, place, 1, None)])
        else:
            pattern = fr'\b{re.escape(place)}\b'
            column_match = [(col,item) for item in l if isinstance(item, str) and re.search(pattern,item)]
            if len(column_match)>0:
                total_matches = len(column_match)
                if len(column_match) > 5:
                    column_match = column_match[:5]
                places.extend([(loc, plac, 2, None) for loc, plac in column_match])
            else:
                if len(place) > 2:
                    column_match = [(col,item) for item in l if isinstance(item, str) and place in item]
                    if len(column_match)>0:
                        total_matches = len(column_match)
                        if len(column_match) > 5:
                            column_match = column_match[:5]
                        places.extend([(loc, plac, 3, None) for loc, plac in column_match])
    if len(places) < 2 and len(place) > 2:
        places=fuzzy_search(place, location_lists, places)
    if places:
        found_details = {place: places} if total_matches == 0 else {place: places, "total_matches": total_matches, "truncated": True}
        matched_places.append(found_details)
    else:
        matched_places.append({place: []})
    return matched_places

def fuzzy_search(place, location_lists, places):
    for col, l in location_lists.items():
        fuzz_list = process.extract(place, location_lists[col], scorer=fuzz.WRatio, score_cutoff=85, limit=3, processor=utils.default_process)
        if len(fuzz_list) > 0:
            fuzz_list = fuzzy_top(fuzz_list)
            places.extend([(col, plac[0], 4, plac[1]) for plac in fuzz_list])
    return places

def fuzzy_top(fuzz_list):
    top_item = None
    for a, b in itertools.combinations(fuzz_list, 2):
        difference = abs(a[1] - b[1])
        if difference > 5:
            top_item = a if a[1] > b[1] else b
    return [top_item] if top_item else fuzz_list

def get_locations(query):
    if query:
        place_query = [x.strip() for x in query.split(",") if x.strip()]
        houses_df = load_houses_data("/Users/danishanrahulan/Downloads/house_prices_formated.csv")
        house_df_borough_list, house_df_town_list, house_df_county_list, house_df_outward_code_list, house_df_postcode_list = df_prerequists(houses_df)
        check = serach(place_query, house_df_borough_list, house_df_town_list, house_df_county_list, house_df_outward_code_list, house_df_postcode_list)
        return check
    return []

# query = "Colliers Wood, London"
# place_query = [x.strip() for x in query.split(",") if x.strip()]
# houses_df = load_houses_data("/Users/danishanrahulan/Downloads/house_prices_formated.csv")
# house_df_borough_list, house_df_town_list, house_df_county_list, house_df_outward_code_list, house_df_postcode_list = df_prerequists(houses_df)
# check = serach(place_query, house_df_borough_list, house_df_town_list, house_df_county_list, house_df_outward_code_list, house_df_postcode_list)
# print(check)

"""Price distribution in areas"""
def price_distribution(location):
    df = pd.read_csv("/Users/danishanrahulan/Downloads/house_prices_formated.csv")
    searched_df =df.loc[df["Borough"]== location]
    area_summary = searched_df.groupby('outward_code')['Price'].agg(
        total_sales='count',
        median_price='median',
        mean_price='mean',
        min_price='min',
        max_price='max'
    ).reset_index()
    area_summary = area_summary.sort_values(by='median_price', ascending=False)
    return area_summary


"""long lat search"""
# geolocator = Nominatim(user_agent="houses")
# location = geolocator.geocode("Merton, London")
# print(location)
# print(location.address)
# print((location.latitude, location.longitude))

"""EFC (energy performance) API search"""
def efc_api_call(search_url, params):
    time.sleep(0.2)
    headers = {
        "Authorization": f"Bearer {EFC_API_KEY}",
        # "Authorization": f"Basic {encoded_token}",
        "Accept": "application/json"
    }
    
    try:
        response = requests.get(search_url, headers=headers, params=params)
        print(response.request.url)
        response.raise_for_status() 
        data = response.json()
        return data
    except requests.exceptions.HTTPError as err:
            print(f"HTTP Error: {err}")
            if response.status_code == 401:
                print("Hint: Check that your email and API key are correct and activated.")
    except Exception as e:
        print(f"An error occurred: {e}")

def get_property_room_count(url: str, params: str):
    """
    Queries the UK EPC database and returns the number of habitable rooms.
    """
    data = efc_api_call(url, params)
    # Check if the API returned any matching rows
    data = data.get("data") if data else None

    if not data:
        print("No property found matching that address.")
        return None
    property_data_code = data[0].get("certificateNumber")
    return efc_api_call("https://api.get-energy-performance-data.communities.gov.uk/api/certificate?", f"certificate_number={property_data_code}") if property_data_code else None
    

    # Replace with a real residential postcode and street
# data = get_property_room_count(url=EFC_BASE_URL, params="postcode=CR7+8PX&address=182+MOFFAT+ROAD")
# import data to use
# print(data['data']["habitable_room_count"])
# print(data['data']['total_floor_area'])
# print(data['data']['heating_cost_current'])
# print(data['data']['potential_energy_efficiency_band'])


"""Police data for crime rates 2024 and before"""

def get_borough_bounding_poly(location_name, coords = False):
    params = {
        "q": location_name,
        "format": "json",
    }
    url = f"https://nominatim.openstreetmap.org/search"
    headers = {"User-Agent": "CrimeDataApp/1.0"}
    res = requests.get(url, headers=headers, params=params).json()

    if not res:
        return None
    s, n, w, e = [float(x) for x in res[0]["boundingbox"]]
    if not coords:
        return (s, w, n, e)
    return (s, w, n, e), (float(res[0]["lon"]), float(res[0]["lat"]))

def get_crimes_in_polygon(poly, date="2025-01"):
    url = f"https://data.police.uk/api/crimes-street/all-crime?poly={poly}&date={date}"
    time.sleep(0.2)
    res = requests.get(url)
    return res.json()

def get_postcode_losas(crimes):
    print(crimes)
    geolocations = [
        {
            "longitude": float(crime['location']['longitude']),
            "latitude": float(crime['location']['latitude']),
            "limit": 1
        }
        for crime in crimes 
        if crime.get('location') and crime['location'].get('longitude') and crime['location'].get('latitude')
    ]
    chunk_size = 100
    chunks = [geolocations[i:i + chunk_size] for i in range(0, len(geolocations), chunk_size)]
    all_lsoas = []
    for chunk in chunks:
        payload = {"geolocations": chunk}
        res = requests.post("https://api.postcodes.io/postcodes", json=payload).json()
        
        for result in res.get('result', []):
            if result['result']:
                all_lsoas.append(result['result'][0]['lsoa'])
    return all_lsoas

def crime_calcualtion(total_crimes_year, pop_df,lsoa_column, all_lsoas):
    unique_locations = {str(x).lower() for x in all_lsoas}
    unique_locations = {x.lower() for x in unique_locations}
    filtered_po = pop_df.loc[pop_df[lsoa_column].str.lower().isin(unique_locations)]
    total_populations_2024 = pd.to_numeric(filtered_po["Total"].str.replace(",", "", regex=False)).sum()
    return (total_crimes_year/total_populations_2024) *1000

def population_data(year):
    if year == 2024:
        return pd.read_csv("/Users/danishanrahulan/Downloads/ons_population_19_24/Mid-2024 LSOA 2021-Table 1.csv",skiprows=3,)
    elif year == 2023:
        return pd.read_csv("/Users/danishanrahulan/Downloads/ons_population_19_24/Mid-2023 LSOA 2021-Table 1.csv",skiprows=3,)
    elif year == 2022:
        return pd.read_csv("/Users/danishanrahulan/Downloads/ons_population_19_24/Mid-2022 LSOA 2021-Table 1.csv",skiprows=3,)
    elif year == 2021:
        return pd.read_csv("/Users/danishanrahulan/Downloads/ons_population_19_24/Mid-2021 LSOA 2021-Table 1.csv",skiprows=3,)
    elif year == 2020:
        return pd.read_csv("/Users/danishanrahulan/Downloads/ons_population_19_24/Mid-2020 LSOA 2021-Table 1.csv",skiprows=3,)
    elif year == 2019:
        return pd.read_csv("/Users/danishanrahulan/Downloads/ons_population_19_24/Mid-2019 LSOA 2021-Table 1.csv",skiprows=3,)
    else:
        raise ValueError("Year not supported. Please choose from 2019, 2020, 2021, 2022, 2023, or 2024.")

# year = 2024
# location_name = "Elephant & castle, London"
# s, w, n, e = get_borough_bounding_poly(location_name)
# poly = f"{n},{w}:{n},{e}:{s},{e}:{s},{w}"
# all_crimes_year = [
#     crime
#     for month in range(1, 13)
#     for crime in get_crimes_in_polygon(poly, f"{year}-{month:02d}")
# ]
# lsoas_locations = get_postcode_losas(all_crimes_year)
# crime_per_year_1000 = crime_calcualtion(len(all_crimes_year), population_data(year), 'LSOA 2021 Name', lsoas_locations)
# print(f"Total Crimes: {len(all_crimes_year)}")
# print(f"Crime Rate (per 1,000): {crime_per_year_1000:.2f}")

""""Crime trend analysis"""

def crimes_trend(location, back_year, last_month):
    crimes_100_year = []
    for year in range (back_year, 2025):
        s,w,n,e = get_borough_bounding_poly(location)
        poly = f"{n},{w}:{n},{e}:{s},{e}:{s},{w}"
        all_crimes_year = [
            crime
            for month in range(last_month, 13)
            for crime in get_crimes_in_polygon(poly, f"{year}-{month:02d}")
        ] + [
            crime
            for month in range(1, last_month)
            for crime in get_crimes_in_polygon(poly, f"{year + 1}-{month:02d}")
        ]
        lsoas_locations = get_postcode_losas(all_crimes_year)
        pop_df = population_data(year)
        crimes_that_year = crime_calcualtion(len(all_crimes_year), pop_df, 'LSOA 2021 Name', lsoas_locations)
        crimes_100_year.append(crimes_that_year)
        print(crimes_that_year)
    return ([j-i for i, j in zip(crimes_100_year[:-1], crimes_100_year[1:])] , crimes_100_year)

# year = int(datetime.now().year) -3
# month = int(datetime.now().month)
# crime_difference_per_year, crime_each_year = crimes_trend("Elephant & castle, London", year, month)