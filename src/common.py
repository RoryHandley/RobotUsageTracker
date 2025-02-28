# Standard library imports
import os
import csv
import json
import logging
import secrets
import sqlite3
import datetime as dt
from datetime import datetime, timedelta, time
from itertools import chain
from typing import List, Optional
from pathlib import Path

# Third-party imports
import redis
import redis.exceptions
import pandas as pd
import matplotlib
matplotlib.use("Agg")  # Non-interactive backend - ensures the graph is processed and saved without relying on a GUI.
import matplotlib.pyplot as plt


# Constants 
DATABASE_NAME = 'RobotTracker.db'
EXPECTED_TIME_IN_ROBOT = 5
CACHE_TTL = 3600  # 1 hour
USER_ID_LENGTH = 16
DB_PROBE_INTERVAL = 30
DESIRED_DAILY_AVAIL = 5


def setup_custom_logger(name):
    """Function to create logger object for each process"""
    # Create custom logger object using the Logger class from the logging module
    logger = logging.getLogger(name)
    # Set the minimum log level to INFO
    # Note this will default to WARNING if we don't set it, which is inherited from the root logger
    logger.setLevel(logging.INFO)

    # Unlike with the root logger, we can't use the basicConfig method to configure the logger
    # Instead, we need to configure the custom object using handlers and formatters
    
    # Create a file handler to send log messages to a file
    # Create a stream handler to send log messages to the console
    file_handler = logging.FileHandler("app.log", mode="a", encoding="utf-8")
    file_handler.setLevel(logging.INFO)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)

    # Once we've initialzed the handlers, we need to add them to the logger using the addHandler method
    # Note the handlers can be viewed by looking at the .handlers attribute of the logger object
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    # Handlers send the logs to the output destination, whereas formatter objects specify the layout of the log messages
    # Create a formatter object using the Formatter class from the logging module
    formatter = logging.Formatter('%(asctime)s:%(name)s:%(levelname)s:%(message)s', 
                              datefmt="%Y-%m-%d %H:%M")
    
    
    # Add the formatter to the handlers
    # Note setFormatter is a method of the Handler class, whereas addHandler is a method of the Logger class
    console_handler.setFormatter(formatter)
    file_handler.setFormatter(formatter)

    """ Note below is how we would do the same thing with the root logger
    
    logging.basicConfig(filename="app.log",
                        encoding="utf-8",
                        filemode="a",
                        level=logging.DEBUG, 
                        format='%(asctime)s:%(name)s:%(message)s',
                        datefmt="%Y-%m-%d %H:%M",
                        )
    """

    # Return the logger object
    return logger

# Global Logger setup
logger = setup_custom_logger("common")

# Load the teams_hierarchy and valid_domains data from a JSON file
with open('static/config.json', 'r', encoding='UTF-8') as file:
    logger.info("Loading config data from config.json")
    content = file.read()
    data = json.loads(content)
    teams_hierarchy = data["Teams"]
    valid_domains = data["valid_domains"]
    shifts_times = data["shifts_times"] 
    database_years = data["database_years_to_keep"]
    logger.info("Config data loaded successfully")

# *** HELPER FUNCTIONS ***
def connect_to_database(query: str, query_parameters: Optional[List] = None, email=False) -> List:
    """ Generic Function to query the database and return the ENTIRE results (fetch-all)
    
    """
    # Connect to the database using a Connection object
    try:
        
        logger.info("Connecting to database...")
        
        conn = sqlite3.connect(DATABASE_NAME)
        
        cursor = conn.cursor()
        
        logger.info("Connected to database.")
        
        # Unpack the data tuple using the * operator to ensure each element is passed as a separate argument
        if query_parameters:
            cursor.execute(query, (*query_parameters,))
        else:
            logger.info(f"Executing query: {query}")
            cursor.execute(query)
        
        if not email:
            logger.info("Fetching all results from database...")
            results = cursor.fetchall()
            logger.info(f"Results fetched: {len(results)}")
            return results
        else:
            logger.info("Email database updated.")
        
        # Commit the changes
        conn.commit()
        logger.info("Database changes committed.")
        
        # Close database connection
        conn.close()
        logger.info("Database connection closed.")
    
    except sqlite3.Error as e:
        logger.error(f"Error connecting to database: {e}")
        
        return


