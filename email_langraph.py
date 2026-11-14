import ast
import re
from datetime import datetime
import streamlit as st
from langgraph.graph import START, END, StateGraph
from ddgs import DDGS
from ddgs.exceptions import DDGSException
from openai import OpenAI
from typing_extensions import TypedDict
import requests
import json

from itertools import islice

from house_functions import (
    get_locations, 
    filter_house_df, 
    price_distribution, 
    get_property_room_count,
    get_borough_bounding_poly,
    get_crimes_in_polygon,
    get_postcode_losas,
    crime_calcualtion,
    population_data, 
    crimes_trend,
    longitude_latitude_from_postcode,
    get_houses_postcode,
    EFC_BASE_URL
)
from map_text import AMENITIES, BRANDS, DATA_SOURCES, prompt_key_list, resolve, build_search_items

STAGE_KEYS = {
    "free_data":       set(DATA_SOURCES),
    "specific_places": set(BRANDS) | {k for k, v in AMENITIES.items() if v["group"] == "cuisine"},
}
STAGE_KEYS["general_places"] = set(AMENITIES) - STAGE_KEYS["specific_places"]

ORDER = ["house_review_pc", "free_data", "specific_places", "general_places", "report"]

# Configure Streamlit layout with two columns: main content and logs
st.set_page_config(layout="wide")
main_content, log_content = st.columns(2)

# maybe remove ---------------------------------------------------------------------
def parse_natural_language_date(query: str):
    """Converts phrases like 'last 2 week summary' into ISO 8601 timestamps."""
    now = datetime.datetime.now(datetime.timezone.utc)
    query_clean = query.lower()

    # Look for "last X week(s)"
    match = re.search(r'last\s+(\d+)\s+week', query_clean)
    if match:
        weeks_count = int(match.group(1))
        time_min = now - datetime.timedelta(weeks=weeks_count)
        return time_min.isoformat(), now.isoformat()

    # Look for a simple "last week"
    if "last week" in query_clean:
        time_min = now - datetime.timedelta(weeks=1)
        return time_min.isoformat(), now.isoformat()

    # Fallback to None if it doesn't match, letting your function use its default
    return None, None

def util_st_log(content):
    log_content.markdown(
        f"<div style='font-size:10px; overflow-y: hidden'>{content}</div>",
        unsafe_allow_html=True
    )
# -----------------------------------------------------------------------------------

log_content.title("Logs")
main_content.title("Area price finder")

# Setup API clients
client = OpenAI(
    base_url="http://localhost:8080/v1",
    api_key="mock-local-key"
)
ddgs = DDGS()

# Define state structure
class State(TypedDict):
    user_search: str
    spec: dict
    location_results: list
    matched_location: str
    df_results: list
    house_area_insight: str
    efc_data: list
    crime_information: dict
    house_analysis: str
    need_summary: bool
    iteration: int
    location: str
    area_insight: str
    # event: str

FIRST_PARSER_PROMPT = """You convert a house-hunting request into JSON.
Reply with one JSON object only. No explanation, no markdown, no code fences.

Fields:
- "area": the place the user wants to live, e.g. "Merton, London". Use null if none is given.
- "amenities": a list of strings, one per thing the user wants nearby or true of the area.
  Each string must be copied exactly from the allowed keys below.
  If nothing fits, use the user's own short word instead.
  Only include what the user asked for.
  if specific brand amenities are requested, use the brand key, not the generic word.
- "max_distance_miles": a number.
  If the user states a distance, use it.
  "walking distance" -> 0.5
  "nearby", "close" or "local" -> 1.0
  Nothing said -> 2.0

Rules:
- Safety wishes ("safe", "low crime", "not dodgy") go in amenities as "safe".
- Good, top or outstanding schools -> "good_school_ofsted". Plain schools -> "school".
- A cuisine replaces the generic word: "vietnamese restaurants" -> "vietnamese", not "restaurant".
- Named chains use their brand key: "Morley's" -> "morleys", "Pepe's Piri Piri" -> "pepes".
- Use lower-case JSON values: true, false, null.

Allowed keys, by group:
<<KEYS>>

Example 1
Request: I want to find a house in Croydon, London with good schools, restaurants and parks nearby.
Answer: {"area": "Croydon, London", "amenities": ["good_school_ofsted", "restaurant", "park"], "max_distance_miles": 1.0}

Example 2
Request: Looking in Merton, London for vietnamese restaurants, Pepe's Piri Piri and Morley's within 0.5 miles, good schools, and most importantly a safe area.
Answer: {"area": "Merton, London", "amenities": ["vietnamese", "pepes", "morleys", "good_school_ofsted", "safe"], "max_distance_miles": 0.5}

Example 3
Request: Somewhere with a tube station and a gym, not too pricey.
Answer: {"area": null, "amenities": ["tube", "gym", "affordable"], "max_distance_miles": 2.0}

Example 4
Request: Zzzz
Answer: {"area": null, "amenities": [], "max_distance_miles": 2.0}

Request: <<QUERY>>
Answer:"""


