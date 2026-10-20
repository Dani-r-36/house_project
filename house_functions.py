import re
houses_df = df
query = "Croydon, Dunstable, Essex"
place_query = [x.strip() for x in query.split(",") if x.strip()]
from rapidfuzz import fuzz, process, utils
house_df_borough_list = houses_df["Borough"].unique()
house_df_town_list = houses_df["Town/City"].unique()
house_df_county_list = houses_df["County"].unique()
house_df_outward = houses_df["outward_code"].unique()
def search_price(place_query,houses_df, house_df_borough_list, house_df_town_list,house_df_county_list, house_df_outward ):
    prev = ""
    matches = {}
    fuzz_borough_list = []
    fuzz_town_list = []
    for place in place_query:
        intial_match = {}
        hits = []
        exact_hit = set()
        if place:
            place = place.upper().strip() 
        else: 
            return matches, fuzz_borough_list, fuzz_town_list
        if matches.get(place) == ['borough', 'town', 'county']:
            print(f"{place} contiune")
            continue
        if re.match(r"^[A-Z]{1,2}\d[A-Z\d]?$", place.upper()):
            print(f"{place} hit regex")
            for code in house_df_outward:
                if place == code:
                    print(f"{place} outcode append")
                    exact_hit.add(f"outward code")
                    intial_match[code] = exact_hit 
                    continue
            if matches.get(place) == None:
                intial_match[place] = "No match"
        if place in house_df_borough_list:
            print(f"{place} boro first")
            print(f"{place} boro first append")
            exact_hit.add("borough")
        else:
            print(f"{place} boro second")
            for borough in house_df_borough_list:
                if place in borough:
                    print(f"{place} boro second append")
                    intial_match.setdefault(borough, set()).add("borough")
                    hits.append("borough") 
        if place in house_df_town_list:
            print(f"{place} town")
            print(f"{place} town first append")
            exact_hit.add("town")
        else:
            print(f"{place} town second")
            for town in house_df_town_list:
                if place in town:
                    print(f"{place} town second append")
                    intial_match.setdefault(town, set()).add("town")
                    hits.append("town") 
        if place in house_df_county_list:
            print(f"{place} count first")
            print(f"{place} count first append")
            exact_hit.add("county")
        else:
            print(f"{place} county second")
            for county in house_df_county_list:
                if place in county:
                    print(f"{place} count second append")
                    intial_match.setdefault(county, set()).add("county")
                    hits.append("county") 
        if not hits and not exact_hit:
            fuzz_borough_list = process.extract(place, house_df_borough_list, scorer=fuzz.WRatio, score_cutoff=85, limit=2, processor=utils.default_process)
            fuzz_town_list = process.extract(place, house_df_town_list, scorer=fuzz.WRatio, score_cutoff=85, limit=2, processor=utils.default_process)
            print(f"fuzz borough {fuzz_borough_list}")
            print(f"fuzz town {fuzz_town_list}")
            print(f"intiaal match\n{intial_match}")
            for borough in fuzz_borough_list:
                intial_match.setdefault(borough[0], set()).add("borough")
            for town in fuzz_town_list:
                intial_match.setdefault(town[0], set()).add("town")
            
            print(f"intiaal match\n{intial_match}")
        if exact_hit:
            print(f"exact match check {exact_hit}")
            matches[place] = exact_hit
        print(intial_match)
        matches = {**intial_match, **matches}
    return matches, fuzz_borough_list, fuzz_town_list 

matches, borough_fuzz, town_fuzz = search_price(place_query, houses_df, house_df_borough_list, house_df_town_list, house_df_county_list, house_df_outward)
