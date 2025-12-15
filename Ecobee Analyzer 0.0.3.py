import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import timedelta

# === CONFIGURATION ===
st.set_page_config(page_title="Ecobee Thermostat Analyzer", layout="wide")

# === HELPER FUNCTIONS ===
@st.cache_data
def load_data(file):
    try:
        # Load CSV (Ecobee headers usually start on row 5, so skiprows=5)
        # on_bad_lines='skip' helps if the file has trailing garbage
        df = pd.read_csv(file, skiprows=5, index_col=False, on_bad_lines='skip')
        df.columns = df.columns.str.strip()
        
        # --- SMART COLUMN REPAIR ---
        # Ecobee CSVs sometimes shift columns. We fix this by checking value ranges.
        
        # 1. Identify Pressure (Always ~100,000 Pa)
        candidates = [c for c in df.columns if 'Thermostat' in c]
        for col in candidates:
            # If mean is > 80,000, it's definitely Pressure
            if df[col].mean(skipna=True) > 80000 and df[col].mean(skipna=True) < 120000:
                df.rename(columns={col: 'Thermostat AirPressure (Corrected)'}, inplace=True)
                
        # 2. Identify VOC (Spikes > 100k) vs CO2 (Usually < 5000)
        remaining_candidates = [c for c in df.columns if 'Thermostat' in c and 'Pressure' not in c and 'Motion' not in c and 'Accuracy' not in c]
        
        potential_voc = None
        potential_co2 = None
        
        for col in remaining_candidates:
            col_max = df[col].max(skipna=True)
            col_mean = df[col].mean(skipna=True)
            
            # VOC signature: Can have huge spikes (like your 241k) or just high variance
            if col_max > 5000: 
                potential_voc = col
            # CO2 signature: Usually 400-3000, rarely above 5000
            elif col_mean > 300 and col_max < 10000:
                potential_co2 = col
                
        if potential_voc:
            df.rename(columns={potential_voc: 'Thermostat VOCppm'}, inplace=True)
        if potential_co2:
            df.rename(columns={potential_co2: 'Thermostat CO2ppm'}, inplace=True)
            
        # --- END REPAIR ---

        # Combine Date and Time
        if 'Date' in df.columns and 'Time' in df.columns:
            df = df.dropna(subset=['Date', 'Time'])
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
            if (motion[j] - motion[j-1]) > timedelta(minutes=10):
                starts.append(cur_start)
                ends.append(motion[j-1])
                cur_start = motion[j]
        
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
        yaxis=dict(tickmode='array', tickvals=[i + 0.4 for i in range(len(columns))], ticktext=columns, showgrid=False),
        xaxis_title="Time",
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
    kwh_price = st.number_input("Electricity Rate ($/kWh)", value=0.14, step=0.01, format="%.2f")
    hp_kw = st.number_input("Heat Pump Power (kW)", value=3.0, step=0.5)
    aux_kw = st.number_input("Aux Heat Power (kW)", value=5.0, step=0.5)
    T_crit = st.number_input("Aux Heat Critical Temp (°F)", value=40.0, step=1.0, help="Outdoor temp above which Aux Heat is considered unnecessary.")

