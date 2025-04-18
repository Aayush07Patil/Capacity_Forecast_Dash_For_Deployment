# This file is needed for Azure to identify the entry point
# Import the Flask app instance from your main application
from app import server as app

# Azure looks for an app variable to run the server
if __name__ == '__main__':
    app.run()