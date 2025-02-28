# Standard library imports
import os
import sqlite3
import datetime
import smtplib
from typing import List, Optional
from email import encoders
from email.utils import formatdate
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.image import MIMEImage

# Local application imports
import common

# Global Logger setup
logger = common.setup_custom_logger("utilities")

# *** WEEKLY DATABASE CLEANUP ***
def delete_old_records() -> None:
    """ Function to delete old records from the database """
    # Note we could call the generic connect_to_database function from common.py 
    
    logger.info("Executing weekly DB Cleanup job...")

    try:
        conn = sqlite3.connect("RobotTracker.db")
        
        cursor = conn.cursor()
    
        # Build query to delete entries older than specified number of years
        query = f"DELETE FROM AgentUsage WHERE ACTUAL_DATE_TIME < DATE('now', '-{common.database_years} year')"
        
        # Execute query
        cursor.execute(query)
        
        # Get the number of deleted rows
        deleted_rows = cursor.rowcount
        
        if deleted_rows > 0:
            logger.info(f"Deleting {deleted_rows} rows due to max age limit reached ({common.database_years} years).")
        else:
            logger.info("No rows deleted. All Database records are within the allowed age limit.")
        
        # Commit the changes
        conn.commit() 
        
        # Close the database connection
        conn.close()
        
    except sqlite3.Error as e:
        logger.error(f"Error connecting to database: {e}")
        return

# *** EMAIL FUNCTIONALITY ***
def check_email_clash(query_parameters: list) -> bool:
    """ Check if the user has already subscribed to the email service.
        Only used when user tries to subscribe to the same service multiple times.
    """ 

    # Set SQL query
    sql_query = "SELECT * FROM Email WHERE TO_EMAIL = ? AND AGENTS = ? AND DAILY = ? AND WEEKLY = ?"
    
    # Query database 
    results = common.connect_to_database(sql_query, query_parameters)
    
    if not results:
        # No clashing entries found
        logger.info(f"No clashing entries found for {query_parameters[0]}")
        return False
    else:
        # Clashing entry found
        logger.info(f"{len(results)} clashing entrie(s) found for {query_parameters[0]}")
        return True


def email_opt_in(request, agents) -> None:
    """ Check if the user has opted in to receive email subscriptions """
    
    if 'email-opt-in' in request.form:
        logger.info("User has opted-in to email subscription")

        # Get to_email
        to_email = [request.form['email-address']]
        
        # Get preferred email recurrence
        if request.form['recurrence'] == "daily":
            recurrence = [1, 0]
        elif request.form['recurrence'] == "weekly":
            recurrence = [0, 1]
        
        # Convert list of agents into a list containing one continous string of agents separated by a comma
        agents_string = [",".join(agents)]
        
        # Combine into single list
        query_paramaters = to_email + agents_string + recurrence
        
        logger.info(f"User has requested {request.form['recurrence']} emails to following email address: {to_email}")
        logger.info(f"Checking database for clashing entries in Email table...")
        
        if check_email_clash(query_paramaters):
            logger.info(f"Clashing entry found for {to_email}.")
            logger.info("Database will not be updated.")
        else:
            logger.info("No clashes found - Updating database")
        
            # Set SQL Query
            sql_query = "INSERT INTO Email (TO_EMAIL, AGENTS, DAILY, WEEKLY) VALUES (?,?,?,?);"

            logger.info(f"Updating Email database with following parameters: {query_paramaters}")
            
            # Update the database
            common.connect_to_database(sql_query, query_paramaters, email=True)

def check_email_subs(recurrence: str):
    """ Check the database for email subscribers """
    
    logger.info(f"Checking database for {recurrence} email subscriptions.")
    
    if recurrence == "daily":
        # Set the column to query
        column = "DAILY"
        
        # Obtain the date of desired shift day (Today - one day)
        shift_dates = [datetime.date.today() - datetime.timedelta(days=1)]
    elif recurrence == "weekly":
        # Set the column to query
        column = "WEEKLY"
        
        # Get the current date
        today = datetime.date.today()
        
        # Subtract the number of weekdays from the current date to get the date of Monday of this week
        # Then subtract 7 days to get the date of Monday of the previous week
        start_date = today - datetime.timedelta(days=(today.weekday() + 7))
        
        # Last shift of week (Friday of the previous week)
        end_date = start_date + datetime.timedelta(days=4)
       
        shift_dates = [start_date, end_date]
    
    # Set SQL query
    sql_query_email = f"SELECT * FROM Email WHERE {column} = ?"
    
    # Pull email info from the databasel
    email_results = common.connect_to_database(sql_query_email, [int(1)])
    
    if email_results:
        return email_results, shift_dates
    else:
        return None, None

def email_build_graphs_csvs(row: tuple, shift_dates: list, recurrence: str):
    """ Function to query database for given subscriber """
    
    if row:
        # Extract the to email address and list of agents
        to_email_address, agents, = (
        row[0],
        row[1].split(',') # Split agent strings by commas and store in list
        )
        
        logger.info(f"Building graphs/CSV for {to_email_address}")

        # Create placeholders list
        placeholders = ', '.join(['?'] * len(agents))
        
        # Combine with agents list to form query_parameters list
        query_parameters = shift_dates + agents
        
        # Build our sql queries
        if recurrence == "daily":
            sql_query = f"SELECT * FROM AgentUsage WHERE SHIFT_DATE = ? AND NAME IN ({placeholders})"
        elif recurrence == "weekly":
            sql_query = f"SELECT * FROM AgentUsage WHERE ACTUAL_DATE_TIME BETWEEN ? AND ? AND NAME IN ({placeholders})"
    
        # Obtain results from database
        agents_results = common.connect_to_database(sql_query, query_parameters) 
        
        if not agents_results:
            logger.error("No data returned from database.")
            return
    
        # Build our CSV based on the agents_results list
        csv_file_path, filename, num_of_shifts = common.create_csv(agents_results, email=to_email_address)  
    
        # Build our graphs from the CSV
        chart_paths = common.create_graph(csv_file_path, agents, recurrence)
        logger.info(chart_paths)
        
        return to_email_address, chart_paths, csv_file_path, recurrence
    else:
        logger.error("No data returned from database.")

