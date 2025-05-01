import pyodbc
import pandas as pd
from datetime import date, timedelta, datetime
import plotly.graph_objects as go
from dash import Dash, html, dcc, Input, Output, State, callback
import dash_bootstrap_components as dbc
import dash
import os
from flask import request, jsonify

# Dash app setup
app = dash.Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP], suppress_callback_exceptions=True)
server = app.server  # Expose Flask server to add custom routes

# Global variables to store the last received data
current_flight_data = {
    "flight_no": "",
    "flight_date": datetime.now().date().isoformat(),
    "flight_origin": "",
    "flight_destination": ""
}

# Database connection setup with environment variables
def get_connection():
    try:
        # Get database connection details from environment variables
        server = os.environ.get('DB_SERVER', '')
        database = os.environ.get('DB_NAME', '')
        username = os.environ.get('DB_USER', '')
        password = os.environ.get('DB_PASSWORD', '')
        
        # Check if we have all the required connection details
        if not all([server, database, username, password]):
            print("Missing database connection details. Using sample data instead...")
            raise Exception("Missing database connection details")

        
        conn_str = (
            'DRIVER={ODBC Driver 17 for SQL Server};'
            f'SERVER={server};'
            f'DATABASE={database};'
            f'UID={username};'
            f'PWD={password};'
            'Encrypt=yes;'
            'TrustServerCertificate=no;'
            'Connection Timeout=30;'
        )
        return pyodbc.connect(conn_str)
    except Exception as e:
        print(f"Database connection error: {e}")
        raise

# Layout - simplified without input fields with loading circle added
app.layout = html.Div([
    # Graph container with responsive layout and loading overlay
    dcc.Loading(
        id="loading-graph",
        type="circle",
        color="#119DFF",
        children=[
            html.Div(
                id="graph-container",
                style={
                    "width": "100%", 
                    "height": "100vh",  # Use viewport height
                    "padding": "0px",   # Remove padding
                    "margin": "0px"     # Remove margin
                }
            )
        ]
    ),
    
    # Add interval component to trigger updates periodically
    dcc.Interval(
        id='interval-component',
        interval=1200000,  # in milliseconds (20 minutes)
        n_intervals=0
    )
], style={
    "width": "100%",
    "height": "100vh",  # Use full viewport height
    "padding": "0px",   # Remove padding
    "margin": "0px",    # Remove margin
    "overflow": "hidden" # Prevent scrollbars
})

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

# New API endpoint to reset data
@server.route('/reset-data', methods=['POST'])
def reset_data():
    global current_flight_data
    
    try:
        # Reset the current flight data to empty values
        current_flight_data = {
            "flight_no": "",
            "flight_date": datetime.now().date().isoformat(),
            "flight_origin": "",
            "flight_destination": ""
        }
        
        print("Dashboard data reset successfully")
        
        return jsonify({"status": "success", "message": "Data reset successfully"}), 200
    
    except Exception as e:
        print(f"Error resetting data: {e}")
        return jsonify({"status": "error", "message": str(e)}), 400

