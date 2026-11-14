"""
amenity_lookup.py

Maps what a user says ("tube", "nursery", "chippy", "safe") onto something your
code can act on. Three layers:

  1. AMENITIES      canonical key -> how to search Google Places (New)
  2. BRANDS         canonical key -> text query for a named chain
  3. DATA_SOURCES   things that are NOT Places searches (safety, school quality...)
  4. SYNONYMS       messy user words -> canonical key

The LLM should only ever be allowed to output canonical keys (see prompt_key_list()),
or free words that resolve() can map. Everything after that is plain code.

Place types are from Google's Places API (New) "Table A". Google adds and renames
types occasionally, so run smoke_test() once to catch any that have changed.
"""
from __future__ import annotations

import os

# ---------------------------------------------------------------------------
# 1. Category searches (searchNearby, includedTypes)
#    group    - used to organise the prompt and the UI
#    mode     - NEARBY (by place type) or TEXT (by query string)
#    types    - Places type strings (max 50 per call; we use 1-4)
#    radius_m - sensible default search radius around the anchor, in metres
# ---------------------------------------------------------------------------


def N(group: str, types: list[str], radius_m: int = 1000) -> dict:
    return {"group": group, "mode": "NEARBY", "types": types, "radius_m": radius_m}


def T(group: str, query: str, radius_m: int = 1500) -> dict:
    """Text-search entry. {area} is filled in at build time."""
    return {"group": group, "mode": "TEXT", "query": query, "radius_m": radius_m}


