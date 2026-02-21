import io
import re
import zipfile
import requests
import streamlit as st
import pandas as pd

try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None

# -------------- Configuración --------------
st.set_page_config(layout="centered", page_title="Rechazos MASIVOS Unificado")

ENDPOINT = "https://q6caqnpy09.execute-api.us-east-1.amazonaws.com/OPS/kpayout/v1/payout_process/reject_invoices_batch"

TXT_POS = {
    "dni": (25, 33),
    "nombre": (40, 85),
    "referencia": (115, 126),
    "importe": (186, 195),
}

ESTADO = "rechazada"
MULT = 2

# Tipos globales
CODE_DESC = {
    "R001": "DOCUMENTO ERRADO",
    "R002": "CUENTA INVALIDA",
    "R007": "RECHAZO POR CCI",
    "R016": "CLIENTE NO TITULAR DE LA CUENTA",
    "R017": "CUENTA DE AFP / CTS",
    "R020": "CUENTA BANCARIA INOPERATIVA",
}

SCO_TXT_POS = {
    "dni": (2, 9),
    "nombre": (14, 73),
    "importe": (105, 115),
    "referencia": (116, 127),
}

KEYWORDS_NO_TIT = [
    "no es titular",
    "beneficiario no",
    "cliente no titular",
    "no titular",
    "continuar",
    "puedes continuar",
    "si deseas, puedes continuar",
]

OUT_COLS = [
    "dni/cex",
    "nombre",
    "importe",
    "Referencia",
    "Estado",
    "Codigo de Rechazo",
    "Descripcion de Rechazo",
]

SUBSET_COLS = [
    "Referencia",
    "Estado",
    "Codigo de Rechazo",
    "Descripcion de Rechazo",
]

# -------------- Utilidades --------------
def parse_amount(raw) -> float:
    if raw is None: return 0.0
    s = re.sub(r"[^\d,.-]", "", str(raw))
    if "." in s and "," in s: s = s.replace(".", "").replace(",", ".")
    elif "," in s: s = s.replace(",", ".")
    parts = s.split(".")
    if len(parts) > 2: s = "".join(parts[:-1]) + "." + parts[-1]
    try: return float(s)
    except ValueError: return 0.0

def slice_fixed(line: str, start: int, end: int) -> str:
    if not line: return ""
    idx = max(0, start - 1)
    return line[idx:end].strip() if idx < len(line) else ""