def build_parser_prompt(query: str) -> str:
    return FIRST_PARSER_PROMPT.replace("<<KEYS>>", prompt_key_list()).replace("<<QUERY>>", query.strip())


def parse_query(raw: str) -> dict:
    """Turn the model's reply into a clean spec. Never raises; falls back to defaults."""
    default = {"area": None, "amenities": [], "max_distance_miles": 2.0}
    try:
        data = json.loads(raw[raw.index("{"): raw.rindex("}") + 1])
    except ValueError:
        return default
    if not isinstance(data, dict):
        return default

    amenities = []
    for term in data.get("amenities") or []:
        key = resolve(str(term))          # maps synonyms, drops unknown words
        if key and key not in amenities:
            amenities.append(key)

    try:
        dist = float(data.get("max_distance_miles", 2.0))
    except (TypeError, ValueError):
        dist = 2.0

    return {
        "area": data.get("area") or None,
        "amenities": amenities,
        "max_distance_miles": min(max(dist, 0.1), 10.0),
    }


class AreaGathererAgent:
    def location_check(self, state: State, max_retries: int = 3):
        response = client.chat.completions.create(
            # model="mlx-community/gemma-4-e4b-it-4bit",

            model = "jedisct1/gemma-4-E2B-it-txt-mlx-4bit",
            # STRICTLY use only 'user' role for Gemma
            messages=[{"role": "user", "content": build_parser_prompt(state["user_search"])}],
            max_tokens=2000
        )

        message = response.choices[0].message

        if hasattr(message, 'content') and message.content:
            insights = ast.literal_eval(message.content.strip())
            print(f"content: {insights}")
        elif hasattr(message, 'reasoning') and message.reasoning:
            # Local server put the actual text inside the reasoning block
            insights = ast.literal_eval(message.reasoning.strip())
            print(f"reasoning: {insights}")

        util_st_log(f"disgested input {insights}...")
        location_query = insights["area"]
        spec = insights
        util_st_log(f"Gathering location information for {location_query} with these amenities{spec}...")

        location_results = get_locations(location_query)
        main_content.write(f"Finding houses in {location_query}")
        return {"spec":spec, "user_search":state["user_search"], "location_results": location_results, "matched_location":"", "location":location_query, "area_insight": "", "df_results": [], "house_area_insight": "", "efc_data": [], "crime_information": [], "house_analysis": "", "need_summary": False, "iteration": 0}