AMENITIES: dict[str, dict] = {
    # ---- Education --------------------------------------------------------
    "school":            N("education", ["primary_school", "secondary_school"], 1500),
    "primary_school":    N("education", ["primary_school"], 1200),
    "secondary_school":  N("education", ["secondary_school"], 2000),
    "nursery":           N("education", ["preschool"], 1200),
    "sixth_form":        T("education", "sixth form college in {area}", 3000),
    "university":        N("education", ["university"], 5000),
    "library":           N("education", ["library"], 1500),
    "tutoring":          T("education", "tutoring centre in {area}", 2000),

    # ---- Food & drink: general -------------------------------------------
    "restaurant":        N("food", ["restaurant", "fast_food_restaurant", "fine_dining_restaurant"], 800),
    "cafe":              N("food", ["cafe", "coffee_shop", "bakery"], 800),
    "coffee_shop":       N("food", ["cafe", "coffee_shop", "bakery"], 800),
    "bakery":            N("food", ["bakery"], 800),
    "pub":               N("food", ["pub"], 800),
    "bar":               N("food", ["bar", "wine_bar", "pub"], 800),
    "takeaway":          N("food", ["meal_takeaway", "fast_food_restaurant"], 800),
    "fast_food":         N("food", ["fast_food_restaurant"], 800),
    "fine_dining":       N("food", ["fine_dining_restaurant"], 2000),
    "brunch":            N("food", ["brunch_restaurant", "breakfast_restaurant"], 1200),
    "dessert":           N("food", ["dessert_shop", "ice_cream_shop", "dessert_restaurant"], 1000),
    "food_delivery":     N("food", ["meal_delivery"], 2000),

    # ---- Food & drink: cuisines ------------------------------------------
    "indian":            N("cuisine", ["indian_restaurant"], 1500),
    "chinese":           N("cuisine", ["chinese_restaurant"], 1500),
    "italian":           N("cuisine", ["italian_restaurant"], 1500),
    "pizza":             N("cuisine", ["pizza_restaurant"], 1500),
    "japanese":          N("cuisine", ["japanese_restaurant", "ramen_restaurant", "sushi_restaurant"], 1500),
    "sushi":             N("cuisine", ["sushi_restaurant"], 2000),
    "ramen":             N("cuisine", ["ramen_restaurant"], 2000),
    "thai":              N("cuisine", ["thai_restaurant"], 1500),
    "vietnamese":        N("cuisine", ["vietnamese_restaurant"], 2000),
    "korean":            N("cuisine", ["korean_restaurant"], 2000),
    "turkish":           N("cuisine", ["turkish_restaurant"], 1500),
    "greek":             N("cuisine", ["greek_restaurant"], 1500),
    "lebanese":          N("cuisine", ["lebanese_restaurant"], 1500),
    "middle_eastern":    N("cuisine", ["middle_eastern_restaurant", "lebanese_restaurant", "afghani_restaurant"], 1500),
    "mediterranean":     N("cuisine", ["mediterranean_restaurant"], 1500),
    "mexican":           N("cuisine", ["mexican_restaurant"], 1500),
    "french":            N("cuisine", ["french_restaurant"], 2000),
    "spanish":           N("cuisine", ["spanish_restaurant"], 2000),
    "african":           N("cuisine", ["african_restaurant"], 2000),
    "brazilian":         N("cuisine", ["brazilian_restaurant"], 2500),
    "american":          N("cuisine", ["american_restaurant", "hamburger_restaurant"], 1500),
    "burger":            N("cuisine", ["hamburger_restaurant"], 1500),
    "bbq":               N("cuisine", ["barbecue_restaurant"], 2000),
    "steakhouse":        N("cuisine", ["steak_house"], 2000),
    "seafood":           N("cuisine", ["seafood_restaurant"], 2000),
    "vegan":             N("cuisine", ["vegan_restaurant"], 2000),
    "vegetarian":        N("cuisine", ["vegetarian_restaurant", "vegan_restaurant"], 2000),
    # No Places type exists for these British staples, so use text queries
    "fish_and_chips":    T("cuisine", "fish and chip shop in {area}", 1500),
    "chicken_shop":      T("cuisine", "chicken shop in {area}", 1200),
    "kebab":             T("cuisine", "kebab shop in {area}", 1200),
    "caribbean":         T("cuisine", "caribbean restaurant in {area}", 2000),
    "peri_peri":         T("cuisine", "peri peri chicken in {area}", 2000),

    # ---- Shopping & daily errands ----------------------------------------
    "supermarket":       N("shopping", ["supermarket"], 1200),
    "grocery":           N("shopping", ["grocery_store", "supermarket"], 1000),
    "convenience_store": N("shopping", ["convenience_store"], 600),
    "market":            N("shopping", ["market"], 2000),
    "butcher":           T("shopping", "butcher in {area}", 1500),
    "greengrocer":       T("shopping", "greengrocer in {area}", 1500),
    "bookshop":          N("shopping", ["book_store"], 2000),
    "shopping_mall":     N("shopping", ["shopping_mall"], 4000),
    "department_store":  N("shopping", ["department_store"], 4000),
    "clothing":          N("shopping", ["clothing_store"], 2000),
    "hardware":          N("shopping", ["hardware_store", "home_improvement_store"], 2000),
    "furniture":         N("shopping", ["furniture_store", "home_goods_store"], 3000),
    "electronics":       N("shopping", ["electronics_store"], 3000),
    "pet_shop":          N("shopping", ["pet_store"], 2000),
    "florist":           N("shopping", ["florist"], 1500),
    "off_licence":       N("shopping", ["liquor_store"], 1000),
    "bike_shop":         N("shopping", ["bicycle_store"], 2000),

    # ---- Transport --------------------------------------------------------
    "tube":              N("transport", ["subway_station"], 1200),
    "train_station":     N("transport", ["train_station"], 1500),
    "light_rail":        N("transport", ["light_rail_station"], 1200),   # DLR / Tramlink
    "any_station":       N("transport", ["subway_station", "train_station", "light_rail_station"], 1500),
    "bus_stop":          N("transport", ["bus_stop"], 400),
    "bus_station":       N("transport", ["bus_station"], 2000),
    "transit_station":   N("transport", ["transit_station"], 1500),
    "airport":           N("transport", ["airport", "international_airport"], 40000),
    "taxi":              N("transport", ["taxi_stand"], 1500),
    "ev_charging":       N("transport", ["electric_vehicle_charging_station"], 1000),
    "parking":           N("transport", ["parking"], 500),
    "petrol_station":    N("transport", ["gas_station"], 2000),

    # ---- Health & wellbeing ----------------------------------------------
    "gp":                N("health", ["doctor"], 1500),
    "dentist":           N("health", ["dentist", "dental_clinic"], 1500),
    "hospital":          N("health", ["hospital"], 5000),
    "pharmacy":          N("health", ["pharmacy"], 1000),
    "physio":            N("health", ["physiotherapist"], 2000),
    "vet":               N("health", ["veterinary_care"], 2500),
    "optician":          T("health", "optician in {area}", 1500),
    "gym":               N("health", ["gym", "fitness_center"], 1500),
    "swimming_pool":     N("health", ["swimming_pool"], 2500),
    "yoga":              N("health", ["yoga_studio"], 2000),
    "spa":               N("health", ["spa", "wellness_center"], 3000),

    # ---- Green space & leisure -------------------------------------------
    "park":              N("leisure", ["park"], 1000),
    "playground":        N("leisure", ["playground"], 800),
    "dog_park":          N("leisure", ["dog_park"], 1500),
    "garden":            N("leisure", ["garden", "botanical_garden"], 2500),
    "sports_centre":     N("leisure", ["sports_complex", "sports_club", "athletic_field"], 2500),
    "golf":              N("leisure", ["golf_course"], 8000),
    "cinema":            N("leisure", ["movie_theater"], 4000),
    "theatre":           N("leisure", ["performing_arts_theater", "concert_hall"], 5000),
    "museum":            N("leisure", ["museum"], 5000),
    "art_gallery":       N("leisure", ["art_gallery"], 5000),
    "nightclub":         N("leisure", ["night_club"], 3000),
    "bowling":           N("leisure", ["bowling_alley"], 5000),
    "community_centre":  N("leisure", ["community_center"], 1500),
    "tourist_attraction": N("leisure", ["tourist_attraction"], 5000),

    # ---- Places of worship -----------------------------------------------
    "church":            N("worship", ["church"], 1500),
    "mosque":            N("worship", ["mosque"], 2000),
    "hindu_temple":      N("worship", ["hindu_temple"], 3000),
    "synagogue":         N("worship", ["synagogue"], 3000),
    "place_of_worship":  N("worship", ["church", "mosque", "hindu_temple", "synagogue"], 2000),

    # ---- Civic & services ------------------------------------------------
    "bank":              N("services", ["bank"], 1500),
    "atm":               N("services", ["atm"], 800),
    "post_office":       N("services", ["post_office"], 1500),
    "police_station":    N("services", ["police"], 3000),
    "fire_station":      N("services", ["fire_station"], 4000),
    "laundrette":        N("services", ["laundry"], 1200),
    "hairdresser":       N("services", ["hair_salon", "hair_care", "barber_shop"], 1000),
    "estate_agent":      N("services", ["real_estate_agency"], 1500),
    "cemetery":          N("services", ["cemetery"], 2000),
    "co_working":        T("services", "co-working space in {area}", 3000),
}