def df_to_excel_bytes(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Rechazos")
    return buf.getvalue()

def post_to_endpoint(excel_bytes: bytes) -> tuple[int, str]:
    files = {"edt": ("rechazos.xlsx", excel_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    resp = requests.post(ENDPOINT, files=files)
    return resp.status_code, resp.text

def select_code(key: str, default: str) -> tuple[str, str]:
    if key not in st.session_state:
        st.session_state[key] = default
    _, center, _ = st.columns([1, 8, 1])
    with center:
        b1, b2, b3 = st.columns(3, gap="small")
        if b1.button("R001\nDOCUMENTO ERRADO", key=f"{key}_r001"): st.session_state[key] = "R001"
        if b2.button("R002\nCUENTA INVALIDA", key=f"{key}_r002"): st.session_state[key] = "R002"
        if b3.button("R007\nRECHAZO POR CCI", key=f"{key}_r007"): st.session_state[key] = "R007"
    code = st.session_state[key]
    desc = CODE_DESC.get(code, "CUENTA INVALIDA")
    st.write("Código de rechazo seleccionado:", f"**{code} – {desc}**")
    return code, desc

def _validate_and_post(df: pd.DataFrame, button_key: str):
    if list(df.columns) != OUT_COLS:
        st.error(f"Encabezados inválidos. Se requieren: {OUT_COLS}")
        return
    if st.button("RECH-POSTMAN", key=button_key, use_container_width=True):
        payload = df[SUBSET_COLS]
        excel_bytes = df_to_excel_bytes(payload)
        status, resp = post_to_endpoint(excel_bytes)
        st.success(f"{status}: {resp}")

def _count_and_sum(df: pd.DataFrame) -> tuple[int, float]:
    return len(df), df["importe"].sum() if "importe" in df.columns else 0.0

def extract_text_from_pdf(pdf_file) -> str:
    """Extrae texto de un archivo PDF usando PyMuPDF."""
    pdf_bytes = pdf_file.read()
    return "".join(p.get_text() or "" for p in fitz.open(stream=io.BytesIO(pdf_bytes), filetype="pdf"))

def load_dataframe(uploaded_file, **kwargs) -> pd.DataFrame:
    """Detecta si es CSV o Excel y carga el dataframe."""
    if uploaded_file.name.lower().endswith(".csv"):
        return pd.read_csv(uploaded_file, dtype=str, **kwargs)
    return pd.read_excel(uploaded_file, dtype=str, **kwargs)

def render_final_output(df: pd.DataFrame, file_name: str, post_key: str, editor_key: str, default_code: str = None):
    """
    Centraliza formateo del df, cálculo de totales, tabla editable y botones.
    """
    st.subheader("Registros a procesar (Editables)")
    st.caption("Puedes modificar los datos, cambiar el 'Motivo de Rechazo' o añadir/eliminar filas usando las casillas de la izquierda.")

    df_ui = df.copy()
    df_ui["Estado"] = ESTADO
    
    # Asignar código por defecto si la lógica previa no lo hizo
    if default_code and "Codigo de Rechazo" not in df_ui.columns:
        df_ui["Codigo de Rechazo"] = default_code
        
    if "Codigo de Rechazo" in df_ui.columns:
        df_ui["Descripcion de Rechazo"] = df_ui["Codigo de Rechazo"].map(CODE_DESC)
        df_ui["Motivo de Rechazo"] = df_ui["Codigo de Rechazo"] + " - " + df_ui["Descripcion de Rechazo"]
        df_ui = df_ui.drop(columns=["Codigo de Rechazo", "Descripcion de Rechazo"])

    valid_options = [f"{k} - {v}" for k, v in CODE_DESC.items()]

    edited_df = st.data_editor(
        df_ui,
        column_config={
            "Motivo de Rechazo": st.column_config.SelectboxColumn("Código y Descripción", options=valid_options, required=True),
            "dni/cex": st.column_config.TextColumn("DNI/CEX"), 
            "nombre": st.column_config.TextColumn("Nombre"),   
            "importe": st.column_config.NumberColumn("Importe", format="%.2f"), 
            "Referencia": st.column_config.TextColumn("Referencia"), 
            "Estado": st.column_config.TextColumn("Estado", disabled=True),
        },
        use_container_width=True,
        num_rows="dynamic",
        key=editor_key
    )
    
    # Reconstruir columnas finales
    df_final = edited_df.copy()
    if "Motivo de Rechazo" in df_final.columns:
        df_final["Codigo de Rechazo"] = df_final["Motivo de Rechazo"].apply(lambda v: str(v).split(" - ")[0].strip() if pd.notna(v) else "")
        df_final["Descripcion de Rechazo"] = df_final["Motivo de Rechazo"].apply(
            lambda v: str(v).split(" - ", 1)[1].strip() if pd.notna(v) and " - " in str(v) else CODE_DESC.get(str(v).split(" - ")[0], "")
        )
        df_final = df_final.drop(columns=["Motivo de Rechazo"])
        
    for col in OUT_COLS:
        if col not in df_final.columns: df_final[col] = ""
    df_final = df_final[OUT_COLS]
    
    cnt, total = _count_and_sum(df_final)
    st.write(f"**Total transacciones:** {cnt}   |   **Suma de importes:** {total:,.2f}")
        
    eb = df_to_excel_bytes(df_final)
    col1, col2 = st.columns(2)
    with col1: st.download_button("Descargar excel de registros", eb, file_name=file_name, mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
    with col2: _validate_and_post(df_final, post_key)

# Lógica de Scotiabank
def parse_sco_importe(raw: str) -> float:
    try: return float(raw) / 100.0
    except ValueError: return 0.0

def map_sco_xls_error_to_code(observation: str) -> tuple[str, str]:
    obs = str(observation).strip()
    if "Verificar cuenta y/o documento" in obs: return "R001", "DOCUMENTO ERRADO"
    if obs in ("Cancelada", "Verificar cuenta."): return "R002", "CUENTA INVALIDA"
    if "Abono AFP" in obs: return "R017", "CUENTA DE AFP / CTS"
    return "R002", "CUENTA INVALIDA"

# -------------- Flujos --------------
def tab_pre_bcp_xlsx():
    st.header("Antigua manera de rechazar con PDF")
    code, desc = select_code("pre_xlsx_code", "R002")

    pdf_file = st.file_uploader("PDF con filas", type="pdf", key="pre_xlsx_pdf")
    ex_file = st.file_uploader("Excel masivo", type="xlsx", key="pre_xlsx_xls")
    
    if pdf_file and ex_file:
        with st.spinner("Procesando PRE BCP-xlsx…"):
            text = extract_text_from_pdf(pdf_file)
            filas = sorted({int(n) + 1 for n in re.findall(r"Registro\s+(\d+)", text)})
            df_raw = load_dataframe(ex_file)
            
            if not filas:
                st.warning("No se detectaron filas en el PDF.")
                return
            filas_valid = [i for i in filas if 0 <= i - 1 < len(df_raw)]
            df_temp = df_raw.iloc[[i - 1 for i in filas_valid]].reset_index(drop=True)

            ref_out = df_temp.iloc[:, 7] if df_temp.shape[1] > 7 else pd.Series([""] * len(df_temp))
            nombre_out = df_temp.iloc[:, 3] if df_temp.shape[1] > 3 else (df_temp.iloc[:, 1] if df_temp.shape[1] > 1 else pd.Series([""] * len(df_temp)))

            df_out = pd.DataFrame({
                "dni/cex": df_temp.iloc[:, 0],
                "nombre": nombre_out,
                "importe": df_temp.iloc[:, 12].apply(parse_amount) if df_temp.shape[1] > 12 else pd.Series([0.0] * len(df_temp)),
                "Referencia": ref_out,
            })
            render_final_output(df_out, "pre_bcp_xlsx.xlsx", "post_pre_xlsx", "editor_pre_xlsx", default_code=code)

def tab_pre_bcp_txt():
    st.subheader("PRE RECHAZO BCP")
    code, desc = select_code("pre_txt_code", "R002")

    pdf_file = st.file_uploader("PDF", type="pdf", key="pre_txt_pdf")
    txt_file = st.file_uploader("TXT", type="txt", key="pre_txt_txt")
    
    if pdf_file and txt_file:
        with st.spinner("Procesando PRE BCP-txt…"):
            text = extract_text_from_pdf(pdf_file)
            regs = sorted({int(m) for m in re.findall(r"Registro\s+(\d{1,5})", text)})
            lines = txt_file.read().decode("utf-8", errors="ignore").splitlines()
            indices = sorted({r * MULT for r in regs})

            rows = []
            for i in indices:
                if 1 <= i <= len(lines):
                    ln = lines[i - 1]
                    rows.append({
                        "dni/cex": slice_fixed(ln, *TXT_POS["dni"]),
                        "nombre": slice_fixed(ln, *TXT_POS["nombre"]),
                        "importe": parse_amount(slice_fixed(ln, *TXT_POS["importe"])),
                        "Referencia": slice_fixed(ln, *TXT_POS["referencia"]),
                    })
                else:
                    rows.append({"dni/cex": "", "nombre": "", "importe": 0.0, "Referencia": ""})

            df_out = pd.DataFrame(rows) if rows else pd.DataFrame(columns=["dni/cex", "nombre", "importe", "Referencia"])
            render_final_output(df_out, "pre_bcp_txt.xlsx", "post_pre_txt", "editor_pre_txt", default_code=code)

def tab_bcp_prueba():
    st.subheader("POST RECHAZO BCP")
    st.info("Módulo para procesar rechazos desde Excel BCP basado en la columna 'Observación'.")
    
    code, desc = select_code("bcp_prueba_code", "R001")
    ex_file = st.file_uploader("Cargar Excel BCP (.xlsx o .csv)", type=["xlsx", "xls", "csv"], key="bcp_prueba_file")
    
    if ex_file:
        with st.spinner("Procesando POST RECHAZO BCP…"):
            df_raw = load_dataframe(ex_file)
            if "Observación" not in df_raw.columns:
                st.error("No se encontró la columna 'Observación' en el archivo.")
                return
            
            mask = df_raw["Observación"].notna() & (df_raw["Observación"].str.strip().str.lower() != "ninguna")
            df_valid = df_raw.loc[mask].reset_index(drop=True)
            
            if df_valid.empty:
                st.warning("No se encontraron registros.")
                return
            
            nombre_out = df_valid["Beneficiario - Nombre"] if "Beneficiario - Nombre" in df_valid.columns else pd.Series([""] * len(df_valid))
            dni_out = df_valid.iloc[:, 3] if df_valid.shape[1] > 3 else pd.Series([""] * len(df_valid))
            ref_out = df_valid.iloc[:, 5] if df_valid.shape[1] > 5 else pd.Series([""] * len(df_valid))
            importe_out = df_valid["Monto"].apply(parse_amount) if "Monto" in df_valid.columns else pd.Series([0.0] * len(df_valid))

            df_out = pd.DataFrame({
                "dni/cex": dni_out,
                "nombre": nombre_out,
                "importe": importe_out,
                "Referencia": ref_out.astype(str).apply(lambda x: x[3:] if x.startswith("000") else x),
            })
            render_final_output(df_out, "rechazo_bcp_prueba.xlsx", "post_bcp_prueba", "editor_bcp_prueba", default_code=code)

def tab_bcp():
    st.header("BCP")
    tab_pre_bcp_txt()
    st.divider()
    tab_bcp_prueba()

def tab_rechazo_ibk():
    st.header("IBK")

    zip_file = st.file_uploader("ZIP con Excel", type="zip", key="ibk_zip")
    if zip_file:
        with st.spinner("Procesando rechazo IBK…"):
            buf = io.BytesIO(zip_file.read())
            zf = zipfile.ZipFile(buf)
            fname = next(n for n in zf.namelist() if n.lower().endswith((".xlsx", ".xls")))
            df_raw = pd.read_excel(zf.open(fname), dtype=str)
            df2 = df_raw.iloc[11:].reset_index(drop=True)

            col_o = df2.iloc[:, 14]
            mask = col_o.notna() & (col_o.astype(str).str.strip() != "")
            df_valid = df2.loc[mask].reset_index(drop=True)

            df_out = pd.DataFrame({
                "dni/cex": df_valid.iloc[:, 4],
                "nombre": df_valid.iloc[:, 5],
                "importe": df_valid.iloc[:, 13].apply(parse_amount),
                "Referencia": df_valid.iloc[:, 7],
            })
            
            # Lógica propia de IBK para código de rechazo por palabras clave
            df_out["Codigo de Rechazo"] = ["R016" if any(k in str(o).lower() for k in KEYWORDS_NO_TIT) else "R002" for o in df_valid.iloc[:, 14]]
            
            render_final_output(df_out, "rechazo_ibk.xlsx", "post_ibk", "editor_ibk")

def tab_post_bcp_xlsx():
    st.header("BBVA")
    
    code, desc = select_code("post_xlsx_code", "R001")
    pdf_file = st.file_uploader("PDF de DNIs", type="pdf", key="post_xlsx_pdf")
    ex_file = st.file_uploader("Excel masivo", type="xlsx", key="post_xlsx_xls")
    
    if pdf_file and ex_file:
        with st.spinner("Procesando BBVA…"):
            text = extract_text_from_pdf(pdf_file)
            docs = set(re.findall(r"\b\d{6,}\b", text))
            df_raw = load_dataframe(ex_file)
            
            if docs:
                mask = df_raw.astype(str).apply(lambda col: col.isin(docs)).any(axis=1)
                df_temp = df_raw.loc[mask].reset_index(drop=True)
            else:
                st.error("No se detectaron identificadores en el PDF.")
                return

            ref_out = df_temp.iloc[:, 7] if df_temp.shape[1] > 7 else pd.Series([""] * len(df_temp))
            nombre_out = df_temp.iloc[:, 3] if df_temp.shape[1] > 3 else (df_temp.iloc[:, 1] if df_temp.shape[1] > 1 else pd.Series([""] * len(df_temp)))
            
            df_out = pd.DataFrame({
                "dni/cex": df_temp.iloc[:, 0],
                "nombre": nombre_out,
                "importe": df_temp.iloc[:, 12].apply(parse_amount) if df_temp.shape[1] > 12 else pd.Series([0.0] * len(df_temp)),
                "Referencia": ref_out,
            })
            render_final_output(df_out, "rechazos_bbva.xlsx", "post_post_xlsx", "editor_post_bcp", default_code=code)
            
def tab_sco_processor():
    st.header("SCO")
    st.info("Auditoría de cantidades y Procesamiento de errores por Excel.")

    col_up1, col_up2, col_up3 = st.columns(3)
    with col_up1: pdf_file = st.file_uploader("1. PDF Detalle", type="pdf", key="sco_pdf")
    with col_up2: txt_file = st.file_uploader("2. TXT Masivo", type="txt", key="sco_txt")
    with col_up3: xls_file = st.file_uploader("3. XLS Errores", type=["xls", "xlsx", "csv"], key="sco_xls")

    txt_lines = []
    
    if pdf_file and txt_file:
        st.divider()
        st.subheader("📊 Sección 1: Auditoría de Cantidades")
        txt_content = txt_file.read().decode("utf-8", errors="ignore")
        txt_lines = [line for line in txt_content.splitlines() if line.strip()]
        
        pdf_text = extract_text_from_pdf(pdf_file)
        count_ok_pdf = pdf_text.upper().replace("Ο", "O").replace("Κ", "K").count("O.K.")

        c1, c2, c3 = st.columns(3)
        c1.metric("Registros en TXT", len(txt_lines))
        c2.metric("Confirmaciones 'O.K.' en PDF", count_ok_pdf)
        
        diff = len(txt_lines) - count_ok_pdf
        c3.metric("Diferencia", diff, delta_color="inverse")

        if diff == 0: st.success("✅ ¡Cuadratura Perfecta!")
        elif diff > 0: st.warning(f"⚠️ Hay {diff} posibles rechazos.")
        else: st.error("🚨 Extraño: Más 'O.K.' que líneas en el TXT.")

    if xls_file and txt_lines:
        st.divider()
        st.subheader("🚫 Sección 2: Generar Rechazos")
        
        rows_to_reject = []
        try:
            df_xls = pd.read_excel(xls_file, header=6, dtype=str)
            if "Linea" not in df_xls.columns:
                st.error("El Excel no tiene la columna 'Linea'. Verifique el formato (header=6).")
            else:
                for _, row in df_xls.iterrows():
                    linea_val = row.get("Linea")
                    obs_val = row.get("Observación:")
                    if pd.isna(linea_val): continue
                    
                    try: line_idx = int(float(linea_val))
                    except ValueError: continue

                    idx_array = line_idx - 1
                    if 0 <= idx_array < len(txt_lines):
                        raw_line = txt_lines[idx_array]
                        code, desc = map_sco_xls_error_to_code(obs_val)
                        rows_to_reject.append({
                            "dni/cex": slice_fixed(raw_line, *SCO_TXT_POS["dni"]),
                            "nombre": slice_fixed(raw_line, *SCO_TXT_POS["nombre"]),
                            "importe": parse_sco_importe(slice_fixed(raw_line, *SCO_TXT_POS["importe"])),
                            "Referencia": slice_fixed(raw_line, 116, 127),
                            "Codigo de Rechazo": code
                        })
        except Exception as e:
            st.error(f"Error leyendo XLS: {e}")

        if rows_to_reject:
            df_out = pd.DataFrame(rows_to_reject)
            render_final_output(df_out, "rechazos_sco.xlsx", "post_sco_simple", "editor_sco_simple")
        elif xls_file:
            st.info("El XLS no contenía líneas válidas.")

    elif not pdf_file and not txt_file:
        st.info("👆 Carga los archivos arriba para comenzar.")

def tab_rechazo_total_txt():
    st.header("Rechazo TOTAL (Banco Inoperativo)")
    st.warning("⚠️ ESTA OPCIÓN RECHAZARÁ TODO EL ARCHIVO EXCEL CON EL CÓDIGO SELECCIONADO.")

    code, desc = select_code("total_excel_code", "R020")
    ex_file = st.file_uploader("Cargar Excel Masivo para rechazar totalmente", type=["xlsx", "xls", "csv"], key="total_excel")
    
    if ex_file:
        with st.spinner("Procesando rechazo total..."):
            df_raw = load_dataframe(ex_file)
            
            if df_raw.shape[1] <= 7:
                st.error("El archivo no tiene las columnas necesarias (se espera el formato POST BCP-xlsx).")
                return
            
            col_ref_name = df_raw.columns[7]
            df_valid = df_raw.dropna(subset=[col_ref_name]).copy()
            df_valid[col_ref_name] = df_valid[col_ref_name].astype(str).str.strip()
            df_valid = df_valid[df_valid[col_ref_name] != ""]
            df_valid = df_valid[df_valid[col_ref_name].str.lower() != "nan"]
            df_valid = df_valid.reset_index(drop=True)

            if df_valid.empty:
                st.error("No se detectaron registros válidos en la columna de Referencia (columna 8).")
                return

            df_out = pd.DataFrame({
                "dni/cex": df_valid.iloc[:, 0],
                "nombre": df_valid.iloc[:, 3] if df_valid.shape[1] > 3 else (df_valid.iloc[:, 1] if df_valid.shape[1] > 1 else pd.Series([""] * len(df_valid))),
                "importe": df_valid.iloc[:, 12].apply(parse_amount) if df_valid.shape[1] > 12 else pd.Series([0.0] * len(df_valid)),
                "Referencia": df_valid.iloc[:, 7],
            })
            render_final_output(df_out, "rechazo_total_inoperativo.xlsx", "post_total_excel", "editor_total_excel", default_code=code)


# -------------- Render pestañas --------------
tabs = st.tabs(["BCP", "IBK", "BBVA", "SCO", "Rechazo TOTAL"])

with tabs[0]: tab_bcp()
with tabs[1]: tab_rechazo_ibk()
with tabs[2]: tab_post_bcp_xlsx()
with tabs[3]: tab_sco_processor()
with tabs[4]: tab_rechazo_total_txt()