if uploaded_file is not None:
    df = load_data(uploaded_file)
    
    if df is not None:
        # --- COLUMN DETECTION ---
        all_cols = df.columns.tolist()
        temp_cols = [c for c in all_cols if '(F)' in c or 'Temp' in c]
        motion_cols = [c for c in all_cols if 'Motion' in c or 'Occupancy' in c or c.endswith('2')]
        
        run_cols = [c for c in ['Cool Stage 1 (sec)', 'Heat Stage 1 (sec)', 'Aux Heat 1 (sec)', 'Fan (sec)'] if c in df.columns]

        # --- SIDEBAR FILTERS ---
        with st.sidebar:
            st.header("3. Graph Filters")
            selected_rooms = st.multiselect("Temperature Sensors", temp_cols, 
                                            default=[c for c in temp_cols if 'Thermostat' in c or 'Current Temp' in c])

        # === ENERGY REPORT (REVISED) ===
        st.header("⚡ Energy Efficiency Report")
        
        cool_min = df['Cool Stage 1 (sec)'].sum() / 60 if 'Cool Stage 1 (sec)' in df else 0
        heat_min = df['Heat Stage 1 (sec)'].sum() / 60 if 'Heat Stage 1 (sec)' in df else 0
        aux_min = df['Aux Heat 1 (sec)'].sum() / 60 if 'Aux Heat 1 (sec)' in df else 0
        total_heating_min = heat_min + aux_min
        total_aux_pct = (aux_min / total_heating_min * 100) if total_heating_min > 0 else 0

        # Calculate cost
        aux_cost = (aux_min / 60) * aux_kw * kwh_price
        hp_cost = (heat_min / 60) * hp_kw * kwh_price
        total_cost = aux_cost + hp_cost
        
        # Unnecessary Aux Heat (Above Critical Temperature)
        if 'Outdoor Temp (F)' in df.columns and total_heating_min > 0:
            df_warm = df[df['Outdoor Temp (F)'] >= T_crit]
            unnecessary_aux_min = df_warm['Aux Heat 1 (sec)'].sum() / 60
            warm_hp_min = df_warm['Heat Stage 1 (sec)'].sum() / 60
            warm_total_heat_min = unnecessary_aux_min + warm_hp_min
            unnecessary_aux_pct = (unnecessary_aux_min / warm_total_heat_min * 100) if warm_total_heat_min > 0 else 0
            
            if warm_total_heat_min > 30: 
                if unnecessary_aux_pct < 5: score, color, grade = 95, "green", "A+ Excellent"
                elif unnecessary_aux_pct < 15: score, color, grade = 85, "lightgreen", "A Good"
                elif unnecessary_aux_pct < 30: score, color, grade = 70, "orange", "B Fair"
                else: score, color, grade = 50, "red", "C Poor"
            else:
                score, color, grade = 80, "gray", "Not Enough Data"
        else:
            unnecessary_aux_pct = 0
            score, color, grade = 80, "gray", "Data Missing"
            
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Heating Time", f"{total_heating_min/60:.1f} hrs")
        c2.metric("Total Aux %", f"{total_aux_pct:.1f}%")
        c3.metric(f"Unnecessary Aux", f"{unnecessary_aux_pct:.1f}%", delta_color="inverse")
        c4.markdown(f"<div style='text-align:center'><b>Efficiency</b><br><span style='font-size:40px;color:{color}'>{score}</span><br>{grade}</div>", unsafe_allow_html=True)
        st.metric("Est. Cost", f"${total_cost:.2f}")

        st.subheader("Recommendations")
        tips = []
        if grade in ["C Poor", "B Fair"]:
            tips.append(f"High unnecessary Aux usage (>{T_crit}°F) → **Check your Ecobee threshold settings**.")
            tips.append(f"Action: Adjust `Aux Heat Max Outdoor Temperature` down to 35°F or lower.")
        if total_cost > 50: tips.append("High overall cost → Use aggressive schedule setbacks.")
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
                fig.add_trace(go.Scatter(x=heat_set.index, y=heat_set, name='Heat Setpoint', line=dict(color='red', dash='dash')))
            if 'Cool Set Temp (F)' in df.columns:
                cool_set = df['Cool Set Temp (F)'].resample('5min').mean()
                fig.add_trace(go.Scatter(x=cool_set.index, y=cool_set, name='Cool Setpoint', line=dict(color='blue', dash='dash')))

            fig.update_layout(hovermode="x unified", yaxis_title="Temperature (°F)")
            st.plotly_chart(fig, use_container_width=True)

        # === HVAC RUNTIME (CLEANED UP) ===
        st.header("⚙️ System Runtime")
        if run_cols:
            # 1. Prepare Data
            runtime_df = df[run_cols].copy() / 60  # Convert to minutes
            
            # 2. Rename columns for cleaner Legend
            rename_map = {
                'Cool Stage 1 (sec)': 'Cooling',
                'Heat Stage 1 (sec)': 'Heating (HP)',
                'Aux Heat 1 (sec)': 'Aux Heat',
                'Fan (sec)': 'Fan'
            }
            runtime_df = runtime_df.rename(columns=rename_map)
            
            # 3. Define Standard HVAC Colors
            color_map = {
                'Cooling': '#00B5F0',       # Blue
                'Heating (HP)': '#FFA600',  # Orange
                'Aux Heat': '#EF553B',      # Red (Warning)
                'Fan': '#00CC96'            # Green (Eco/Fan)
            }
            
            # 4. Plot with Color Map
            fig = px.bar(runtime_df, 
                         title="HVAC Runtime (Minutes per 5-min block)",
                         color_discrete_map=color_map)
                         
            fig.update_layout(hovermode="x unified", yaxis_title="Minutes On", legend_title="Equipment", barmode='stack')
            st.plotly_chart(fig, use_container_width=True)

        # === AIR QUALITY ANALYSIS (CORRECTED) ===
        st.header("💨 Air Quality Analysis")
        
        # 1. Identify the REAL Air Quality Column
        # We look for the column that has realistic air quality values (400 - 5000 range)
        # We explicitly IGNORE any column with values > 10,000 (which are Pressure/Errors)
        
        valid_aq_col = None
        
        # Candidates to check
        candidates = ['Thermostat CO2ppm', 'Thermostat VOCppm', 'Thermostat AirQuality']
        
        for col in candidates:
            if col in df.columns:
                col_mean = df[col].mean()
                # Realistic Air Quality is usually between 400 and 5000
                if 300 < col_mean < 8000:
                    valid_aq_col = col
                    break
        
        if valid_aq_col:
            st.info(f"Analyzing Air Quality using column: **{valid_aq_col}** (Values ~{int(df[valid_aq_col].mean())})")
            
            # Simple, clean line chart
            fig = px.line(df, x=df.index, y=valid_aq_col, 
                          title="Estimated Air Quality Levels (CO₂ Equivalent)",
                          markers=True)
            
            # Add color zones for context
            fig.add_hrect(y0=0, y1=1000, line_width=0, fillcolor="green", opacity=0.1, annotation_text="Excellent")
            fig.add_hrect(y0=1000, y1=2000, line_width=0, fillcolor="yellow", opacity=0.1, annotation_text="Fair")
            fig.add_hrect(y0=2000, y1=5000, line_width=0, fillcolor="red", opacity=0.1, annotation_text="Poor")
            
            fig.update_layout(
                yaxis_title="CO₂ Equivalent (ppm)",
                xaxis_title="Time",
                hovermode="x unified"
            )
            st.plotly_chart(fig, use_container_width=True)
            
            # Insight about the sensor
            st.caption("Note: Ecobee uses a VOC sensor to 'estimate' CO₂ levels. High values here actually represent high VOCs (odors, chemicals, stuffiness).")
            
        else:
            st.warning("Could not find valid Air Quality data (Values between 400-5000). The available columns seem to contain Error or Pressure data.")
            # Debugging view to show the user what we found
            st.write("Data detected in columns (for debugging):")
            st.write(df[candidates].describe())

        # === MOTION TIMELINE ===
        st.header("🏃 Motion Detection Timeline")
        if motion_cols:
            selected_motion = st.multiselect("Select sensors", motion_cols, default=motion_cols)
            if selected_motion:
                fig = create_motion_timeline(df, selected_motion)
                st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No motion columns found.")

        # === WEATHER & HUMIDITY ===
        st.header("🌐 Weather & Humidity")
        col1, col2 = st.columns(2)

        with col1:
            st.subheader("Outdoor Conditions")
            fig_out = go.Figure()
            if 'Outdoor Temp (F)' in df.columns:
                fig_out.add_trace(go.Scatter(x=df.index, y=df['Outdoor Temp (F)'], name='Outdoor Temp', line=dict(color='orange')))
            if 'Wind Speed (km/h)' in df.columns:
                wind = df['Wind Speed (km/h)'].resample('5min').mean()
                fig_out.add_trace(go.Scatter(x=wind.index, y=wind, name='Wind (km/h)', yaxis='y2', line=dict(color='gray', dash='dot')))
            
            fig_out.update_layout(height=400, yaxis2=dict(overlaying="y", side="right"))
            st.plotly_chart(fig_out, use_container_width=True)

        with col2:
            st.subheader("Indoor Humidity")
            hum_cols = [c for c in df.columns if any(x in c.lower() for x in ['humidity', '%rh'])]
            if hum_cols:
                sel_hum = st.multiselect("Select Sensors", hum_cols, default=hum_cols[:2])
                if sel_hum:
                    fig_hum = px.line(df[sel_hum].resample('5min').mean(), title="Relative Humidity")
                    fig_hum.update_layout(height=400)
                    st.plotly_chart(fig_hum, use_container_width=True)

        # === ROOM BALANCING ===
        st.divider()
        st.header("⚖️ Room Temperature Balancing")
        room_cols = [c for c in temp_cols if 'Outdoor' not in c and 'Set Temp' not in c and 'Zone' not in c]
        thermostat_col = next((c for c in room_cols if 'Thermostat' in c or 'Current Temp' in c), None)

        if thermostat_col and len(room_cols) > 1:
            avg_temps = df[room_cols].mean()
            offsets = avg_temps - avg_temps[thermostat_col]
            offsets = offsets.drop(thermostat_col, errors='ignore')
            
            score_df = pd.DataFrame({'Sensor': offsets.index, 'Offset': offsets.values})
            fig_bal = px.bar(score_df, x='Offset', y='Sensor', orientation='h', color='Offset', color_continuous_scale='RdBu_r', text_auto='.1f', title=f"Offset vs {thermostat_col}")
            fig_bal.add_vline(x=0, line_color="black")
            st.plotly_chart(fig_bal, use_container_width=True)