# ---------------------------------------------------------------------------
# 2. Brands -> text queries (searchText). Add as many as you like.
# ---------------------------------------------------------------------------
BRANDS: dict[str, dict] = {
    "morleys":      T("brand", "Morley's Chicken in {area}", 3000),
    "pepes":        T("brand", "Pepe's Piri Piri in {area}", 3000),
    "nandos":       T("brand", "Nando's in {area}", 3000),
    "kfc":          T("brand", "KFC in {area}", 3000),
    "mcdonalds":    T("brand", "McDonald's in {area}", 3000),
    "greggs":       T("brand", "Greggs in {area}", 2000),
    "pret":         T("brand", "Pret A Manger in {area}", 2000),
    "gails":        T("brand", "GAIL's Bakery in {area}", 3000),
    "costa":        T("brand", "Costa Coffee in {area}", 2000),
    "starbucks":    T("brand", "Starbucks in {area}", 2000),
    "wetherspoons": T("brand", "Wetherspoons pub in {area}", 3000),
    "franco_manca": T("brand", "Franco Manca in {area}", 3000),
    "tesco":        T("brand", "Tesco in {area}", 2000),
    "sainsburys":   T("brand", "Sainsbury's in {area}", 2000),
    "waitrose":     T("brand", "Waitrose in {area}", 3000),
    "aldi":         T("brand", "Aldi in {area}", 3000),
    "lidl":         T("brand", "Lidl in {area}", 3000),
    "marks_spencer": T("brand", "Marks & Spencer Foodhall in {area}", 3000),
    "co_op":        T("brand", "Co-op Food in {area}", 1500),
    "boots":        T("brand", "Boots pharmacy in {area}", 2000),
    "puregym":      T("brand", "PureGym in {area}", 3000),
    "gym_group":    T("brand", "The Gym Group in {area}", 3000),
    "david_lloyd":  T("brand", "David Lloyd Club in {area}", 5000),
}

