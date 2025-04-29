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

# Layout - simplified without input fields
app.layout = html.Div([
    # No title or information display - clean interface for iframe embedding
    
    # Graph container with responsive layout
    html.Div(
        id="graph-container",
        style={
            "width": "100%", 
            "height": "100vh",  # Use viewport height
            "padding": "0px",   # Remove padding
            "margin": "0px"     # Remove margin
        }
    ),
    
    # Add interval component to trigger updates periodically
    dcc.Interval(
        id='interval-component',
        interval=1200000,  # in milliseconds (5 minutes)
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
        return html.Div("Waiting for flight data...", className="text-center p-5")
    
    try:
        # Convert f_date to datetime if it's a string
        if isinstance(f_date, str):
            f_date_dt = datetime.strptime(f_date.split('T')[0], "%Y-%m-%d").date()
        else:
            f_date_dt = f_date
            
        conn = get_connection()
        day_of_query = date.today()
        fifteen_days_before = day_of_query - timedelta(days=15)

        # Get prediction data
        pred_df = pd.read_sql("SELECT * FROM dbo.CapacityTransaction", conn)
        pred_df = pred_df[['ID', 'FltNo', 'FltDate', 'Origin', 'Destination', 'ReportWeight', 'ReportVolume']]

        # Get passenger data
        Pax_load = pd.read_sql("SELECT * FROM dbo.AirlinePAX WHERE FlightSchDept >= ?", 
                               conn, params=[fifteen_days_before])

        # Get flight schedule data
        query = """
            SELECT ID, FlightID, Source, Dest, FlightSchDept, CargoCapacity, UOM, 
                   AirCraftType, TailNo, FlightCapacityWeight, FlightCapacityVolume, 
                   DepartedWeight, AvailableWeight, AvailableVolume 
            FROM dbo.AirlineScheduleRouteForecast 
            WHERE Source = ? AND Dest = ? AND FlightID = ? AND AirCraftType NOT IN ('323', '32S', 'ATR') 
                  AND AirCraftType IS NOT NULL AND FlightSchDept >= ?
        """
        ASRF_df = pd.read_sql(query, conn, params=[origin, destination, f_no, fifteen_days_before])

        # Merge passenger data
        merge_cols = ['FlightID', 'Source', 'Dest', 'FlightSchDept']

        ASRF_df = ASRF_df.merge(
            Pax_load[merge_cols + ['ExpectedPAXCount', 'AVGBagPerPAX', 'Underload', 'ExpectedBaggage', 'CapacityWeightHold', 'CapacityVolumeHold']],
            on=merge_cols,
            how='left'
        )
        ASRF_df.dropna(subset=['ExpectedPAXCount'], inplace=True)

        # Calculate derived metrics
        ASRF_df['DepartedWeight'] = ASRF_df['DepartedWeight'].astype(float)
        ASRF_df['TOTAL CARGO'] = ASRF_df['DepartedWeight'].fillna(0) + ASRF_df['Underload'].fillna(0)
        ASRF_df['BaggageVolume'] = ASRF_df['ExpectedPAXCount'] * ASRF_df['AVGBagPerPAX'] * 0.067  # Average bag volume in cubic meters
        ASRF_df['ReportVolume'] = (
            ASRF_df['CapacityVolumeHold'].astype(float) - ASRF_df['BaggageVolume'].astype(float)
        ).round(0)

        # Process dates
        current_date = day_of_query  # fixed current date
        start_date = f_date_dt - timedelta(days=15)  # 15 days before f_date

        # Filter by flight number
        pred_df = pred_df[pred_df['FltNo'] == f_no]
        ASRF_df = ASRF_df[ASRF_df['FlightID'] == f_no]

        # Convert date columns
        pred_df['FltDate'] = pd.to_datetime(pred_df['FltDate']).dt.date
        ASRF_df['FlightSchDept'] = pd.to_datetime(ASRF_df['FlightSchDept']).dt.date

        # Filter prediction data: from current_date to f_date
        pred_filtered = pred_df[(pred_df['FltDate'] >= current_date) & (pred_df['FltDate'] <= f_date_dt)][
            ['FltNo', 'FltDate', 'Origin', 'Destination', 'ReportWeight', 'ReportVolume']
        ]
        pred_filtered = pred_filtered.rename(columns={
            'ReportWeight': 'Weight',
            'FltDate': 'Date',
            'ReportVolume': 'Volume'
        })
        pred_filtered['Data_From'] = 'Pred'

        # Filter actual data: from start_date to the day before current_date
        asrf_filtered = ASRF_df[(ASRF_df['FlightSchDept'] >= start_date) & (ASRF_df['FlightSchDept'] < current_date)][
            ['FlightID', 'Source', 'Dest', 'FlightSchDept', 'TOTAL CARGO', 'ReportVolume']
        ]
        asrf_filtered = asrf_filtered.rename(columns={
            'TOTAL CARGO': 'Weight',
            'FlightSchDept': 'Date',
            'FlightID': 'FltNo',
            'Source': 'Origin',
            'Dest': 'Destination',
            'ReportVolume': 'Volume'
        })
        asrf_filtered['Data_From'] = 'Actual'

        # Combine both datasets and sort by date
        combined_df = pd.concat([pred_filtered, asrf_filtered], ignore_index=True).sort_values(by='Date')

        # Group data by date and type
        daily_data = combined_df.groupby(['Date', 'Data_From'])[['Weight', 'Volume']].sum().unstack().sort_index()

        # Check if we have data to display
        if daily_data.empty:
            return html.Div("No data found for the specified parameters", className="text-center")

        # Create plotly figure with dual Y-axis
        fig = go.Figure()

        # === Weight (Primary Y-axis on the left) ===
        # Actual Weight (green)
        if 'Actual' in daily_data['Weight']:
            fig.add_trace(go.Scatter(
                x=daily_data.index,
                y=daily_data['Weight']['Actual'],
                mode='lines+markers',
                name='Actual Weight',
                line=dict(color='green'),
                yaxis='y1'
            ))

        # Predicted Weight (blue)
        if 'Pred' in daily_data['Weight']:
            fig.add_trace(go.Scatter(
                x=daily_data.index,
                y=daily_data['Weight']['Pred'],
                mode='lines+markers',
                name='Predicted Weight',
                line=dict(color='blue'),
                yaxis='y1'
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
                yaxis='y2'
            ))

        # Predicted Volume (orange)
        if 'Pred' in daily_data['Volume']:
            fig.add_trace(go.Scatter(
                x=daily_data.index,
                y=daily_data['Volume']['Pred'],
                mode='lines+markers',
                name='Predicted Volume',
                line=dict(color='orange'),
                yaxis='y2'
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

        # Update layout with dual Y-axis
        fig.update_layout(
            title=f'Cargo Trend and Forecast',
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
            shapes=[
                dict(
                    type='line',
                    x0=current_date,
                    x1=current_date,
                    y0=0,
                    y1=max_weight,
                    line=dict(color='black', width=2, dash='dot'),
                    xref='x',
                    yref='y'
                )
            ],
            annotations=[
                dict(
                    x=current_date,
                    y=max_weight,
                    xref="x",
                    yref="y",
                    text="Today",
                    showarrow=True,
                    arrowhead=2,
                    ax=0,
                    ay=-40
                )
            ],
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
        return html.Div(f"Error: {str(e)}", className="text-center text-danger")

if __name__ == '__main__':
    app.run_server(debug=False, host='0.0.0.0',port=int(os.environ.get('PORT',8050)))