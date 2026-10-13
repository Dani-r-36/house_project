# import json
# from rich.markdown import Markdown
# import datetime
# from mlx_lm import load, generate, stream_generate
# from mlx_lm.sample_utils import make_sampler
# from rich.console import Console
# from rich.markdown import Markdown
# from rich.panel import Panel


# from bs4 import BeautifulSoup
# import datetime 
import os.path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# OAuth scope for Google Maps Places API (New)
SCOPES = ["https://www.googleapis.com/auth/maps-platform.places"]


def get_places_service(client_secrets_file="creds.json", token_file="token.json"):
    """
    Authenticates and builds the service client for the Places API (v1).
    """
    creds = None
    
    # Load previously saved access/refresh tokens
    if os.path.exists(token_file):
        creds = Credentials.from_authorized_user_file(token_file, SCOPES)
        
    print("creds are ", creds)
    
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            # Read OAuth client configuration from creds.json
            flow = InstalledAppFlow.from_client_secrets_file(
                client_secrets_file, SCOPES
            )
            creds = flow.run_local_server(port=0)

        # Save the user tokens into a separate token.json file
        with open(token_file, "w") as token:
            token.write(creds.to_json())

    # Build and return the Places API (v1) client
    return build("places", "v1", credentials=creds)


def get_places(look_back:str =None):
    """
    A function that returns emails within a specified timeframe.
    Args:
        look_back: The period to gather the emails from, in datetime YYYY/MM/DD format. Defaults to 2 weeks prior if None.

    """
    service = get_places_service()
    # Create the request object
    request = service.places().searchText(
        body={"textQuery": "coffee shop in elephant & castle, London"}
    )

    # Do not pass http=request.http
    response = request.execute(
        headers={
            "X-Goog-FieldMask": "places.displayName,places.formattedAddress,places.rating"
        }
    )

    for place in response.get("places", []):
        name = place.get("displayName", {}).get("text", "No Name")
        address = place.get("formattedAddress", "No Address")
        print(f"{name} - {address}")

# get_places()

import requests
from geopy.distance import geodesic
from geopy.geocoders import Nominatim
import itertools
import os

API_KEY = os.getenv('GOOGLE_MAP_KEY')
TEXT_URL = "https://places.googleapis.com/v1/places:searchText"
NEARBY_URL = "https://places.googleapis.com/v1/places:searchNearby"

HEADERS = {
    "Content-Type": "application/json",
    "X-Goog-Api-Key": API_KEY,
    "X-Goog-FieldMask": "places.displayName,places.formattedAddress,places.location"
}
# Compare distances
MAX_DISTANCE_MILES = 3.0

def search_places(payload, search_url):
    res = requests.post(search_url, json=payload, headers=HEADERS)
    return res.json().get("places", [])

# def combination_places (places: list, location: str):
#     valid_clusters = []
#     places_location = {place:search_places(f"{place} in {location}") for place in places}
#     all_combinations =  itertools.product(*places_location.values())
#     for combo in all_combinations:
#         # 1. Extract coordinates and names in one pass
#         cluster_places = [
#             {
#                 "name": place.get("displayName", {}).get("text", "Unknown"),
#                 "address": place.get("formattedAddress", ""),
#                 "coords": (place["location"]["latitude"], place["location"]["longitude"])
#             }
#             for place in combo
#         ]
        
#         # 2. Check pairwise distances with early break
#         is_valid = True
#         for p1, p2 in itertools.combinations(cluster_places, 2):
#             if geodesic(p1["coords"], p2["coords"]).miles > MAX_DISTANCE_MILES:
#                 is_valid = False
#                 break  # Exit pair check immediately
                
#         # 3. Store structured match if valid
#         if is_valid:
#             valid_clusters.append(cluster_places)
#     return valid_clusters

def combination_places (items_config, max_distance_miles):
    valid_clusters = []
    brand_results = []
    for item in items_config:
        search_type = item.get("type", "TEXT")
        payload = item.get("payload")

        if search_type == "TEXT":
            places = search_places(payload, TEXT_URL)
        elif search_type == "NEARBY":
            places = search_places(payload, NEARBY_URL)
        else:
            places = []

        if places:
            brand_results.append(places)
    if not brand_results:
        return []
    all_combinations =  itertools.product(*brand_results)
    for combo in all_combinations:
        coords = [
            (p["location"]["latitude"], p["location"]["longitude"])
            for p in combo
        ]

        # Verify if every pair in this cluster is within distance threshold
        is_valid = True
        for c1, c2 in itertools.combinations(coords, 2):
            if geodesic(c1, c2).miles > max_distance_miles:
                is_valid = False
                break
                
        # 3. Store structured match if valid
        if is_valid:
            valid_clusters.append(combo)
    return valid_clusters

geolocator = Nominatim(user_agent="houses")
location = geolocator.geocode("Merton, London")
print(location.latitude, location.longitude)
"""if they ask i want a school and morleys and transport links -? """
search_items = [
    {
        "type": "TEXT",
        "payload": {"textQuery": "Morley's Chicken in Merton, London"}
    },
    {
        "type": "TEXT",
        "payload": {"textQuery": "Pepe's Piri Piri in Merton, London"}
    },
    # 3. Nearby Category Search for Schools around Merton
    {
        "type": "NEARBY",
        "payload": {
            "includedTypes": ["primary_school", "secondary_school"],
            "locationRestriction": {
                "circle": {
                    "center": {"latitude": 51.4012, "longitude": -0.1658},
                    "radius": 2000.0
                }
            }
        }
    }
]

# Run the unified function
valid_clusters = combination_places(search_items, max_distance_miles=3.0)

# Display results
for cluster in valid_clusters:
    print("--- Found Cluster ---")
    for place in cluster:
        name = place.get("displayName", {}).get("text")
        address = place.get("formattedAddress")
        print(f" • {name} ({address})")
    print()

# print(combination_places(["Morley's", "Pepe's Piri Piri", "KFC", "Nandos"], "Merton, London"))
# print(combination_places(["railway station", "Primary Schools"], location.latitude, location.longitude))

# print(search_places(""))