# ---------------------------------------------------------------------------
# 3. Things that are NOT Places searches. The parser can emit these keys too,
#    but the code that handles them calls a different dataset.
#    join_key is what you use to attach the data to an anchor point.
# ---------------------------------------------------------------------------
DATA_SOURCES: dict[str, dict] = {
    "safe": {
        "source": "data.police.uk street-level crimes",
        "how": "crimes per 1,000 residents per LSOA, ranked as a percentile across London",
        "join_key": "LSOA 2021 code (via postcodes.io)",
    },
    "burglary_low": {
        "source": "data.police.uk, filtered to category 'burglary'",
        "how": "same as 'safe' but one crime category",
        "join_key": "LSOA 2021 code",
    },
    "violence_low": {
        "source": "data.police.uk, categories 'violent-crime' + 'robbery'",
        "how": "same as 'safe' but one crime category group",
        "join_key": "LSOA 2021 code",
    },
    "good_school_ofsted": {
        "source": "DfE Get Information About Schools + Ofsted inspection outcomes",
        "how": "filter schools to Outstanding/Good, then nearest-neighbour distance",
        "join_key": "school lat/lon (or postcode)",
    },
    "good_school_results": {
        "source": "DfE school performance tables (KS2 / GCSE / Progress 8)",
        "how": "threshold on published results, then nearest-neighbour distance",
        "join_key": "school URN",
    },
    "commute": {
        "source": "TfL Unified API journey planner",
        "how": "journey time from anchor to a user-supplied destination",
        "join_key": "lat/lon",
    },
    "quiet": {
        "source": "DEFRA strategic noise maps",
        "how": "noise band at the anchor point",
        "join_key": "lat/lon",
    },
    "clean_air": {
        "source": "London Air Quality Network / DEFRA modelled NO2",
        "how": "annual mean at the anchor point",
        "join_key": "lat/lon",
    },
    "low_flood_risk": {
        "source": "Environment Agency flood risk datasets",
        "how": "flood zone at the anchor point",
        "join_key": "lat/lon",
    },
    "fast_broadband": {
        "source": "Ofcom Connected Nations postcode data",
        "how": "max available download speed",
        "join_key": "postcode",
    },
    "low_deprivation": {
        "source": "English Indices of Deprivation (IMD 2019)",
        "how": "decile per LSOA",
        "join_key": "LSOA code",
    },
    "affordable": {
        "source": "your Land Registry dataframe (price_distribution)",
        "how": "median price vs budget",
        "join_key": "postcode / borough",
    },
    "energy_efficient": {
        "source": "your EPC lookup (get_property_room_count)",
        "how": "average EPC band / heating cost",
        "join_key": "address",
    },
}