# Callback to update the graph based on stored flight data
@callback(
    Output("graph-container", "children"),
    [Input("interval-component", "n_intervals")]
)
def update_graph(n_intervals):
    # Get the current flight data
    f_no = current_flight_data["flight_no"]
    f_date = current_flight_data["flight_date"]
    origin = current_flight_data["flight_origin"]
    destination = current_flight_data["flight_destination"]
    
    # Check if we have all required data
    if not all([f_no, f_date, origin, destination]):
        # Return empty message if missing data
        return html.Div("Waiting for flight data...", 
                        style={
                            "display": "flex",
                            "justifyContent": "center",
                            "alignItems": "center",
                            "height": "100%",
                            "fontSize": "16px"
                        })
    
    try:
        # Convert f_date to datetime if it's a string
        if isinstance(f_date, str):
            f_date_dt = datetime.strptime(f_date.split('T')[0], "%Y-%m-%d").date()
        else:
            f_date_dt = f_date
            
        conn = get_connection()
        current_date = date.today()
        fifteen_days_before = f_date_dt - timedelta(days=15)  # 15 days before target flight date
        date_to_start = f_date_dt + timedelta(days=1)

        # Get data from CapacityTransaction table with appropriate filters
        query = """
            SELECT ID, FltNo, FltDate, Origin, Destination, ReportWeight, ReportVolume, OBW
            FROM dbo.CapacityTransaction
            WHERE FltNo = ? AND Origin = ? AND Destination = ? 
                  AND FltDate >= ? AND FltDate <= ?
        """
        capacity_df = pd.read_sql(query, conn, params=[f_no, origin, destination, fifteen_days_before, date_to_start])
        
        # Convert FltDate to datetime
        capacity_df['FltDate'] = pd.to_datetime(capacity_df['FltDate']).dt.date
        
        # Create a new Data_From column
        capacity_df['Data_From'] = capacity_df['FltDate'].apply(
            lambda x: 'Actual' if x < current_date else 'Pred'
        )
        
        # Rename columns for consistency with your existing code
        capacity_df = capacity_df.rename(columns={
            'ReportWeight': 'Weight',
            'ReportVolume': 'Volume',
            'FltDate': 'Date'
        })
        
        # Group data by date and type
        daily_data = capacity_df.groupby(['Date', 'Data_From'])[['Weight', 'Volume']].sum().unstack().sort_index()

        # Check if we have data to display
        if daily_data.empty:
            return html.Div("No data found for the specified parameters", 
                            style={
                                "display": "flex",
                                "justifyContent": "center",
                                "alignItems": "center",
                                "height": "100%",
                                "fontSize": "16px"
                            })

        # Create plotly figure with dual Y-axis
        fig = go.Figure()
        
        # Create a date range to ensure all dates are shown in the x-axis
        # This ensures May 8 is included even if there's no data for it
        all_dates = pd.date_range(start=fifteen_days_before, end=f_date_dt).date

        # === Weight (Primary Y-axis on the left) ===
        # Actual Weight (green)
        if 'Actual' in daily_data['Weight']:
            fig.add_trace(go.Scatter(
                x=daily_data.index,
                y=daily_data['Weight']['Actual'],
                mode='lines+markers',
                name='Actual Wt',
                line=dict(color='green'),
                yaxis='y1',
                hovertemplate = 'Date: %{x}<br>Weight: %{y} Kg<extra></extra>'
            ))

        # Predicted Weight (blue)
        if 'Pred' in daily_data['Weight']:
            fig.add_trace(go.Scatter(
                x=daily_data.index,
                y=daily_data['Weight']['Pred'],
                mode='lines+markers',
                name='Pred Wt',
                line=dict(color='blue'),
                yaxis='y1',
                hovertemplate = 'Date: %{x}<br>Weight: %{y} Kg<extra></extra>'
            ))

        # Transition line for Weight if both actual and predicted data exist
        if 'Actual' in daily_data['Weight'] and 'Pred' in daily_data['Weight']:
            actual_series = daily_data['Weight']['Actual'].dropna()
            pred_series = daily_data['Weight']['Pred'].dropna()
            if not actual_series.empty and not pred_series.empty:
                fig.add_trace(go.Scatter(
                    x=[actual_series.index[-1], pred_series.index[0]],
                    y=[actual_series.iloc[-1], pred_series.iloc[0]],
                    mode='lines',
                    name='Weight Transition',
                    line=dict(color='blue', dash='dot'),
                    showlegend=False,
                    yaxis='y1'
                ))

        # === Volume (Secondary Y-axis on the right) ===
        # Actual Volume (red)
        if 'Actual' in daily_data['Volume']:
            fig.add_trace(go.Scatter(
                x=daily_data.index,
                y=daily_data['Volume']['Actual'],
                mode='lines+markers',
                name='Actual Volume',
                line=dict(color='red'),
                yaxis='y2',
                hovertemplate = 'Date: %{x}<br>Volume: %{y} Kg<extra></extra>'
            ))

        # Predicted Volume (orange)
        if 'Pred' in daily_data['Volume']:
            fig.add_trace(go.Scatter(
                x=daily_data.index,
                y=daily_data['Volume']['Pred'],
                mode='lines+markers',
                name='Predicted Volume',
                line=dict(color='orange'),
                yaxis='y2',
                hovertemplate = 'Date: %{x}<br>Volume: %{y} Kg<extra></extra>'
            ))

        # Transition line for Volume if both actual and predicted data exist
        if 'Actual' in daily_data['Volume'] and 'Pred' in daily_data['Volume']:
            actual_vol_series = daily_data['Volume']['Actual'].dropna()
            pred_vol_series = daily_data['Volume']['Pred'].dropna()
            if not actual_vol_series.empty and not pred_vol_series.empty:
                fig.add_trace(go.Scatter(
                    x=[actual_vol_series.index[-1], pred_vol_series.index[0]],
                    y=[actual_vol_series.iloc[-1], pred_vol_series.iloc[0]],
                    mode='lines',
                    name='Volume Transition',
                    line=dict(color='orange', dash='dot'),
                    showlegend=False,
                    yaxis='y2'
                ))

        # Calculate the max y-value for the vertical line
        max_weight = 0
        if 'Actual' in daily_data['Weight'] and not daily_data['Weight']['Actual'].empty:
            max_weight = max(max_weight, daily_data['Weight']['Actual'].max())
        if 'Pred' in daily_data['Weight'] and not daily_data['Weight']['Pred'].empty:
            max_weight = max(max_weight, daily_data['Weight']['Pred'].max())
        max_weight = max_weight + 2000  # Add padding

        # Initialize empty lists for shapes and annotations
        shapes = []
        annotations = []

        # Only add the Today line and annotation if current_date is within our date range
        if fifteen_days_before <= current_date <= f_date_dt:
            shapes.append(dict(
                type='line',
                x0=current_date,
                x1=current_date,
                y0=0,
                y1=max_weight,
                line=dict(color='black', width=2, dash='dot'),
                xref='x',
                yref='y'
            ))
            
            annotations.append(dict(
                x=current_date,
                y=max_weight,
                xref="x",
                yref="y",
                text="Today",
                showarrow=True,
                arrowhead=2,
                ax=0,
                ay=-40
            ))

        # Update layout with dual Y-axis
        fig.update_layout(
            title=dict(
                text='Cargo trend and Forecast',
                x=0.5,  # Center title
                y=0.98  # Position near top
            ),
            xaxis_title='Date',
            yaxis=dict(
                title='Weight (kg)',
                rangemode='tozero',
            ),
            yaxis2=dict(
                title='Volume (m³)',
                overlaying='y',
                side='right',
                rangemode='tozero'
            ),
            xaxis=dict(
                tickangle=45,
                tickmode='linear',
                dtick='D1',
                tickformat='%d %b',
                # Explicitly set the range to include all dates including flight date
                range=[fifteen_days_before, f_date_dt]
            ),
            legend=dict(
                x=1.05,        # Just outside the right side
                y=1,           # Align to top
                xanchor='left',
                yanchor='top',
                bgcolor='rgba(255,255,255,0.8)',  # Semi-transparent background
                bordercolor='black',
                borderwidth=1
            ),
            template='plotly_white',
            shapes=shapes,  # Use the conditionally created shapes list
            annotations=annotations,  # Use the conditionally created annotations list
            margin=dict(l=50, r=100, t=60, b=50),  # Reduced top margin
            autosize=True,  # Enable autosize for responsiveness
            height=None,    # Let height be determined by container
        )

        return dcc.Graph(
            figure=fig,
            style={
                'height': '100%',  # Take full height of parent container
                'width': '100%'    # Take full width of parent container
            },
            config={
                'responsive': True,  # Enable responsiveness
                'displayModeBar': False  # Hide the mode bar for cleaner appearance
            }
        )
    
    except Exception as e:
        return html.Div(f"Error: {str(e)}", 
                        style={
                            "display": "flex",
                            "justifyContent": "center",
                            "alignItems": "center",
                            "height": "100%",
                            "fontSize": "16px",
                            "color": "red"
                        })

if __name__ == '__main__':
    app.run_server(debug=False, host='0.0.0.0',port=int(os.environ.get('PORT',8050)))