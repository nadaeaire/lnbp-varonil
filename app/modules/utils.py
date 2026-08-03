# modules/utils.py
import streamlit as st
import pandas as pd
from datetime import datetime
import pytz
import streamlit.components.v1 as components

# --- DEPENDENCIAS PARA EL LOG EN GOOGLE SHEETS ---
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# 1. INYECCIÓN DE GOOGLE ANALYTICS
def inyectar_ga():
    GA_ID = "G-H2HWJBPVN1"
    ga_code = f"""
    <script async src="https://www.googletagmanager.com/gtag/js?id={GA_ID}"></script>
    <script>
        window.dataLayer = window.dataLayer || [];
        function gtag(){{dataLayer.push(arguments);}}
        gtag('js', new Date());
        gtag('config', '{GA_ID}');
    </script>
    """
    components.html(ga_code, height=0, width=0)

# 2. CARGA DE ESTILOS CSS
def cargar_estilos_css():
    st.markdown("""
    <style>
        .block-container {padding-top: 1rem; padding-bottom: 2rem;}
        [data-testid="stMetricValue"] {font-size: 1.5rem;}
        thead tr th:first-child {display:none}
        tbody tr td:first-child {display:none}
        td { font-variant-numeric: tabular-nums; }
        [data-testid="stSidebar"] { background-color: #efcd92; }
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
    </style>
    """, unsafe_allow_html=True)

# 3. REGISTRO DE EVENTOS (TRACKING EN GOOGLE SHEETS)
def registrar_evento(usuario, accion):
    """Escribe un evento en la hoja 'Log' de Google Sheets."""
    if not usuario: usuario = "Anonimo"
    
    try:
        # Definir el alcance
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        
        # Intentar cargar credenciales desde secrets.toml o archivo local
        if "gcp_service_account" in st.secrets:
            creds = ServiceAccountCredentials.from_json_keyfile_dict(st.secrets["gcp_service_account"], scope)
        else:
            # Fallback a archivo local (Asegúrate de que este archivo exista en tu carpeta raíz)
            creds = ServiceAccountCredentials.from_json_keyfile_name("nea-accesosheets-ce29b7c423e5.json", scope)

        client = gspread.authorize(creds)
        
        # Abrir hoja y escribir
        sheet = client.open("Streamlit Accesos")
        worksheet = sheet.worksheet("Log")

        try:
            tz = pytz.timezone('America/Mexico_City')
            now = datetime.now(tz)
        except:
            now = datetime.now()

        timestamp_str = now.strftime("%Y-%m-%d %H:%M:%S")
        
        # Escribir la fila
        worksheet.append_row([timestamp_str, usuario, accion], value_input_option='USER_ENTERED')
        
    # En modules/utils.py (al final de la función registrar_evento)

    except Exception as e:
        # CAMBIO TEMPORAL: Muestra el error en la pantalla de la app
        #st.error(f"🚨 ERROR DE TRACKING: {e}") 
        print(f"⚠️ Error Tracking: {e}")

# 4. RASTREO DE CAMBIOS (PARA SLIDERS Y SELECTORES)
def rastrear_cambio(nombre_variable, valor_actual):
    """Detecta si una variable cambió y la registra."""
    usuario = st.session_state.get("user_email", "Anonimo")
    key_memoria = f"log_{nombre_variable}"

    # Si es la primera vez, guardamos el estado sin loguear
    if key_memoria not in st.session_state:
        st.session_state[key_memoria] = valor_actual
        return

    # Si cambió, registramos
    if st.session_state[key_memoria] != valor_actual:
        registrar_evento(usuario, f"Cambio {nombre_variable}: {valor_actual}")
        st.session_state[key_memoria] = valor_actual