def generate_user_id(app):
    # Generate a random string of a specific length
    # token_hex() represents each byte of the specified byte length with 2 hex characters, so need to divide by two.
    user_id = app.secret_key = secrets.token_hex(USER_ID_LENGTH // 2)  
    return user_id

def create_graph(csv_file_path, agents, recurrence):
    """Create a graph of the agent's availability over time and save it as an image in the user's temp folder"""
    # Check for weekly flag
    if recurrence == "daily":
        weekly = False
    elif recurrence == "weekly":
        weekly = True
      
    # Convert to a file path object
    path = Path(csv_file_path)
    
    # Extract the folder and filename from the path
    user_folder = path.parent
    csv_filename = path.name
    
    # Read the CSV file into a pandas DataFrame
    df = pd.read_csv(csv_file_path)
    
    # Convert the Date column (and all rows under it) to datetime object
    df['Shift Date'] = pd.to_datetime(df['Shift Date']).dt.date
    
    # Convert the Time Logged In column (and all rows under it) to a timedelta object
    # Then convert the timedelta object --> seconds --> divide by 3600 to get hours
    df['Time Logged In'] = pd.to_timedelta(df['Time Logged In']).dt.total_seconds() / 3600

    logger.info(f"Weekly graphs: {weekly}")

    # Group by Date and Name and take the last entry for each agent on each day/shift
    df_daily = df.groupby(['Shift Date', 'Name']).last().reset_index()
    
    if not weekly: 
        logger.info(f"Creating Daily graphs...")
        
        # Desired total time available for each agent per day
        total_time_desired = DESIRED_DAILY_AVAIL     
    else:       
        logger.info(f"Creating Weekly graphs...")
        
        # Convert the Date column to a Period object with a weekly frequency (Monday --> Sunday)
        df_daily['Week'] = pd.to_datetime(df_daily['Shift Date']).dt.to_period('W')
        
        # Group by Week and Name to sum the Time Logged In for each week
        df_weekly = df_daily.groupby(['Week', 'Name'])['Time Logged In'].sum().reset_index()

        # Desired total time available for each agent per week
        total_time_desired = DESIRED_DAILY_AVAIL * 5
        
    # Create a list to store the paths of the saved graphs
    chart_paths = []
    
    # Create a set of all agents
    all_agents = set(agents)

    for period in df_daily['Shift Date'].unique() if not weekly else df_weekly['Week'].unique():
        if weekly:
            # Period string manipulation for weekly reports
            period_str = str(period).replace("/", "_")  # Replace '/' with '_'
            
            # Convert start date to a string
            start_date = period.start_time.strftime('%Y-%m-%d')
            
            # Get end date by manually subtracting two days and convert to string 
            end_date = (period.end_time - timedelta(days=2)).strftime('%Y-%m-%d')
            
            title = f'Hours Available from {start_date} to {end_date}'
        else:
            # Period string manipulation for daily reports
            period_str = str(period)
            title = f'Hours Available from {period}'
             
        logger.info(f"Creating graph for {start_date} to {end_date}" if weekly else f"Creating graph for {period}")
        
        # Filter out data for the current period (week or day)
        df_period = df_weekly[df_weekly['Week' if weekly else 'Shift Date'] == period] if weekly else df_daily[df_daily['Shift Date'] == period]
        
        # Create a set of agents for the current period
        agents_for_period = set(df_period['Name'])
        # Find missing agents
        missing_agents = all_agents - agents_for_period
        logger.info(f"Missing agents: {missing_agents}")
        
        # Add blank entries for missing agents
        for agent in missing_agents:
            missing_agent_df = pd.DataFrame([{'Name': agent, 'Time Logged In': 0}])
            df_period = pd.concat([df_period, missing_agent_df], ignore_index=True)
      
        # Create the plot
        plt.figure(figsize=(10, 6))  # Set the figure size
        plt.bar(df_period['Name'], df_period['Time Logged In'], color='skyblue')

        # Add titles and labels
        title = f'Hours Available from {start_date} to {end_date}' if weekly else f'Hours Available from {period}'
        plt.title(title, fontsize=14)
        plt.xlabel('Agent', fontsize=12)
        plt.ylabel('Total Hours Available', fontsize=12)
        plt.xticks(rotation=75, ha='right')  # Rotate agent names for readability
        plt.axhline(y=total_time_desired, color='r', linestyle='-', label="Desired Hours")  # Add a horizontal line for base case

        # Save the plot as an image
        plt.tight_layout()  # Ensure the layout is clean
        graph_path = os.path.join(user_folder, f"graph_{period_str}.png")
        logger.info(f"Saving to graph path {graph_path}")
        try:
            plt.savefig(graph_path)  # Save the graph with the period in the filename
            chart_paths.append(graph_path)
            logger.info(f"Graph saved to {graph_path}")
            logger.info("Adding graph to chart_paths list")
        except Exception as e:
            logger.error(f"Error saving graph to {graph_path}")
            logger.error(f"Error: {e}")
        plt.close() 
    
    return chart_paths
    
def create_csv(results, user_id=None, email=None): 
    """Create a CSV file with the filtered data and return it as an attachment"""

    # Declare/Initialize our headers for the CSV file
    headers = ["Name", "Actual Date", "Shift Date", "Previous Value", "New Value", "Time Logged In"]
    
    # Define the temp folder
    temp_folder = os.path.join('static', 'temp')
    
    # Create the temp folder if it doesn't exist already
    if not os.path.exists(temp_folder):
        os.makedirs(temp_folder)
        logger.info(f"Temp folder created at {temp_folder}")
    else:
        logger.info(f"Temp folder already exists at {temp_folder}")
        
    # Define subfolder for either the user ID or email address
    if user_id:
        user_path = os.path.join(temp_folder, user_id)
    else:
        # Create a subfolder for daily/weekly emails
        # Need to double check if I need to create this first like above
        user_path = os.path.join(temp_folder, "emails", email)
       
    # Create subfolders if they don't exist already 
    if not os.path.exists(user_path):
        os.makedirs(user_path)  # Correctly use user_path here
        logger.info(f"User folder created at {user_path}")
    else:
        logger.info(f"User folder already exists at {user_path}")
    
    # Generate a unique file name
    filename = f"filtered_data_{datetime.now().strftime('%Y%m%d%H%M%S')}.csv"
    
    # Create the full path to the CSV file
    csv_file_path = os.path.join(user_path, filename)
    logger.info(f"CSV file path: {csv_file_path}")
    
    # Declare an empty dictionary to store the shifts for each date
    shifts = {}
    
    # Write the data to the CSV file
    with open(csv_file_path, 'w', newline='') as csvfile:
        # Create a csv writer object
        writer = csv.writer(csvfile)  
        
        # Write the headers
        writer.writerow(headers)
        
        for row in results:
            # Unpack the row into variables
            name, email, actual_date_time, shift_date, previous_value, new_value = (
                row[0],
                row[1],
                row[2],
                row[3],
                int(row[4]),
                int(row[5]),
            )
            
            # Convert date/time strings to datetime objects
            actual_date_time = datetime.strptime(str(actual_date_time), r"%Y-%m-%d %H:%M:%S")
            
            # Clense the data that was recorded before the concept of shift_changes (shift date = null)
            # Note we could just do this manually in the database which I will probably do in the future, so below will be redundant.
            if not shift_date:
                if actual_date_time.hour < shifts_times['shift_start']:
                    shift_date = actual_date_time.date() - timedelta(days=1)
                else:
                    shift_date = actual_date_time.date()
            else:
                shift_date = datetime.strptime(str(shift_date), r"%Y-%m-%d").date()
        
            # Add the date to the dictionary if not already there
            if shift_date not in shifts:
                shifts[shift_date] = {}

            if name not in shifts[shift_date]:
                # Log the agent in the shifts dicitionary for the current shift date, set their total time to 0
                shifts[shift_date][name] = {"Timestamp": actual_date_time, "Totaltime":timedelta(), "Previous Value": previous_value, "New Value": new_value, "State Change Count": 0}
            elif (new_value != previous_value) and new_value == 1:
                # Login event
                # Record the login time
                shifts[shift_date][name]["Timestamp"] = actual_date_time
                
                # Increment the state change count
                shifts[shift_date][name]["State Change Count"] += 1
                
                # Update the values
                shifts[shift_date][name]["Previous Value"] = previous_value
                shifts[shift_date][name]["New Value"] = new_value
            elif (new_value != previous_value) and new_value == 0:
                # Logoff event 
                # Calculate time difference between previous login
                tdelta = actual_date_time - shifts[shift_date][name]["Timestamp"]
                shifts[shift_date][name]["Totaltime"] += tdelta
                
                # Increment the state change count
                shifts[shift_date][name]["State Change Count"] += 1
                
                # Update the values
                shifts[shift_date][name]["Previous Value"] = previous_value
                shifts[shift_date][name]["New Value"] = new_value

            
            # Check to make sure nobody has more than 8 hours
            if shifts[shift_date][name]["Totaltime"] > timedelta(hours=8):
                shifts[shift_date][name]["Totaltime"] = timedelta(hours=8)
            
            # Write the row to the CSV file
            writer.writerow([name, actual_date_time, shift_date, previous_value, new_value, shifts[shift_date][name]["Totaltime"]])

        # After processing all rows, check if any agents have an empty total time but are currently logged in
        for shift_date, agents in shifts.items():
            # Get the end of shift date and time
            end_of_shift_date_time = datetime.combine(shift_date + timedelta(days=1), time(shifts_times['shift_start']))
            
            for name, data in agents.items():
                # If they have an empty total time but are logged in at the end of the shift and have not had a state change
                if data["Totaltime"] == timedelta() and (data["New Value"] == 1) and (data["State Change Count"] == 0):
                    # Assume they've been logged in the whole shift and set the total time to 8 hours
                    data["Totaltime"] = timedelta(hours=8)
                    
                    # Append the row to the CSV file.
                    # Note this could be improved i.e. we update the last row of the csv file for that agent on that day/shift, rather than adding a new row.
                    writer.writerow([name, data["Timestamp"], shift_date, data["Previous Value"], data["New Value"], data["Totaltime"]])
                    
                elif data["Totaltime"] == timedelta() and (data["New Value"] == 1):
                    # Note this works, but doesn't account for different time zones.
                    # I.e. if x logs in at 12:00 pm and doesn't log out, x will be credited with 8 hours of time.
                    # However x shift ends at 5:00 pm, so x should only be credited with 5 hours.
               
                    # Else if they are logged in at the end of the shift but have changed state at least once
                    # Calculate the time difference between the last login and the end of the shift
                    tdelta = end_of_shift_date_time - data["Timestamp"]

                    
                    # Add the time difference to the total time
                    data["Totaltime"] += tdelta
                    
                    # If the total time is greater than 8 hours for anyone, limit it to 8 hours
                    if data["Totaltime"] > timedelta(hours=8):
                        data["Totaltime"] = timedelta(hours=8)
                    
                    writer.writerow([name, data["Timestamp"], shift_date, data["Previous Value"], data["New Value"], data["Totaltime"]])
    
    logger.info(f"CSV file saved: {csv_file_path}")
    
    if len(shifts) < 14:
        recurrence = "daily"
    elif len(shifts) >= 14:
        recurrence = "weekly"
    

    return csv_file_path, filename, recurrence

def create_datetime_object(request):
    """Convert date and time strings to datetime objects in the form YYYY-MM-DD HH:MM:SS"""

    # Get Date strings from the form or use defaults.
    start_date_string = request.form['startdate'] or dt.datetime.now().strftime(r'%Y-%m-%d')
    end_date_string = request.form['enddate'] or start_date_string

    # Get Time strings from the form or use a default time.
    start_time_string = request.form['starttime'] or '00:00'
    end_time_string = request.form['endtime'] or '23:59'

    # Combine the date and time strings and add seconds field
    start_datetime_string = f"{start_date_string} {start_time_string}:00"
    end_datetime_string = f"{end_date_string} {end_time_string}:00" 

    # Convert the combined strings to datetime objects with correct format
    start_date_time = dt.datetime.strptime(start_datetime_string, r"%Y-%m-%d %H:%M:%S")
    end_date_time = dt.datetime.strptime(end_datetime_string, r"%Y-%m-%d %H:%M:%S")

    return start_date_time, end_date_time

# *** REDIS CACHE FUNCTIONS ***
def redis_connect():
    """Connect to the Redis server and return the Redis client object"""
    # Create a Redis client object. 
    r = redis.Redis(host='localhost', port=6379, db=0)
    # Test the connection. If the connection is unnsuccessful, an exception will be raised which we handle in the parent function. 
    try:
        r.ping()
        logger.info("Successfully connected to Redis Server.")
    except redis.exceptions.ConnectionError:
        logger.error("Could not connect to Redis Server.")
        return False
    
    return r

def redis_add_to_cache(r, user_id, csv_file_path):
    """Add the user's results to the Redis cache"""
    # Add the file path to the cache against the user's session ID
    r.set(user_id, csv_file_path)
    # Set an expiry time of 1 hour (3600 seconds) for the cache
    r.expire(user_id, CACHE_TTL)
    logger.info(f"Results added to cache for user {user_id}")

def redis_pull_from_cache(r, user_id):
    """Pull the user's results from the Redis cache"""
    # List is stored as a string in the cache, so we need to convert it back to a list using the eval() function
    csv_file_path = r.get(user_id)
    
    # Return the file path with it's unique timestamp so we can access the correct file in download_csv
    return csv_file_path