# ---------------------------------------------------------------------------
# 4. Synonyms: user word -> canonical key (AMENITIES, BRANDS or DATA_SOURCES).
#    Lower-case, spaces allowed. resolve() also tries replacing spaces/hyphens
#    with underscores, so "fish and chips" and "fish-and-chips" both work.
# ---------------------------------------------------------------------------
SYNONYMS: dict[str, str] = {
    # education
    "schools": "school", "primary": "primary_school", "primary schools": "primary_school",
    "secondary": "secondary_school", "high school": "secondary_school",
    "secondary schools": "secondary_school", "nurseries": "nursery",
    "preschool": "nursery", "pre-school": "nursery", "daycare": "nursery",
    "childcare": "nursery", "college": "sixth_form", "sixth form": "sixth_form",
    "uni": "university", "universities": "university", "libraries": "library",
    "tutor": "tutoring", "tutors": "tutoring",
    "good schools": "good_school_ofsted", "outstanding school": "good_school_ofsted",
    "ofsted": "good_school_ofsted", "top schools": "good_school_results",
    # food
    "restaurants": "restaurant", "food": "restaurant", "places to eat": "restaurant",
    "eating out": "restaurant", "cafes": "cafe", "coffee": "cafe", "coffee shop": "cafe",
    "coffee shops": "cafe", "bakeries": "bakery", "pubs": "pub", "bars": "bar",
    "takeaways": "takeaway", "take out": "takeaway", "takeout": "takeaway",
    "fast food": "fast_food", "fine dining": "fine_dining", "posh restaurants": "fine_dining",
    "delivery": "food_delivery", "indian food": "indian", "curry": "indian",
    "chinese food": "chinese", "italian food": "italian", "pasta": "italian",
    "pizzeria": "pizza", "pizzas": "pizza", "japanese food": "japanese",
    "thai food": "thai", "korean food": "korean", "turkish food": "turkish",
    "mexican food": "mexican", "tacos": "mexican", "burgers": "burger",
    "barbecue": "bbq", "steak": "steakhouse", "fish": "seafood",
    "plant based": "vegan", "plant-based": "vegan", "veggie": "vegetarian",
    "chippy": "fish_and_chips", "fish and chips": "fish_and_chips", "chip shop": "fish_and_chips",
    "chicken": "chicken_shop", "fried chicken": "chicken_shop", "kebabs": "kebab",
    "jerk": "caribbean", "piri piri": "peri_peri", "peri peri": "peri_peri",
    "pepe's": "pepes", "pepe's piri piri": "pepes", "morley's": "morleys",
    "morley's chicken": "morleys", "nando's": "nandos", "mcdonald's": "mcdonalds",
    "maccies": "mcdonalds", "sainsbury's": "sainsburys", "m&s": "marks_spencer",
    "marks and spencer": "marks_spencer", "gail's": "gails", "wetherspoon": "wetherspoons",
    "spoons": "wetherspoons", "pure gym": "puregym", "gym group": "gym_group",
    # shopping
    "supermarkets": "supermarket", "groceries": "grocery", "shops": "convenience_store",
    "corner shop": "convenience_store", "corner shops": "convenience_store",
    "local shops": "convenience_store", "markets": "market", "farmers market": "market",
    "bookstore": "bookshop", "book shop": "bookshop", "mall": "shopping_mall",
    "shopping centre": "shopping_mall", "diy": "hardware", "ikea": "furniture",
    "pet store": "pet_shop", "pets": "pet_shop", "flowers": "florist",
    "liquor store": "off_licence", "bottle shop": "off_licence", "bike shop": "bike_shop",
    # transport
    "underground": "tube", "subway": "tube", "metro": "tube", "tube station": "tube",
    "tube stations": "tube", "rail": "train_station", "railway": "train_station",
    "railway station": "train_station", "overground": "train_station",
    "elizabeth line": "train_station", "national rail": "train_station",
    "station": "any_station", "stations": "any_station", "transport": "any_station",
    "transport links": "any_station", "public transport": "any_station",
    "commuter links": "any_station", "dlr": "light_rail", "tram": "light_rail",
    "trams": "light_rail", "buses": "bus_stop", "bus": "bus_stop", "bus stops": "bus_stop",
    "coach station": "bus_station", "airports": "airport", "cab": "taxi", "taxis": "taxi",
    "ev charger": "ev_charging", "electric car charging": "ev_charging",
    "car park": "parking", "petrol": "petrol_station", "gas station": "petrol_station",
    "commute time": "commute", "short commute": "commute",
    # health
    "doctor": "gp", "doctors": "gp", "surgery": "gp", "gp surgery": "gp",
    "dentists": "dentist", "a&e": "hospital", "hospitals": "hospital",
    "chemist": "pharmacy", "chemists": "pharmacy", "physiotherapist": "physio",
    "vets": "vet", "opticians": "optician", "gyms": "gym", "fitness": "gym",
    "swimming": "swimming_pool", "pool": "swimming_pool", "leisure centre": "swimming_pool",
    "pilates": "yoga",
    # leisure
    "parks": "park", "green space": "park", "greenery": "park", "playgrounds": "playground",
    "kids play area": "playground", "dog walking": "dog_park", "gardens": "garden",
    "sports": "sports_centre", "sports centre": "sports_centre", "football pitch": "sports_centre",
    "golf course": "golf", "movies": "cinema", "film": "cinema", "theater": "theatre",
    "museums": "museum", "galleries": "art_gallery", "clubs": "nightclub",
    "nightlife": "nightclub", "community centre": "community_centre",
    "things to do": "tourist_attraction", "attractions": "tourist_attraction",
    # worship / services
    "churches": "church", "mosques": "mosque", "temple": "hindu_temple", "temples": "hindu_temple",
    "synagogues": "synagogue", "worship": "place_of_worship", "religious": "place_of_worship",
    "banks": "bank", "cash machine": "atm", "cashpoint": "atm", "police": "police_station",
    "launderette": "laundrette", "laundry": "laundrette", "laundromat": "laundrette",
    "hairdressers": "hairdresser", "barber": "hairdresser", "barbers": "hairdresser",
    "hair salon": "hairdresser", "estate agents": "estate_agent",
    "coworking": "co_working", "co-working": "co_working", "wfh": "co_working",
    # data-source keys
    "safety": "safe", "low crime": "safe", "crime": "safe", "safer": "safe", "secure": "safe",
    "not dodgy": "safe", "burglary": "burglary_low", "break ins": "burglary_low",
    "violent crime": "violence_low", "knife crime": "violence_low",
    "peaceful": "quiet", "low noise": "quiet", "air quality": "clean_air",
    "pollution": "clean_air", "flooding": "low_flood_risk", "flood": "low_flood_risk",
    "broadband": "fast_broadband", "internet": "fast_broadband", "wifi": "fast_broadband",
    "deprivation": "low_deprivation", "price": "affordable", "cheap": "affordable",
    "budget": "affordable", "epc": "energy_efficient",
}