def send_email(to_email_address, chart_paths, csv_file_path, shift_dates, recurrence):
    """ Send an email to the specified email address with graphs embedded as images and CSV at attachment """
    
    # Logging
    logger.info(f"Building email for {to_email_address}")
    
    # Define the date range for the email subject
    if recurrence == "daily":
        date_range = str(shift_dates[0])
    elif recurrence == "weekly":
        date_range = str(shift_dates[0]) + ' --> ' + str(shift_dates[1])
    
    # Create a MIMEMultipart object so we can combine different types of content e.g. text, images, attachments
    msg = MIMEMultipart() 
    
    # Set the email headers
    msg["Subject"] = f"Robot Usage Tracker {recurrence.title()} Report: {date_range}"
    msg["To"] = to_email_address
    msg["From"] = "roryhandley96@gmail.com"
    msg['Cc'] = "roryhandley96@gmail.com"
    msg["Date"] = formatdate()

    # Define the main body as an HTML-Formatted string
    body = f"""
    <p> Hello {to_email_address.split(".")[0].title()}, </p>
    <p> You are receiving this email because you have signed up for {recurrence} reports from the Robot Usage Tracker. Please see the availablility for the specified agents below: </p>
    """
    
    # Embed the images in the email body using Content-ID (CID)
    # Note CIDs are required by email clients to interpret the embedded images
    for chart_path in chart_paths:
        # Generate a CID for each image. 
        # E.g. graph_2025-02-20.png becomes 2025-02-20
        cid = os.path.basename(chart_path).split('_')[1]
        cid = cid.removesuffix('.png')
        
        # Add the image reference to the HTML body
        body += '<h2><u>' + date_range + '</u></h2>'
        body += f'<img src="cid:{cid}"></img><hr><br>'
        
        # Attach the actual images
        if os.path.exists(chart_path):
            # Open the image in binary mode (since images are stored as raw binary)
            # Note img_file is a pointer to the file, not the actual binary data
            with open(chart_path, 'rb') as img_file:
                # Load the binary data into memory as a bytes object
                img_data = img_file.read()
                # Wrap the binary in an email-friendly format using a MIMEImage object
                img = MIMEImage(img_data, name=cid)
                # Add a Content-ID header to the MIMEImage object so the email client can locate the image --> replace the <img> tag with the actual image.
                # E.g. <img src="cid:20250220"></img> would be replaced with the actual image that has cid:2025-02-20
                img.add_header('Content-ID', f'<{cid}>')
                # Tell the email client how to handle the image with a Content-Disposition header. Inline means the client will display the image directly in the email. (as opposed to attachment)
                img.add_header('Content-Disposition', 'inline', filename=cid)
                # Attach the image to the email
                msg.attach(img)
    
    # Add closing comments to email body. 
    body += """
    <br><br>
    <p> If you would like to run custom queries, please visit the <a href='http://172.24.68.195:5000/'>Robot Usage Tracker Webpage.If you would like to be removed from the mailing list, please respond to this email.</a></p>
    """

    # Define an HTML message 
    html_part = MIMEText(body, "html")
    
    # Attach the HTML message to the MIME object
    msg.attach(html_part)

    # Add CSV file as attachment
    if os.path.exists(csv_file_path):
        
        # Open csv in binary mode to ensure the file is treated as raw binary data, not text
        with open(csv_file_path, 'rb') as csv_file:
            # Load the binary data into memory as a bytes object
            csv_data = csv_file.read()
            
            # MIMEBase is a general-purpose MIME type that can handle arbitrary files. 
            # Application means general files, octet-stream means the content is binary data.
            csv_part = MIMEBase('application', 'octet-stream')
            
            # Set the binary content of the CSV file as the payload (part we want to send) for this MIME part
            csv_part.set_payload(csv_data)
            
            # Encode the binary data into text so it can be safely transmitted over email. 
            encoders.encode_base64(csv_part)
            
            # Tell the email client to handle the file as an attachment. 
            csv_part.add_header('Content-Disposition', 'attachment', filename=f"{os.path.basename(csv_file_path)}")
        
            msg.attach(csv_part)

    try:
        with smtplib.SMTP("smtp-server") as smtp:
            # Logging
            logger.info(f"Attempting to send email to {to_email_address}")
            
            # Send the email
            smtp.send_message(msg)
            
            # Logging
            logger.info(f"Email sent to {to_email_address} successfully")
    except Exception as e:
        logger.error(f"Error sending email: {e}")
        
def email_main(recurrence: str):
    """ Main Function for email functionality """
    
    # Check for any email subscribers
    email_results, shift_dates = check_email_subs(recurrence)
    
    if email_results:
        # Logging
        logger.info(f"Found {len(email_results)} {recurrence} email subscriptions.")
        
        # Iterate through the email subscribers
        for row in email_results:
            
            # Build the graphs and CSV for the subscriber
            to_email_address, chart_paths, csv_file_path, recurrence = email_build_graphs_csvs(row, shift_dates, recurrence)

            # Send email to user(s)
            send_email(to_email_address, chart_paths, csv_file_path, shift_dates, recurrence)
    else: 
        # Logging
        logger.info(f"No {recurrence} email subscriptions found.")
