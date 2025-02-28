# Standard library imports
import os
import json
import logging
import base64
import sqlite3
import datetime

# Third-party imports
import requests

# Local application imports
import common

# Constants
API_KEY = os.environ.get('FRESHDESK_API_KEY')
FRESHDESK_URL = f"https://freshdesk.com/api/v2/agents"
SQL_QUERY_INSERT = "INSERT INTO AgentUsage (NAME, EMAIL, ACTUAL_DATE_TIME, SHIFT_DATE, PREVIOUS_VALUE, NEW_VALUE) VALUES (?, ?, ?, ?, ?, ?)"
SQL_QUERY_SELECT_1 = "SELECT NAME FROM AgentUsage WHERE NAME = (?) AND SHIFT_DATE = (?)"
SQL_QUERY_SELECT_2 = "SELECT NEW_VALUE FROM AgentUsage WHERE NAME = (?) ORDER BY rowid DESC LIMIT 1"

# Set up a global custom logger object for the script
logger = common.setup_custom_logger("robot_usage_tracker")

# Configuration and setup
teams_hierarchy = common.teams_hierarchy
valid_domains = common.valid_domains
shifts_times = common.shifts_times 


# Load the teams_hierarchy and valid_domains data from a JSON file
with open('static/config.json', 'r', encoding='UTF-8') as file:
    logger.info("Loading config data from config.json")
    content = file.read()
    data = json.loads(content)
    teams_hierarchy = data["Teams"]
    valid_domains = data["valid_domains"]
    shifts_times = data["shifts_times"] 
    logger.info("Config data loaded successfully")

def build_headers():
    """Base64 encode the API key"""
    
    if not API_KEY:
        logger.error("API Key not found in environment variables")
        raise ValueError("API Key not found in environment variables")
    
    # FD API doc states we need authorization header in format 'Basic your_api_key:X"
    credentials = f"{API_KEY}:X"

    # It also requires the credentials to be base64 encoded
    # base64 encoding converts binary data into a text representation using ASCII. Hence we need to firstly need to convert (encode) the string to get a byte object --> then base64 encode the byte object to get a base64 encoded byte object --> decode the raw binary using ASCII conversion (byte object) back into a string.

    # Encode the string to get a byte object
    credentials_bytes = credentials.encode("ascii")

    base_64_credentials = base64.b64encode(credentials_bytes)

    # When you decode the byte object back into a string: decoded = 'eW91cl9hcGlfa2V5Olg='
    base_64_credentials = base_64_credentials.decode("ascii")
    
    headers_to_include = {
    "Authorization": f"Basic {base_64_credentials}",
    "Content-Type": "application/json"
    }
        
    return headers_to_include


def send_requests(cursor, conn, headers_to_include, date_time):
    """Send requests to the Freshdesk API and update the database"""
    
    # If the hour is less than or equal to e.g. 5am, credit this entry to the previous shift/date.
    if date_time.hour <= shifts_times['shift_start']:
        date = (date_time - datetime.timedelta(days=1)).date()
    else:
        # Else credit to the current shift/date.
        date = date_time.date()
    
    # Agents are spread out over multiple pages, so we need to go through each page starting at page 1
    page = 1

    while True:
        
        # Max amount of entries per page is 100
        url_with_page = f"{FRESHDESK_URL}?per_page=100&page={page}"
        
        # Send get request to url_with_page and save response object as response
        # Note timeout is set to a tuple which specifies the [0] connect and [1] read timeouts
        response = requests.get(url_with_page, headers=headers_to_include, timeout=(3.05, 27))
        
        # If we get a successful response
        if response.status_code == 200:

            # Convert the response object to a JSON object
            agents = response.json()

            # Get a list of agents that are in the teams_hierarchy
            filtered_agents = [agent for agent in agents if any(agent['contact']['name'] in name for name in teams_hierarchy.values())]

            for agent in filtered_agents:
                # If the agent isn't in the database for the current shift date, record their initial state.
                
                if not (cursor.execute(SQL_QUERY_SELECT_1, (agent['contact']['name'], date))).fetchone():
                    logger.info(f"No agent record for shift: {date}. Adding {agent['contact']['name']} to the database. Initial value = {agent['available']}")
                    cursor.execute(
                        SQL_QUERY_INSERT,
                        (agent['contact']['name'], agent['contact']['email'], date_time.strftime(r"%Y-%m-%d %H:%M:%S"), date, agent['available'], agent['available'])
                    )
                else: 
                    # Else if they are in the database for the current shift, return their latest entry. 
                    returned_tuple = (cursor.execute(SQL_QUERY_SELECT_2, (agent['contact']['name'],))).fetchone()
                    
                    # Convert the value at index 0 of the tuple into an integer. 
                    previous_available = int(returned_tuple[0])
                    
                    # If there has been a state change
                    if agent['available'] != previous_available:
                        logger.info(f"State change detected for {agent['contact']['name']}. Logged in? Previous value: {True if previous_available else False}, New value: {agent['available']}")
                        logger.info(f"Updating database.....")
                        cursor.execute(
                            SQL_QUERY_INSERT,
                            (agent['contact']['name'], agent['contact']['email'], date_time.strftime(r"%Y-%m-%d %H:%M:%S"), date, previous_available, agent['available'])
                        )
                
            # If below is true, we know we are on the last page.
            if len(agents) < 100:
                break
            # Else, move to the next page
            page += 1
        else:
            # If there's an issue with our HTTP Request
            logger.error(f"Error: {response.status_code}, {response.text}")
            break
    
    try:
        # Save changes to our DB
        conn.commit()

        logger.info("Database update complete. Closing database connection")
    except:
        # If there's an issue with our commit
        logger.error("Error committing changes to database. No changes have been made.")
        
    conn.close()
    logger.info("Successfully closed Database connection")      

def main():
    """Main function to run the script""" 
    
    # Build headers for HTTP request.
    headers_to_include = build_headers()

    # Record the current datetime
    date_time = datetime.datetime.now()
    
    # Connect to our sqlite database
    try:
        conn = sqlite3.connect(r"RobotTracker.db")
        cursor = conn.cursor()
        logger.info("Successfully connected to database ")
    except sqlite3.Error as e:
        logger.error(f"Error connecting to database: {e}")
        return
    
    # Send requests to the Freshdesk API and update the database
    send_requests(cursor, conn, headers_to_include, date_time)

if __name__ == '__main__':
    main()
