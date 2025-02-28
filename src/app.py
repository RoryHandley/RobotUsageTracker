# Standard library imports
import os
import secrets
import datetime as dt
import sqlite3

# Third-party imports
from flask import (
    Flask, request, send_file, render_template, jsonify,
    send_from_directory, session, after_this_request, redirect, url_for
)
from apscheduler.schedulers.background import BackgroundScheduler

# Local application imports
import common
import utilities

# Flask app setup
app = Flask(__name__)

# Secret key for session management
app.secret_key = secrets.token_hex(16)  

# Set up a global custom logger object for this script
logger = common.setup_custom_logger("app.py")

# *** ROUTES ***  
@app.before_request
def before_request():
    """Set the user's session ID if it doesn't exist"""

    if 'id' not in session:
        # Logging
        logger.info("User ID not found in session object")
        
        # Set the userID
        session['id'] = common.generate_user_id(app)
        
        # Logging
        logger.info(f"User ID set to {session['id']}")
    else:
        # Logging
        logger.info(f"User ID found in session object: {session['id']}")
        pass

@app.route('/', methods=['GET'])
def homepage():
    """ Render the homepage.html template to the browser with specific data """
    
    return render_template('homepage.html', teams_hierarchy=common.teams_hierarchy, valid_domains=common.valid_domains, user_id=session['id'])

@app.route(f'/filter_<user_id>', methods=['POST'])
def filter_data(user_id):
    """ Filter the data based on the form inputs and return the results as a JSON object """
 
    # Create datetime objects from the form inputs
    start_date_time, end_date_time = common.create_datetime_object(request)
    
    # Get a list of agent emails from the form (referencing the name attribute in the HTML form)
    agents = request.form.getlist('agent')
    
    # Update the database if the user has opted in to receive emails 
    utilities.email_opt_in(request, agents)

    # Concatenate the start and end date time objects with the agents list to create a list of query parameters
    query_paramaters = [start_date_time, end_date_time] + agents
    
    # Build the SQL query
    placeholders = ','.join(['?'] * len(agents))
    sql_query = f"SELECT * FROM AgentUsage WHERE ACTUAL_DATE_TIME BETWEEN ? AND ? AND NAME IN ({placeholders})"
    
    
    # Query the database
    results = common.connect_to_database(sql_query, query_paramaters)
    
    # Map the user's session ID to the csv_file_path and filename so we can access it later
    # Firstly we need to get the user's session ID from the session object
    user_id = session.get('id')
    
    # Create csv and save in user specific temp folder
    csv_file_path, filename, recurrence = common.create_csv(results, user_id)
    
    # Connect to the Redis server
    r = common.redis_connect()
    
    if not r:
        # Return error page if the Redis cache isn't available
        logger.error("Redis cache not available")
        return render_template("error.html")
    else:
        # Add the results to the cache against the user's session ID
        common.redis_add_to_cache(r, user_id, csv_file_path)
    
    # Create a graph and save it as an image in the user's temp folder
    chart_paths = common.create_graph(csv_file_path, agents, recurrence)
    
    # Return the chart data and CSV download URL as JSON
    return render_template('filter.html', chart_paths=chart_paths)

@app.route('/download_csv', methods=['GET'])
def download_csv():
    """Send the generated CSV file for the user's query results."""
    
    # Get the user's session ID from the session object
    user_id = session.get('id')
    
    try:
        # Connect to the Redis server
        r = common.redis_connect()
        
        if r:
            # Identify the user's csv file path
            csv_file_path = common.redis_pull_from_cache(r, user_id).decode('utf-8')
            
            # Get the filename from the path
            filename = os.path.basename(csv_file_path)

            # Send the file back to the browser directly from the temp directory
            response = send_file(
                csv_file_path,
                as_attachment=True,
                download_name=filename,
            )
            
            return response
        else:
            logger.error("Redis cache not available")
            return render_template("error.html")
        
    except FileNotFoundError:
        logger.error("File not found")
        return "File not found", 404

if __name__ == '__main__':
    
    # Create a scheduler object
    scheduler = BackgroundScheduler()
    
    # Add jobs to the scheduler
    scheduler.add_job(utilities.delete_old_records, 'cron', day_of_week='sun', hour=12, minute=30)
    scheduler.add_job(utilities.email_main, 'cron', kwargs={'recurrence': 'daily'}, day_of_week='tue-sat', hour=8, minute=50)
    scheduler.add_job(utilities.email_main, 'cron', kwargs={'recurrence': 'weekly'}, day_of_week='mon', hour=8, minute=50)
        
    # # Start the scheduler
    scheduler.start()

    # Run the Flask app
    app.run(host='localhost', port=5000, debug=True)
    
    

