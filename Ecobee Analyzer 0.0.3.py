import streamlit as stimport streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import timedelta

# === CONFIGURATION ===
st.set_page_config(page_title="Ecobee Thermostat Analyzer", layout="wide")

# === HELPER FUNCTIONS ===
@st.cache_data
def load_data(file):
    """
    Loads and cleans data. Cached to prevent reloading on every interaction.
    """
    try:
        # Load CSV (Ecobee headers usually start on row 5, so skiprows=4)
        df = pd.read_csv(file, skiprows=4, index_col=False)
        df.columns = df.columns.str.strip()
        
        # Combine Date and Time and set as index
        if 'Date' in df.columns and 'Time' in df.columns:
            df['DateTime'] = pd.to_datetime(df['Date'] + ' ' + df['Time'])
            df = df.set_index('DateTime')
            return df
        else:
            return None
    except Exception as e:
        st.error(f"Error parsing file: {e}")
        return None

def create_motion_timeline(df, columns, title="Motion / Occupancy Timeline"):
    """
    Creates a Plotly Gantt-style chart showing duration of motion events.
    """
    fig = go.Figure()
    colors = px.colors.qualitative.Plotly
    
    for i, col in enumerate(columns):
        if col not in df.columns: continue
        # Filter for rows where motion/occupancy is detected (value is 1 or more)
        motion = df[df[col] >= 1].index
        if motion.empty: continue

        # Logic to group adjacent 'motion' points into continuous blocks
        starts = []
        ends = []
        cur_start = motion[0]

        for j in range(1, len(motion)):
            # Check for a gap longer than 10 minutes (Ecobee reports every 5 min)
            if (motion[j] - motion[j-1]) > timedelta(minutes=10):
                starts.append(cur_start)
                ends.append(motion[j-1])
                cur_start = motion[j]
        
        # Add the final block
        starts.append(cur_start)
        ends.append(motion[-1])

        for s, e in zip(starts, ends):
            duration_minutes = round((e - s).total_seconds() / 60)
            
            fig.add_trace(go.Scatter(
                x=[s, e, e, s, s], 
                y=[i+0.8, i+0.8, i, i, i+0.8],
                fill='toself',
                fillcolor=colors[i % len(colors)],
                line_color='rgba(255,255,255,0)',
                name=col,
                showlegend=(s == starts[0]),
                hoveron='fills',
                customdata=[[s.strftime("%H:%M"), e.strftime("%H:%M"), duration_minutes]],
                hovertemplate=f"<b>{col} Active</b><br>Start: %{{customdata[0]}}<br>End: %{{customdata[1]}}<br>Duration: %{{customdata[2]}} min<extra></extra>"
            ))

    fig.update_layout(
        title=title,
        height=max(300, len(columns) * 90),
        yaxis=dict(
            tickmode='array',
            tickvals=[i + 0.4 for i in range(len(columns))], 
            ticktext=columns,
            showgrid=False
        ),
        xaxis_title="Time",
        legend_title="Sensors",
        margin=dict(t=60, b=20),
        hoverlabel=dict(bgcolor="black", font_size=14, font_color="white")
    )
    return fig

# === MAIN APP ===
st.title("🏡 Ecobee Thermostat — Pro Interactive Analyzer")

# --- SIDEBAR ---
with st.sidebar:
    st.header("1. Upload Data")
    uploaded_file = st.file_uploader("Upload Ecobee CSV", type="csv")
    
    st.header("2. Energy Settings")
    kwh_price = st.number_input("Electricity Rate ($/kWh)", value=0.14, step=0.01, format="%.2f", help="Your cost per kWh")
    hp_kw = st.number_input("Heat Pump Power (kW)", value=3.0, step=0.5, help="Heat pump power consumption")
    aux_kw = st.number_input("Aux Heat Power (kW)", value=5.0, step=0.5, help="Auxiliary/Emergency heat power consumption")