class LocationReviewerAgent:
    def analyze_location_results(self, state: State):
        util_st_log("LocationReviewerAgent started...")
        raw_locations = str(state["location_results"])
        
        # 2. Explicitly tell the model NOT to waste tokens on a thinking process
        prompt = (
            f"""You are a location matcher for a UK house price search.

        User query: {state["location"]}

        Candidate matches found in the data, as column=value (level, score):
        {raw_locations}

        Levels: 1 = exact, 2 = whole word, 3 = partial, 4 = fuzzy (score shown).
        Rules:
        - Use only values that appear in the candidates above, copied exactly.
        - Prefer lower levels over higher levels.
        - Choose at most one value per column.
        - Only include a column if it helps match what the user asked for.
        - If no candidate fits the query, or every term has no matches, answer {{}}.

        Example 1
        Query: Croydon, London
        Candidates:
        "CROYDON": Town/City=CROYDON (level 1); Borough=CROYDON (level 1)
        "LONDON": Town/City=LONDON (level 1); Borough=CITY OF LONDON (level 2); County=GREATER LONDON (level 2)
        Answer: {{"Borough": "CROYDON", "County": "GREATER LONDON"}}

        Example 2
        Query: Zzzz
        Candidates:
        "ZZZZ": no matches
        Answer: {{}}

        Reply with one JSON object, nothing else, no formatting to specify JSON. No explanation."""
        )
        # if state.get("summary_feedback"):
        #     prompt += f"\n\nFeedback from reviewer to incorporate: {state['summary_feedback']}"

        try:
            response = client.chat.completions.create(
                # model="mlx-community/gemma-4-e4b-it-4bit",

                model = "jedisct1/gemma-4-E2B-it-txt-mlx-4bit",
                # STRICTLY use only 'user' role for Gemma
                messages=[{"role": "user", "content": prompt}],
                max_tokens=2000
            )

            message = response.choices[0].message
            
            if hasattr(message, 'content') and message.content:
                insights = message.content.strip()
            elif hasattr(message, 'reasoning') and message.reasoning:
                # Local server put the actual text inside the reasoning block
                insights = message.reasoning.strip()
                # Clean up internal "thinking process" meta-text if the model ignored our prompt
                if "thinking process" in insights.lower():
                    util_st_log("Note: Model returned thinking process as insights. Using it as fallback.")
            else:
                insights = "Error: The model returned a response, but both content and reasoning fields were empty."
        
        except Exception as e:
            insights = f"Analyze agent API Error ({type(e).__name__}): {str(e)}"
            print("\n\n ",insights)
        util_st_log(f"Insights generated ({len(insights)} chars): {insights[:50]}...")
        return {"location_results": state["location_results"],  "matched_location":insights, "iteration": state["iteration"], "summary_feedback": None, "location": state["location"], "area_insight": "", "df_results": []}

