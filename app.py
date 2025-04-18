import dash
from dash import dcc, html, Input, Output, State, callback
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
from datetime import datetime, timedelta
from flask import request, jsonify

# Try to import pyodbc, but provide alternative if it fails
try:
    import pyodbc
except ImportError:
    print("pyodbc not installed. Using sample data only.")
    pyodbc = None

# Initialize the Dash app
app = dash.Dash(__name__, title="Flight Capacity Dashboard", suppress_callback_exceptions=True)
server = app.server  # Expose Flask server to add custom routes

# Global variables to store the last received data
current_flight_data = {
    "flight_no": "",
    "flight_date": datetime.now().date().isoformat(),
    "flight_origin": "",
    "flight_destination": ""
}

# Create the layout (now without input fields)
app.layout = html.Div([
    
    html.Div([
        dcc.Loading(
            id="loading-graphs",
            type="circle",
            children=[
                html.Div([
                    html.H3("Flight Capacity Forecast", style={"textAlign": "center"}),
                    dcc.Graph(id="combined-graph")
                ], style={"width": "100%", "display": "inline-block"})
            ]
        )
    ], style={"marginTop": "20px"}),
    
    # Hidden div to store the flight data from the .NET application
    html.Div(id="flight-data-store", style={"display": "none"}),
    
    # Add interval component to trigger updates periodically
    dcc.Interval(
        id='interval-component',
        interval=180000,# in milliseconds (3 minutes)
        n_intervals=0
    )
])

# Function to connect to the database and get data
def get_flight_data(flight_no, flight_date, origin, destination):
    # For demonstration purposes, if DB connection fails, use sample data
    try:
        # For Azure SQL Database, Windows Authentication (Trusted_Connection) won't work
        # We need to use SQL Authentication with the proper driver
        try:
            # Method 1: Using ODBC Driver 17 (recommended for Azure SQL)
            conn = pyodbc.connect(
                'DRIVER={ODBC Driver 17 for SQL Server};'
                'SERVER=qidtestingindia.database.windows.net;'  # Remove the port from server name
                'DATABASE=rm-demo-erp-db;'
                'UID=rmdemodeploymentuser;'  # Replace with actual username
                'PWD=rm#demo#2515;'  # Replace with actual password
                'Encrypt=yes;'  # Required for Azure SQL
                'TrustServerCertificate=no;'
                'Connection Timeout=30;'
            )
        except Exception as e1:
            print(f"First connection attempt failed: {e1}")
            try:
                # Method 2: Using SQL Server driver as fallback
                conn = pyodbc.connect(
                    'DRIVER={SQL Server};'
                    'SERVER=qidtestingindia.database.windows.net;'  # Remove the port from server name
                    'DATABASE=rm-demo-erp-db;'
                    'UID=rmdemodeploymentuser;'  # Replace with actual username
                    'PWD=rm#demo#2515;'  # Replace with actual password
                    'Encrypt=yes;'  # Required for Azure SQL
                )
            except Exception as e2:
                print(f"Second connection attempt failed: {e2}")
                # If both connection methods fail, raise exception to use sample data
                raise Exception("Cannot connect to database")
        
        # Create a cursor
        cursor = conn.cursor()
        
        # Format the date for SQL query
        formatted_date = flight_date.strftime("%Y-%m-%d") if isinstance(flight_date, datetime) else flight_date
        
        # Construct and execute the query to get the next 15 instances
        query = """
        SELECT TOP 15 FltNo, FltDate, Origin, Destination, ReportWeight, ReportVolume
        FROM dbo.CapacityTransaction
        WHERE FltNo = ?
        AND Origin = ?
        AND Destination = ?
        AND FltDate >= ?
        ORDER BY FltDate
        """
        
        cursor.execute(query, (flight_no, origin, destination, formatted_date))
        
        # Fetch all results
        rows = cursor.fetchall()
        
        # Create DataFrame from results
        columns = [column[0] for column in cursor.description]
        df = pd.DataFrame.from_records(rows, columns=columns)
        
        # Close cursor and connection
        cursor.close()
        conn.close()
        
        return df
        
    except Exception as e:
        print(f"Database error: {e}")
        print("Using sample data instead...")
        
        # Generate sample data for demonstration
        # Convert flight_date to datetime object if it's a string
        if isinstance(flight_date, str):
            try:
                flight_date = datetime.strptime(flight_date.split('T')[0], "%Y-%m-%d").date()
            except ValueError:
                flight_date = datetime.now().date()
        
        sample_dates = [flight_date + timedelta(days=i) for i in range(15)]
        
        # Create sample data
        sample_data = {
            'FltNo': [flight_no] * 15,
            'FltDate': sample_dates,
            'Origin': [origin] * 15,
            'Destination': [destination] * 15,
            'ReportWeight': [round(1000 + i * 50 + (100 * (i % 3)), 2) for i in range(15)],  # Random-ish weights
            'ReportVolume': [round(500 + i * 25 + (50 * (i % 4)), 2) for i in range(15)]     # Random-ish volumes
        }
        
        return pd.DataFrame(sample_data)