if uploaded_file is not None:
    df = load_data(uploaded_file)
    
    if df is not None:
        # --- COLUMN DETECTION ---
        all_cols = df.columns.tolist()
        temp_cols = [c for c in all_cols if '(F)' in c]
        motion_cols = [c for c in all_cols if 'Motion' in c or 'Occupancy' in c or c.endswith('2')]
        aq_cols = [c for c in ['Thermostat CO2ppm', 'Thermostat VOCppm', 'Thermostat AirQuality'] if c in df.columns]
        run_cols = [c for c in ['Cool Stage 1 (sec)', 'Heat Stage 1 (sec)', 'Aux Heat 1 (sec)', 'Fan (sec)'] if c in df.columns]

        # --- SIDEBAR FILTERS ---
        with st.sidebar:
            st.header("3. Graph Filters")
            selected_rooms = st.multiselect("Temperature Sensors", temp_cols, 
                                            default=[c for c in temp_cols if 'Thermostat' in c or 'Average' in c])

        # === ENERGY REPORT ===
        st.header("⚡ Energy Efficiency Report")
        
        cool_min = df['Cool Stage 1 (sec)'].sum() / 60 if 'Cool Stage 1 (sec)' in df else 0
        heat_min = df['Heat Stage 1 (sec)'].sum() / 60 if 'Heat Stage 1 (sec)' in df else 0
        aux_min = df['Aux Heat 1 (sec)'].sum() / 60 if 'Aux Heat 1 (sec)' in df else 0
        total_heating_min = heat_min + aux_min
        aux_pct = (aux_min / total_heating_min * 100) if total_heating_min > 0 else 0

        aux_cost = (aux_min / 60) * aux_kw * kwh_price
        hp_cost = (heat_min / 60) * hp_kw * kwh_price
        total_cost = aux_cost + hp_cost

        # Scoring Logic
        if total_heating_min > 60:
            if aux_pct < 5: score, color, grade = 95, "green", "A+ Excellent"
            elif aux_pct < 15: score, color, grade = 85, "lightgreen", "A Good"
            elif aux_pct < 30: score, color, grade = 70, "orange", "B Fair"
            else: score, color, grade = 50, "red", "C Poor"
        else:
            score, color, grade = 80, "gray", "Not Enough Data"

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Heating Time", f"{total_heating_min/60:.1f} hrs")
        c2.metric("Aux Heat %", f"{aux_pct:.1f}%", delta_color="inverse")
        c3.metric("Est. Cost", f"${total_cost:.2f}")
        c4.markdown(f"<div style='text-align:center'><b>Score</b><br><span style='font-size:40px;color:{color}'>{score}</span><br>{grade}</div>", unsafe_allow_html=True)

        st.subheader("Recommendations")
        tips = []
        if aux_pct > 30: tips.append("High aux heat → Consider cold-climate heat pump or insulation upgrades")
        elif aux_pct > 15: tips.append("Raise Aux Heat lockout temp in Ecobee settings")
        if total_cost > 50: tips.append("High cost → Use schedule setbacks when away")
        if not tips: tips.append("Your system is running efficiently!")
        for t in tips: st.success(t)

        st.divider()

        # === TEMPERATURE ===
        st.header("🌡️ Temperature Profiles")
        if selected_rooms:
            plot_df = df[selected_rooms].resample('5min').mean()
            fig = px.line(plot_df, render_mode='webgl')
            
            if 'Heat Set Temp (F)' in df.columns:
                heat_set = df['Heat Set Temp (F)'].resample('5min').mean()
                fig.add_trace(go.Scatter(x=heat_set.index, y=heat_set, name='Heat Setpoint', 
                                         line=dict(color='red', dash='dash')))
            if 'Cool Set Temp (F)' in df.columns:
                cool_set = df['Cool Set Temp (F)'].resample('5min').mean()
                fig.add_trace(go.Scatter(x=cool_set.index, y=cool_set, name='Cool Setpoint', 
                                         line=dict(color='blue', dash='dash')))

            fig.update_layout(hovermode="x unified", yaxis_title="Temperature (°F)", legend_title="Legend")
            st.plotly_chart(fig, use_container_width=True)

        # === HVAC RUNTIME ===
        st.header("⚙️ System Runtime")
        if run_cols:
            fig = px.area(df[run_cols].copy() / 60, title="HVAC Runtime (Minutes per 5-min block)",
                          color_discrete_sequence=['#FF97FF', '#FF6692', '#EF553B', '#636EFA'])
            fig.update_layout(hovermode="x unified", yaxis_title="Minutes On", legend_title="Equipment")
            st.plotly_chart(fig, use_container_width=True)

        # === AIR QUALITY ===
        st.header("💨 Air Quality & CO₂")
        if aq_cols:
            fig = px.line(df[aq_cols], title="Air Quality Trends")
            fig.update_layout(hovermode="x unified", yaxis_title="Level (ppb / ppm)", legend_title="Reading")
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No air quality data found (available only on Ecobee Premium models).")

        # === MOTION TIMELINE ===
        st.header("🏃 Motion Detection Timeline")
        if motion_cols:
            selected_motion = st.multiselect("Select sensors", motion_cols, default=motion_cols)
            if selected_motion:
                fig = create_motion_timeline(df, selected_motion)
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("No motion sensors selected.")
        else:
            st.info("No columns for motion or occupancy detected.")

        # === WEATHER & HUMIDITY ===
        st.header("🌐 Weather & Humidity")
        col1, col2 = st.columns(2)

        with col1:
            st.subheader("Outdoor Conditions")
            fig_out = go.Figure()
            has_outdoor = False
            if 'Outdoor Temp (F)' in df.columns:
                fig_out.add_trace(go.Scatter(x=df.index, y=df['Outdoor Temp (F)'], name='Outdoor Temp (°F)', line=dict(color='orange', width=2.5), yaxis='y1'))
                has_outdoor = True
            if 'Wind Speed (km/h)' in df.columns:
                fig_out.add_trace(go.Scatter(x=df.index, y=df['Wind Speed (km/h)'], name='Wind Speed (km/h)', yaxis='y2', line=dict(color='gray', width=2, dash='dot')))
                has_outdoor = True
            
            if has_outdoor:
                fig_out.update_layout(title="Outdoor Weather", hovermode="x unified", height=420, yaxis=dict(title="Temp"), yaxis2=dict(title="Wind", overlaying="y", side="right"))
                st.plotly_chart(fig_out, use_container_width=True)
            else:
                st.info("No outdoor weather data found.")

        with col2:
            st.subheader("Indoor Humidity")
            humidity_cols = [col for col in df.columns if any(x in col.lower() for x in ['humidity', '%rh'])]
            if humidity_cols:
                default_hum = humidity_cols if len(humidity_cols) <= 3 else humidity_cols[:2]
                selected_hum = st.multiselect("Select Humidity Sensors", options=humidity_cols, default=default_hum, key="humidity_select")
                if selected_hum:
                    fig_hum = px.line(df[selected_hum].resample('5min').mean(), title="Indoor Relative Humidity", color_discrete_sequence=['#636EFA', '#00CC96', '#EF553B'])
                    fig_hum.update_layout(height=420)
                    st.plotly_chart(fig_hum, use_container_width=True)
            else:
                st.info("No indoor humidity data found.")

        # ==========================================
        # === NEW SECTION: ROOM BALANCING SCORES ===
        # ==========================================
        st.divider()
        st.header("⚖️ Room Temperature Balancing")
        
        # Identify Room Sensors (exclude Outdoor, Setpoints, Min/Max columns)
        room_cols = [c for c in temp_cols if 'Outdoor' not in c and 'Set Temp' not in c and 'Zone' not in c]
        
        # Try to identify the Main Thermostat to use as a baseline
        # Ecobee usually names it 'Thermostat Temperature (F)'
        thermostat_col = next((c for c in room_cols if 'Thermostat' in c), None)

        if thermostat_col and len(room_cols) > 1:
            st.write(f"Comparing all rooms against **{thermostat_col}** (Baseline).")
            
            # 1. Calculate Average Temperature for entire period
            avg_temps = df[room_cols].mean()
            baseline_temp = avg_temps[thermostat_col]
            
            # 2. Calculate Offsets (Room - Thermostat)
            offsets = avg_temps - baseline_temp
            offsets = offsets.drop(thermostat_col) # Remove the baseline itself from the chart
            
            # 3. Create DataFrame for Plotting
            score_df = pd.DataFrame({'Sensor': offsets.index, 'Offset': offsets.values})
            
            # 4. Visualization: Diverging Bar Chart
            fig_bal = px.bar(score_df, x='Offset', y='Sensor', orientation='h',
                             title="Average Temperature Offset vs Main Thermostat",
                             color='Offset',
                             color_continuous_scale='RdBu_r', # Red=Hot, Blue=Cold
                             text_auto='.1f')
            
            fig_bal.update_layout(xaxis_title="Offset (°F) [Negative = Cooler, Positive = Warmer]", 
                                  yaxis_title=None)
            fig_bal.add_vline(x=0, line_dash="solid", line_color="black")
            st.plotly_chart(fig_bal, use_container_width=True)
            
            # 5. Recommendations
            col_rec1, col_rec2 = st.columns(2)
            
            with col_rec1:
                st.subheader("🔥 Rooms Running Hot")
                hot_rooms = score_df[score_df['Offset'] > 1.0] # Threshold: 1 degree warmer
                if not hot_rooms.empty:
                    for idx, row in hot_rooms.iterrows():
                        st.warning(f"**{row['Sensor']}** (+{row['Offset']:.1f}°F)")
                    st.markdown("👉 **Action:** Partially close vents in these rooms to force air to cooler rooms.")
                else:
                    st.success("No rooms are significantly overheating.")

            with col_rec2:
                st.subheader("❄️ Rooms Running Cold")
                cold_rooms = score_df[score_df['Offset'] < -1.0] # Threshold: 1 degree cooler
                if not cold_rooms.empty:
                    for idx, row in cold_rooms.iterrows():
                        st.info(f"**{row['Sensor']}** ({row['Offset']:.1f}°F)")
                    st.markdown("👉 **Action:** Ensure vents are fully open. Check windows for drafts.")
                else:
                    st.success("No rooms are significantly overcooling.")
                    
        elif len(room_cols) <= 1:
            st.warning("Not enough sensors found to calculate balancing scores. You need at least one remote SmartSensor.")
        else:
            st.error("Could not identify the main 'Thermostat Temperature' column to use as a baseline.")

        st.success("Your Ecobee Pro Analyzer is complete — enjoy your smart home insights!")

    else:
        st.error("Could not process the uploaded CSV file. Please check file format.")
else:
    st.info("Upload your Ecobee CSV data export to begin the analysis.")
    st.info("Upload your Ecobee CSV data export to begin the analysis.")