class HouseReviewerAgent:
    def house_pc(self, state: State, max_retries: int = 3):
        locations = state["matched_location"]
        util_st_log(f"Finding house detail info")
        location_dict = ast.literal_eval(locations) if isinstance(locations, str) else locations
        filtered_df, _ = filter_house_df(location_dict)
        util_st_log(f"Found {len(filtered_df)} matching houses.")
        main_content.write("No matching houses found." if filtered_df.empty else f"Found {len(filtered_df)} matching houses.")
        postcode_filtered_df = filtered_df.assign(longitude=filtered_df["Postcode"].apply(longitude_latitude_from_postcode).str[0], latitude=filtered_df["Postcode"].apply(longitude_latitude_from_postcode).str[1])
        print(f"Filtered DataFrame postcodes results: {postcode_filtered_df}")
        it = iter(postcode_filtered_df["Postcode"]) 
        res = [list(islice(it, 100)) for _ in range((len(postcode_filtered_df["Postcode"]) + 100 - 1) // 100)]
        list_postcodes = []
        for postcode_batch in res:
            payload = {"postcodes": postcode_batch}
            res = requests.post("https://api.postcodes.io/postcodes", json=payload).json()
            list_postcodes.extend([item['result'] for item in res.get('result', []) if item['result']])
        lsoa_mapping = {item['postcode']: item['lsoa'] for item in list_postcodes}
        postcode_filtered_df['LSOA'] = postcode_filtered_df['Postcode'].map(lsoa_mapping)
        print("FINIDSHED HOUSE PC")
        return {"location_results": state["location_results"],"df_results": postcode_filtered_df,  "matched_location":state["matched_location"], "iteration": state["iteration"], "summary_feedback": None, "location": state["location"], "area_insight": ""}

def free_data(state):
    print(f"free_data_node:")
    wanted = set(state["spec"]["amenities"]) & STAGE_KEYS["free_data"]   # e.g. {"safe", "good_school_ofsted"}
    matched_location = state["matched_location"]
    if "safe" in wanted:
        print("call police data")
    #     candidates = filter_by_crime(candidates)
    if "good_school_ofsted" in wanted:
        print("call school list")
    #     candidates = filter_by_ofsted(candidates, state["spec"]["max_distance_miles"])
    return {"matched_location": matched_location}

def general_places(state):
    print(f"general_places:")
    return state
def specific_places(state):
    print(f"specific_places:")
    return state
def report(state):
    print(f"report:")
    return state
def no_matches(state):
    print(f"no_matches: ")
    return state
# NEXT is """Crime information""" and """EPC data""" and """House analysis""" and """House area insight"""
class HouseareaInsightAgent:
    def house_area_insight(self, state: State, max_retries: int = 3):
        locations = state["matched_location"]
        # util_st_log(f"Finding house details...")
        location_dict = ast.literal_eval(locations) if isinstance(locations, str) else locations
        borough = location_dict.get("Borough")
        if borough:
            util_st_log(f"Finding house details for borough: {borough}...")
            area_insight = price_distribution(borough)
            util_st_log(f"Area insight: {area_insight}")
        else:
            util_st_log("No borough found in matched location. Cannot provide area insight.")
            area_insight = "No borough found in matched location."
        return {"location_results": state["location_results"],  "matched_location":state["matched_location"], "df_results": state["df_results"], "iteration": state["iteration"], "summary_feedback": None, "location": state["location"], "area_insight": area_insight}

class EnergyEfficiencyInsightAgent:
    def energy_efficiency_insight(self, state: State, max_retries: int = 3):

        df_houses = state["df_results"]
        if df_houses.empty:
            util_st_log("No house data available for energy efficiency analysis.")
            return {"location_results": state["location_results"],  "matched_location":state["matched_location"], "df_results": state["df_results"], "iteration": state["iteration"], "summary_feedback": None, "location": state["location"], "area_insight": state["area_insight"], "efc_data": []}
        df_houses = df_houses.sample(n=10).reset_index(drop=True)  # Shuffle the DataFrame and get sample of 10 rows
        efc_data = []
        habitable_room_counts = 0
        total_floor_area = 0
        heating_costs = 0
        potential_energy_efficiency_bands = []
        for index, row in df_houses.iterrows():
            params = f"postcode={row['Postcode'].replace(' ', '+').upper()}&address={row['Door_number'].upper()}+{row['Street'].replace(' ', '+').upper()}"
            util_st_log(f"Fetching energy efficiency data for {params}...")
            data = get_property_room_count(url=EFC_BASE_URL, params=params)
            if not data:
                util_st_log(f"No energy efficiency data found for {params}.")
                continue
            habitable_room_counts += int(data['data'].get("habitable_room_count", 0))
            total_floor_area += float(data['data'].get('total_floor_area', 0))
            heating_dict = data['data'].get('heating_cost_current')
            heating_costs += float(heating_dict.get('value', 0)) if heating_dict else 0
            potential_energy_efficiency_bands.append(data['data'].get('potential_energy_efficiency_band'))
            # Here you would call your function to fetch the energy efficiency data
            # For demonstration, we'll just append a mock dictionary
            efc_data.append({"Address": params, "EPC Rating": "B", "EPC Score": 85})
        print(f"Total habitable room counts: {habitable_room_counts}, Total floor area: {total_floor_area}, Total heating costs: {heating_costs}, Potential energy efficiency bands: {potential_energy_efficiency_bands}")
        print(f"Average habitable room counts: {habitable_room_counts / 10}, Average floor area: {total_floor_area / 10}, Average heating costs: {heating_costs / 10}, Most common potential energy efficiency band: {max(set(potential_energy_efficiency_bands), key=potential_energy_efficiency_bands.count)}")
        return {"location_results": state["location_results"],  "matched_location":state["matched_location"], "df_results": state["df_results"], "iteration": state["iteration"], "summary_feedback": None, "location": state["location"], "area_insight": state["area_insight"], "efc_data": efc_data}

class CrimeInformationAgent:
    def crime_information(self, state: State, max_retries: int = 3):
        locations = state["matched_location"]
        util_st_log(f"Finding crime information...")
        location_dict = ast.literal_eval(locations) if isinstance(locations, str) else locations
        borough = location_dict.get("Borough")
        town_city = location_dict.get("Town/City")
        if borough and town_city:
            location_name = f"{borough}, {town_city}"
            util_st_log(f"Finding crime information for {location_name}...")
            main_content.write(f"debug: {location_dict}...")
            # temp year
            year = 2024
            s, w, n, e = get_borough_bounding_poly(location_name)
            poly = f"{n},{w}:{n},{e}:{s},{e}:{s},{w}"
            all_crimes_year = [
                crime
                for month in range(1, 13)
                for crime in get_crimes_in_polygon(poly, f"{year}-{month:02d}")
            ]
            lsoas_locations = get_postcode_losas(all_crimes_year)
            crime_per_year_1000 = crime_calcualtion(len(all_crimes_year), population_data(year), 'LSOA 2021 Name', lsoas_locations)

            year = int(datetime.now().year) -3
            month = int(datetime.now().month)
            crime_difference_per_year, crime_each_year = crimes_trend(location_name, year, month)

            print(f"Total Crimes for {year}: {len(all_crimes_year)}")
            print(f"Crime Rate (per 1,000): {crime_per_year_1000:.2f}")
            print(f"Crime difference per year: {crime_difference_per_year}")
            print(f"Crime each year: {crime_each_year}")
            util_st_log(f"Total Crimes for {year}: {len(all_crimes_year)}")
            util_st_log(f"Crime Rate (per 1,000): {crime_per_year_1000:.2f}")
            util_st_log(f"Crime difference per year: {crime_difference_per_year}")
            util_st_log(f"Crime each year: {crime_each_year}")
            crime_information = {
                f"total_crimes_for_{year}": len(all_crimes_year),
                "crime_rate_per_1000": crime_per_year_1000,
                "crime_difference_per_year": crime_difference_per_year,
                "crime_each_year": crime_each_year
            }
        else:
            util_st_log("No borough found in matched location. Cannot provide crime information.")
            crime_information = []
        return {"location_results": state["location_results"],  "matched_location":state["matched_location"], "df_results": state["df_results"], "iteration": state["iteration"], "summary_feedback": None, "location": state["location"], "area_insight": state["area_insight"], "efc_data": state.get("efc_data", []), "crime_information": crime_information}

# class AnalysisAgent:
#     def analyze_data(self, state: State):
#         util_st_log("AnalysisAgent started...")
#         raw_emails = str(state["email_results"])
#         truncated_emails = raw_emails[:4000] 
        
#         # 2. Explicitly tell the model NOT to waste tokens on a thinking process
#         prompt = (
#             "You are an expert data analyst.\n"
#             "Summarize the following email and/or calendar data in clear, informative built points, highlighting in chronological order and most important/urgent emails and/or events. For each section have an emoji alongside heading.\n"
#             "CRITICAL: Do not write a thinking process, intro notes, or internal monologue. "
#             "Output ONLY the final summary paragraphs directly.\n\n"
#             f"Data\n"
#             f" - Calendar events:{str(state['calendar_results'])}"
#             f" - Emails:{truncated_emails}\n"
#         )
#         if state.get("summary_feedback"):
#             prompt += f"\n\nFeedback from reviewer to incorporate: {state['summary_feedback']}"

#         try:
#             response = client.chat.completions.create(
#                 # model="mlx-community/gemma-4-e4b-it-4bit",

#                 model = "jedisct1/gemma-4-E2B-it-txt-mlx-4bit",
#                 # STRICTLY use only 'user' role for Gemma
#                 messages=[{"role": "user", "content": prompt}],
#                 max_tokens=2000
#             )

#             message = response.choices[0].message
            
#             if hasattr(message, 'content') and message.content:
#                 insights = message.content.strip()
#             elif hasattr(message, 'reasoning') and message.reasoning:
#                 # Local server put the actual text inside the reasoning block
#                 insights = message.reasoning.strip()
#                 # Clean up internal "thinking process" meta-text if the model ignored our prompt
#                 if "thinking process" in insights.lower():
#                     util_st_log("Note: Model returned thinking process as insights. Using it as fallback.")
#             else:
#                 insights = "Error: The model returned a response, but both content and reasoning fields were empty."
        
#         except Exception as e:
#             insights = f"Analyze agent API Error ({type(e).__name__}): {str(e)}"
#             print("\n\n ",insights)
#         util_st_log(f"Insights generated ({len(insights)} chars): {insights[:50]}...")
#         return {"email_results": state["email_results"],  "calendar_results":state["calendar_results"], "insights": insights, "iteration": state["iteration"], "summary_feedback": None, "email": state["email"], "event": state["event"]}

# class ReviewerAgent:
#     def review_insights(self, state: State, max_iterations=2):
#         review_prompt = f"You are an expert reviewer.\n\nReview the following email and/or calendar event report for clarity and quality. If revision is needed, start your response with exactly 'Needs revision'.\n\nReport:\n{state['insights']}"
        
#         try:
#             response = client.chat.completions.create(
#                 # model="mlx-community/gemma-4-e4b-it-4bit",
#                 model = "jedisct1/gemma-4-E2B-it-txt-mlx-4bit",
#                 # STRICTLY use only 'user' role for Gemma
#                 messages=[{"role": "user", "content": review_prompt}],
#                 max_tokens=2000
#             )

#             # Safety fallback to prevent NoneType errors
#             raw_content = response.choices[0].message.content
#             summary_feedback = raw_content.strip() if raw_content else ""
        
#         except Exception as e:
#             summary_feedback = f"Review agent API Error: {str(e)}"

#         # This will no longer crash because summary_feedback is guaranteed to be a string
#         need_revision = "Needs revision" in summary_feedback and state["iteration"] < max_iterations

#         util_st_log(f"Review feedback: {summary_feedback[:50]}... | Needs revision: {need_revision}")
        
#         return {"email_results": state["email_results"],  "calendar_results":state["calendar_results"], "insights": state["insights"], "iteration": state["iteration"] + 1, "summary_feedback": summary_feedback if need_revision else None, "email": state["email"], "event": state["event"], "need_summary": need_revision}

# class ReportCompilerAgent:
#     def compile_report(self, state: State):
#         main_content.write(state["insights"])
#         return state


def next_stage(current):
    def router(state):
        print(f"Routing from stage: {current}")
        if not state["matched_location"]:
            print("No matched_location found, routing to no_matches")
            return "no_matches"
        for stage in ORDER[ORDER.index(current) + 1:]:
            if stage == "report" or set(state["spec"]["amenities"]) & STAGE_KEYS[stage]:
                return stage
    return router

# Instantiate agents
location_gatherer = AreaGathererAgent()
location_reviewer = LocationReviewerAgent()
house_review_pc = HouseReviewerAgent()
house_area_insight = HouseareaInsightAgent()
energy_efficiency_insight = EnergyEfficiencyInsightAgent()
crime_information_agent = CrimeInformationAgent()
# email_gatherer = EmailGathererAgent()
# event_gatherer = EventGathererAgent()
# analysis_agent = AnalysisAgent()
# reviewer_agent = ReviewerAgent()
# report_compiler = ReportCompilerAgent()

# Build the state graph
builder = StateGraph(State)
builder.add_node("location_gatherer", location_gatherer.location_check)
builder.add_node("location_reviewer", location_reviewer.analyze_location_results)
builder.add_node("house_review_pc", house_review_pc.house_pc)
builder.add_node("free_data", free_data)
builder.add_node("specific_places", specific_places)
builder.add_node("general_places", general_places)
builder.add_node("report", report)
builder.add_node("no_matches", no_matches)
builder.add_node("house_area_insight", house_area_insight.house_area_insight)
builder.add_node("energy_efficiency_insight", energy_efficiency_insight.energy_efficiency_insight)
builder.add_node("crime_information_agent", crime_information_agent.crime_information)
# builder.add_node("analyze_data", analysis_agent.analyze_data)
# builder.add_node("review_insights", reviewer_agent.review_insights)
# builder.add_node("compile_report", report_compiler.compile_report)

builder.add_edge(START, "location_gatherer")
builder.add_edge("location_gatherer", "location_reviewer")
builder.add_edge("location_reviewer", "house_review_pc")
# builder.add_edge("house_review_pc", "house_area_insight")
for stage in ORDER[:-1]:
    builder.add_conditional_edges(stage, next_stage(stage), ORDER[1:] + ["no_matches"])
# builder.add_edge("house_area_insight", "energy_efficiency_insight")
# builder.add_edge("energy_efficiency_insight", "crime_information_agent")
# builder.add_edge("house_area_insight", "analyze_data")

# FIXED: Changed from conditional_edges to standard add_edge since it's a guaranteed path
# builder.add_edge("analyze_data", "review_insights") 

# builder.add_conditional_edges("review_insights", lambda state: "analyze_data" if state["need_summary"] else "compile_report")

# FIXED: Added the final edge to tell LangGraph where the execution ends
builder.add_edge("report", END)

graph = builder.compile()

# User input and process trigger
user_search = main_content.text_input("Enter the location to find houses and what amenties you are looking for", "Merton, London, with good schools and indian restaurants, all in walking distance")
if main_content.button("Generate Report"):
    initial_state = {"user_search": user_search, "location_results": [], "matched_location": "", "df_results": [], "house_area_insight": "", "efc_data": [], "crime_information": {}, "house_analysis": "", "need_summary": False, "iteration": 0, "location": ""}
    # Using streamlit spinner for better UX while running
    with st.spinner(f"Agents are researching {user_search}... Check logs for details."):
        graph.invoke(initial_state)