# API endpoint to receive data from .NET application
@server.route('/update-data', methods=['POST'])
def update_data():
    global current_flight_data
    
    try:
        # Get the data from the request
        data = request.get_json()
        
        # Update the current flight data
        current_flight_data = {
            "flight_no": data.get("flight_no", ""),
            "flight_date": data.get("flight_date", datetime.now().date().isoformat()),
            "flight_origin": data.get("flight_origin", ""),
            "flight_destination": data.get("flight_destination", "")
        }
        
        print(f"Received data: {current_flight_data}")
        
        return jsonify({"status": "success", "message": "Data received successfully"}), 200
    
    except Exception as e:
        print(f"Error processing data: {e}")
        return jsonify({"status": "error", "message": str(e)}), 400

# Callback to update the graph based on stored flight data
@callback(
    Output("combined-graph", "figure"),
    [Input("interval-component", "n_intervals")]
)
def update_graphs(n_intervals):
    # Get the current flight data
    flight_no = current_flight_data["flight_no"]
    flight_date = current_flight_data["flight_date"]
    origin = current_flight_data["flight_origin"]
    destination = current_flight_data["flight_destination"]
    
    # Check if we have all required data
    if not all([flight_no, flight_date, origin, destination]):
        # Return empty figure if missing data
        empty_fig = go.Figure()
        empty_fig.update_layout(
            xaxis={"visible": False},
            yaxis={"visible": False},
            annotations=[{
                "text": "Waiting for flight data...",
                "showarrow": False,
                "font": {"size": 16}
            }]
        )
        
        return empty_fig
    
    # Get data from database
    df = get_flight_data(flight_no, flight_date, origin, destination)
    
    if df.empty:
        # Return empty figure if no data
        empty_fig = go.Figure()
        empty_fig.update_layout(
            xaxis={"visible": False},
            yaxis={"visible": False},
            annotations=[{
                "text": "No data found for the given parameters.",
                "showarrow": False,
                "font": {"size": 16}
            }]
        )
        
        return empty_fig
    
    # Convert FltDate to datetime if it's not already
    if not pd.api.types.is_datetime64_any_dtype(df['FltDate']):
        df['FltDate'] = pd.to_datetime(df['FltDate'])
    
    # Create a combined figure with dual y-axes
    combined_fig = go.Figure()
    
    # Add weight trace (left y-axis)
    combined_fig.add_trace(
        go.Scatter(
            x=df['FltDate'],
            y=df['ReportWeight'],
            name='Weight',
            mode='lines+markers',
            line=dict(color='blue')
        )
    )
    
    # Add volume trace (right y-axis)
    combined_fig.add_trace(
        go.Scatter(
            x=df['FltDate'],
            y=df['ReportVolume'],
            name='Volume',
            mode='lines+markers',
            line=dict(color='red'),
            yaxis='y2'  # Use the secondary y-axis
        )
    )
    
    # Update the layout for dual y-axes
    combined_fig.update_layout(
        xaxis=dict(
            title="Flight Date",
            tickformat="%d %b",  # Format the date as "DD MMM" (e.g., "07 JUN")
            tickmode="array",    # Force all ticks to be shown
            tickvals=df['FltDate'],  # Show ticks for all dates in the dataset
            ticktext=[date.strftime("%d %b").upper() for date in df['FltDate']]  # Format date labels
        ),
        yaxis=dict(
            title=dict(
                text="Weight (kg)",
                font=dict(color="black")
            ),
            tickfont=dict(color="black"),
            rangemode="tozero"  # Make y-axis start from zero
        ),
        yaxis2=dict(
            title=dict(
                text="Volume (cbm)",
                font=dict(color="black")
            ),
            tickfont=dict(color="black"),
            anchor="x",
            overlaying="y",
            side="right",
            rangemode="tozero"  # Make y2-axis start from zero
        ),
        legend=dict(x=0.02, y=0.98),
        hovermode="x unified"
    )
    
    return combined_fig

# For local development
if __name__ == '__main__':
    app.run_server(debug=False, host='0.0.0.0', port=8050)