# Words that only affect weighting or filters, not search. Handy to teach the parser.
MODIFIERS = {
    "walking_distance": 800,    # metres
    "close": 1000,
    "nearby": 1500,
    "short_drive": 5000,
}

# ---------------------------------------------------------------------------
# Resolution and builders
# ---------------------------------------------------------------------------

def resolve(term: str) -> str | None:
    """Map free text to a canonical key, or None if unknown."""
    t = term.strip().lower()
    if not t:
        return None
    candidates = [t, t.replace(" ", "_").replace("-", "_")]
    for c in candidates:
        if c in AMENITIES or c in BRANDS or c in DATA_SOURCES:
            return c
    for c in (t, t.replace("-", " ")):
        if c in SYNONYMS:
            return SYNONYMS[c]
    return None


def kind_of(key: str) -> str:
    """'places' (searchable via Google Places) or 'data' (needs another dataset)."""
    return "data" if key in DATA_SOURCES else "places"


def build_search_item(key: str, lat: float, lng: float, area: str = "London",
                      radius_m: int | None = None) -> dict:
    """Return an entry in the same shape as your search_items list in maps.py."""
    spec = AMENITIES.get(key) or BRANDS.get(key)
    if spec is None:
        raise KeyError(f"'{key}' is not a Places-searchable key")
    radius = float(min(radius_m or spec["radius_m"], 50000))
    circle = {"center": {"latitude": lat, "longitude": lng}, "radius": radius}

    if spec["mode"] == "TEXT":
        return {
            "type": "TEXT",
            "key": key,
            "payload": {
                "textQuery": spec["query"].format(area=area),
                "locationBias": {"circle": circle},
                "regionCode": "GB",
                "pageSize": 20,
            },
        }
    return {
        "type": "NEARBY",
        "key": key,
        "payload": {
            "includedTypes": spec["types"],
            "locationRestriction": {"circle": circle},
            "rankPreference": "DISTANCE",
            "maxResultCount": 20,       # hard cap of the API; use a grid for more
            "regionCode": "GB",
        },
    }


def build_search_items(keys: list[str], lat: float, lng: float, area: str = "London") -> tuple[list[dict], list[str]]:
    """
    Resolve a list of user terms. Returns (search_items, data_keys) where data_keys
    are the ones that need non-Places handling (safety, Ofsted, commute...).
    """
    items, data_keys, seen = [], [], set()
    for term in keys:
        k = resolve(term)
        if k is None or k in seen:
            continue
        seen.add(k)
        if kind_of(k) == "data":
            data_keys.append(k)
        else:
            items.append(build_search_item(k, lat, lng, area))
    return items, data_keys


def prompt_key_list() -> str:
    """Compact, grouped list of allowed keys to paste into the parser prompt."""
    groups: dict[str, list[str]] = {}
    for k, v in {**AMENITIES, **BRANDS}.items():
        groups.setdefault(v["group"], []).append(k)
    groups["data (non-search)"] = list(DATA_SOURCES)
    return "\n".join(f"{g}: {', '.join(ks)}" for g, ks in groups.items())


def smoke_test(lat: float = 51.4012, lng: float = -0.1658) -> None:
    """Call every NEARBY key once (1 result) to catch type names Google has changed."""
    import requests

    key = os.getenv("GOOGLE_MAP_KEY")
    headers = {"Content-Type": "application/json", "X-Goog-Api-Key": key,
               "X-Goog-FieldMask": "places.displayName"}
    url = "https://places.googleapis.com/v1/places:searchNearby"
    for k, spec in AMENITIES.items():
        if spec["mode"] != "NEARBY":
            continue
        item = build_search_item(k, lat, lng)
        item["payload"]["maxResultCount"] = 1
        r = requests.post(url, json=item["payload"], headers=headers)
        status = "ok" if r.ok else f"FAIL {r.status_code}: {r.text[:120]}"
        print(f"{k:22s} {status}")


if __name__ == "__main__":
    print(prompt_key_list())
