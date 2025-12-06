import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import altair as alt

# --- THEME CONSTANTS ---
COLOR_BG = "#0e1117"
COLOR_ACCENT = "#3B8ED0"
COLOR_DANGER = "#FF4B4B"
COLOR_SUCCESS = "#00CC96"
COLOR_WARN = "#FFA500"

class LogisticsDashboard:
    def __init__(self):
        st.set_page_config(page_title="DevCode Command", page_icon="✈️", layout="wide")
        self._inject_css()
        
        self._render_header()
        
        # 1. Top Row: KPIs
        self.kpi_container = st.empty()
        
        # 2. Middle Row: Charts & Console
        col_charts, col_console = st.columns([1.5, 1])
        with col_charts:
            st.caption("Hourly Cost Overview")
            self.charts_container = st.empty()
        with col_console:
            st.caption("SYSTEM LOGS")
            self.logs_container = st.empty()
            
        st.divider()
        
        # 3. Bottom Row: Airport Matrix
        st.caption("NETWORK STOCK LEVELS")
        self.table_container = st.empty()

    def _inject_css(self):
        st.markdown(f"""
        <style>
            .stApp {{ background-color: {COLOR_BG}; }}
            
            /* Console Container */
            .console-wrapper {{
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 11px;
                background-color: #111;
                color: #e0e0e0;
                padding: 10px;
                height: 400px; 
                overflow-y: auto;
                border: 1px solid #333;
                border-radius: 5px;
                display: block;
            }}
            
            /* Individual Log Entry */
            .log-entry {{
                border-bottom: 1px solid #222;
                padding: 6px 0;
                display: block;
            }}
            
            .log-header {{ 
                color: {COLOR_ACCENT}; 
                font-weight: bold; 
                display: flex; 
                justify-content: space-between;
            }}
            
            .log-body {{ margin-left: 10px; margin-top: 4px; }}
            .flight-row {{ margin-bottom: 3px; border-left: 2px solid #444; padding-left: 8px; }}
            .log-warn {{ color: {COLOR_WARN}; }}
            .log-err {{ color: {COLOR_DANGER}; font-weight: bold; }}
            .dim {{ color: #777; }}
            .highlight {{ color: #fff; }}
        </style>
        """, unsafe_allow_html=True)

    def _render_header(self):
        st.markdown(f"<h2 style='text-align: center; color: {COLOR_ACCENT}; margin: 0px;'>DEVCODE LOGISTICS</h2>", unsafe_allow_html=True)

    def render_controls(self, is_running):
        if not is_running:
            _, c, _ = st.columns([1, 2, 1])
            with c:
                return st.button("▶ INITIALIZE SIMULATION", type="primary", width="stretch")
        return False

    def render_update(self, state_data):
        # 1. KPIs
        with self.kpi_container.container():
            col1, col2, col3, col4 = st.columns(4)

            with col1:
                st.metric("Simulation Time", f"Day {state_data['day']} : {state_data['hour']:02d}")
                st.metric("Total Cost", f"${state_data['total_cost']:,.0f}")

            with col2:
                st.metric("Penalties", f"{state_data['penalty_count']}", delta_color="inverse")

            with col3:
                st.metric("Hub First Stock", f"{state_data['hub_stock']['FIRST']:,}")
                st.metric("Hub Biz Stock", f"{state_data['hub_stock']['BUSINESS']:,}")

            with col4:
                st.metric("Hub PE Stock", f"{state_data['hub_stock']['PREMIUM_ECONOMY']:,}")
                st.metric("Hub Eco Stock", f"{state_data['hub_stock']['ECONOMY']:,}")

        # 2. Chart
        with self.charts_container.container():
            if not state_data['cost_history'].empty:
                chart = alt.Chart(state_data['cost_history']).mark_area(
                    line={'color': COLOR_ACCENT},
                    color=alt.Gradient(
                        gradient='linear',
                        stops=[alt.GradientStop(color=COLOR_ACCENT, offset=0),
                               alt.GradientStop(color=COLOR_BG, offset=1)],
                        x1=1, x2=1, y1=1, y2=0
                    )
                ).encode(
                    x=alt.X('time:Q', title='Hour'),
                    y=alt.Y('cost:Q', title='Cost'),
                    tooltip=['time', 'cost']
                ).properties(height=400)
                st.altair_chart(chart, theme="streamlit", width="stretch")

        # 3. Logs (CSS Terminal Style)
        with self.logs_container.container():
            log_body = "".join(state_data['logs'])
            
            html_content = f"""
            <html>
            <head>
            <style>
                html, body {{
                    height: 100%;
                    margin: 0;
                    padding: 0;
                    background-color: #111;
                    color: #e0e0e0;
                    font-family: 'Consolas', 'Courier New', monospace;
                    font-size: 11px;
                }}
                
                #log-container {{
                    /* This forces the content to build from bottom up */
                    display: flex;
                    flex-direction: column-reverse;
                    min-height: 100%;
                    padding: 10px;
                    box-sizing: border-box;
                }}

                /* Scrollbar Styling */
                ::-webkit-scrollbar {{ width: 8px; }}
                ::-webkit-scrollbar-track {{ background: #1a1a1a; }}
                ::-webkit-scrollbar-thumb {{ background: #333; border-radius: 4px; }}
                
                .log-entry {{ border-bottom: 1px solid #222; padding: 6px 0; }}
                .log-header {{ color: {COLOR_ACCENT}; font-weight: bold; display: flex; justify-content: space-between; }}
                .log-body {{ margin-left: 10px; margin-top: 4px; }}
                .flight-row {{ margin-bottom: 3px; border-left: 2px solid #444; padding-left: 8px; }}
                .log-warn {{ color: {COLOR_WARN}; }}
                .log-err {{ color: {COLOR_DANGER}; font-weight: bold; }}
                .dim {{ color: #777; }}
                .highlight {{ color: #fff; }}
            </style>
            </head>
            <body>
                <div id="log-container">
                    {log_body}
                </div>
                <script>
                    window.scrollTo(0, document.body.scrollHeight);
                </script>
            </body>
            </html>
            """
            components.html(html_content, height=400, scrolling=True)

        # 4. Table
        if not state_data['airports_df'].empty:
            df = state_data['airports_df']
            
            # --- STYLING LOGIC ---
            def color_stock(row):
                # Colors
                c_green = 'background-color: #1b5e20; color: white'  # Dark Green
                c_yellow = 'background-color: #f57f17; color: white' # Dark Orange/Yellow
                c_red = 'background-color: #b71c1c; color: white'    # Dark Red
                
                # Output styles list (must match column count)
                styles = [''] * len(row)
                
                try:
                    # Map visible columns to their capacity columns
                    # We assume columns are: Code, Status, FC, BC, PE, EC, Cap_FC...
                    pairs = [
                        ('FC', 'Cap_FC'), 
                        ('BC', 'Cap_BC'), 
                        ('PE', 'Cap_PE'), 
                        ('EC', 'Cap_EC')
                    ]
                    
                    for stock_col, cap_col in pairs:
                        idx = df.columns.get_loc(stock_col)
                        val = row[stock_col]
                        cap = row[cap_col]
                        
                        if val < 0 or val > cap:
                            styles[idx] = c_red
                        elif val == cap:
                            styles[idx] = c_yellow
                        else:
                            styles[idx] = c_green
                except:
                    pass # Safety net
                    
                return styles

            # Apply the style
            styled_df = df.style.apply(color_stock, axis=1)
            
            # Format numbers to look clean (no decimals)
            styled_df = styled_df.format("{:.0f}", subset=["FC", "BC", "PE", "EC"])

            with self.table_container.container():
                st.dataframe(
                    styled_df,
                    width="stretch",
                    hide_index=True,
                    column_config={
                        "Code": "Airport",
                        "Status": "Health",
                        # Hide the capacity columns used for calculation
                        "Cap_FC": None, "Cap_BC": None, "Cap_PE": None, "Cap_EC": None
                    },
                    height=400
                )