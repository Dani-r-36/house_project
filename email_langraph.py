import ast
import os
import time
import random
import streamlit as st
from langgraph.graph import START, END, StateGraph
from ddgs import DDGS
from ddgs.exceptions import DDGSException
from openai import OpenAI
from typing_extensions import TypedDict

from house_functions import get_locations, filter_house_df, price_distribution, get_property_room_count, EFC_BASE_URL

# Configure Streamlit layout with two columns: main content and logs
st.set_page_config(layout="wide")
main_content, log_content = st.columns(2)

import re
import datetime

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
main_content.title("Agentic AI Framework - LangGraph")

# Setup API clients
client = OpenAI(
    base_url="http://localhost:8080/v1",
    api_key="mock-local-key"
)
ddgs = DDGS()

# Define state structure
class State(TypedDict):
    location_results: list
    matched_location: str
    df_results: list
    house_area_insight: str
    efc_data: list
    crime_information: list
    house_analysis: str
    need_summary: bool
    iteration: int
    location: str
    area_insight: str
    # event: str

class LocationGathererAgent:
    def location_check(self, state: State, max_retries: int = 3):
        location_query = state["location"]
        util_st_log(f"Gathering location information for {location_query}...")

        location_results = get_locations(location_query)
        return {"location_results": location_results, "matched_location":"", "location":state["location"], "area_insight": "", "df_results": [], "house_area_insight": "", "efc_data": [], "crime_information": [], "house_analysis": "", "need_summary": False, "iteration": 0}

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
    def house_review(self, state: State, max_retries: int = 3):
        locations = state["matched_location"]
        util_st_log(f"Finding house details...")
        location_dict = ast.literal_eval(locations) if isinstance(locations, str) else locations
        df_results, original_df = filter_house_df(location_dict)
        util_st_log(f"Found {len(df_results)} matching houses.")
        main_content.write("No matching houses found." if df_results.empty else f"Found {len(df_results)} matching houses.")
        print(f"Filtered DataFrame results: {df_results}")
        print(df_results.head())
        print(df_results.columns)
        return {"location_results": state["location_results"],"df_results": df_results,  "matched_location":state["matched_location"], "iteration": state["iteration"], "summary_feedback": None, "location": state["location"], "area_insight": ""}

# NEXT is """Crime information""" and """EPC data""" and """House analysis""" and """House area insight"""
class HouseareaInsightAgent:
    def house_area_insight(self, state: State, max_retries: int = 3):
        locations = state["matched_location"]
        util_st_log(f"Finding house details...")
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
            heating_costs += float(heating_dict.get('value', 0))
            potential_energy_efficiency_bands.append(data['data'].get('potential_energy_efficiency_band'))
            # Here you would call your function to fetch the energy efficiency data
            # For demonstration, we'll just append a mock dictionary
            efc_data.append({"Address": params, "EPC Rating": "B", "EPC Score": 85})
        print(f"Total habitable room counts: {habitable_room_counts}, Total floor area: {total_floor_area}, Total heating costs: {heating_costs}, Potential energy efficiency bands: {potential_energy_efficiency_bands}")
        print(f"Average habitable room counts: {habitable_room_counts / 10}, Average floor area: {total_floor_area / 10}, Average heating costs: {heating_costs / 10}, Most common potential energy efficiency band: {max(set(potential_energy_efficiency_bands), key=potential_energy_efficiency_bands.count)}")
        return {"location_results": state["location_results"],  "matched_location":state["matched_location"], "df_results": state["df_results"], "iteration": state["iteration"], "summary_feedback": None, "location": state["location"], "area_insight": state["area_insight"], "efc_data": efc_data}

# https://api.get-energy-performance-data.communities.gov.uk/api/domestic/search?postcode=SW165QD&address=32+LONGTHORNTON+ROAD
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

# Instantiate agents
location_gatherer = LocationGathererAgent()
location_reviewer = LocationReviewerAgent()
house_reviewer = HouseReviewerAgent()
house_area_insight = HouseareaInsightAgent()
energy_efficiency_insight = EnergyEfficiencyInsightAgent()
# email_gatherer = EmailGathererAgent()
# event_gatherer = EventGathererAgent()
# analysis_agent = AnalysisAgent()
# reviewer_agent = ReviewerAgent()
# report_compiler = ReportCompilerAgent()

# Build the state graph
builder = StateGraph(State)
builder.add_node("location_gatherer", location_gatherer.location_check)
builder.add_node("location_reviewer", location_reviewer.analyze_location_results)
builder.add_node("house_reviewer", house_reviewer.house_review)
builder.add_node("house_area_insight", house_area_insight.house_area_insight)
builder.add_node("energy_efficiency_insight", energy_efficiency_insight.energy_efficiency_insight)
# builder.add_node("analyze_data", analysis_agent.analyze_data)
# builder.add_node("review_insights", reviewer_agent.review_insights)
# builder.add_node("compile_report", report_compiler.compile_report)

builder.add_edge(START, "location_gatherer")
builder.add_edge("location_gatherer", "location_reviewer")
builder.add_edge("location_reviewer", "house_reviewer")
builder.add_edge("house_reviewer", "house_area_insight")
builder.add_edge("house_area_insight", "energy_efficiency_insight")
# builder.add_edge("house_area_insight", "analyze_data")

# FIXED: Changed from conditional_edges to standard add_edge since it's a guaranteed path
# builder.add_edge("analyze_data", "review_insights") 

# builder.add_conditional_edges("review_insights", lambda state: "analyze_data" if state["need_summary"] else "compile_report")

# FIXED: Added the final edge to tell LangGraph where the execution ends
builder.add_edge("energy_efficiency_insight", END)

graph = builder.compile()

# User input and process trigger
location = main_content.text_input("Enter the location to find houses", "Merton, London")
if main_content.button("Generate Report"):
    initial_state = {"location_results": [], "matched_location": "", "df_results": [], "house_area_insight": "", "efc_data": [], "crime_information": [], "house_analysis": "", "need_summary": False, "iteration": 0, "location": location}
    # Using streamlit spinner for better UX while running
    with st.spinner(f"Agents are researching {location}... Check logs for details."):
        graph.invoke(initial_state)