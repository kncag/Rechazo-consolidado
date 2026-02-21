import io
import re
import zipfile
import requests
import streamlit as st
import pandas as pd
import pdfplumber

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
    "titular",
    "beneficiario no",
    "cliente no titular",
    "no titular",
    "continuar",
    "puedes continuar",
    "si deseas, puedes continuar",
    "puedes continua",
    "si deseas, puedes continua",
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
def clean_text(obs: str) -> str:
    """Limpia espacios dobles, tabs y saltos de línea para mejorar el matching de palabras clave."""
    return re.sub(r'\s+', ' ', str(obs).lower().strip())

def parse_amount(raw) -> float:
    if raw is None:
        return 0.0
    s = re.sub(r"[^\d,.-]", "", str(raw))
    if "." in s and "," in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    parts = s.split(".")
    if len(parts) > 2:
        s = "".join(parts[:-1]) + "." + parts[-1]
    try:
        return float(s)
    except ValueError:
        return 0.0

def slice_fixed(line: str, start: int, end: int) -> str:
    if not line:
        return ""
    idx = max(0, start - 1)
    return line[idx:end].strip() if idx < len(line) else ""

def df_to_excel_bytes(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Rechazos")
    return buf.getvalue()

def post_to_endpoint(excel_bytes: bytes) -> tuple[int, str]:
    files = {
        "edt": (
            "rechazos.xlsx",
            excel_bytes,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    }
    resp = requests.post(ENDPOINT, files=files)
    return resp.status_code, resp.text

def select_code(key: str, default: str) -> tuple[str, str]:
    if key not in st.session_state:
        st.session_state[key] = default
    _, center, _ = st.columns([1, 8, 1])
    with center:
        b1, b2, b3 = st.columns(3, gap="small")
        if b1.button("R001\nDOCUMENTO ERRADO", key=f"{key}_r001"):
            st.session_state[key] = "R001"
        if b2.button("R002\nCUENTA INVALIDA", key=f"{key}_r002"):
            st.session_state[key] = "R002"
        if b3.button("R007\nRECHAZO POR CCI", key=f"{key}_r007"):
            st.session_state[key] = "R007"
    code = st.session_state[key]
    desc = CODE_DESC.get(code, "CUENTA INVALIDA")
    st.write("Código de rechazo seleccionado:", f"**{code} – {desc}**")
    return code, desc

def _validate_and_post(df: pd.DataFrame, button_key: str):
    if list(df.columns) != OUT_COLS:
        st.error(f"Encabezados inválidos. Se requieren: {OUT_COLS}")
        return
    if st.button("RECH-POSTMAN", key=button_key):
        payload = df[SUBSET_COLS]
        excel_bytes = df_to_excel_bytes(payload)
        status, resp = post_to_endpoint(excel_bytes)
        st.success(f"{status}: {resp}")

def _count_and_sum(df: pd.DataFrame) -> tuple[int, float]:
    cnt = len(df)
    total = df["importe"].sum() if "importe" in df.columns else 0.0
    return cnt, total

def parse_sco_importe(raw: str) -> float:
    try:
        return float(raw) / 100.0
    except ValueError:
        return 0.0

def map_sco_xls_error_to_code(observation: str) -> tuple[str, str]:
    obs = str(observation).strip()
    if "Verificar cuenta y/o documento" in obs:
        return "R001", "DOCUMENTO ERRADO"
    if obs == "Cancelada" or obs == "Verificar cuenta.":
        return "R002", "CUENTA INVALIDA"
    if "Abono AFP" in obs:
        return "R017", "CUENTA DE AFP / CTS"
    return "R002", "CUENTA INVALIDA"

# -------------- Flujos --------------

def tab_bcp_prueba():
    st.header("BCP Prueba")
    st.info("Módulo para procesar rechazos desde Excel BCP basado en la columna 'Observación'.")
    
    ex_file = st.file_uploader("Cargar Excel BCP (.xlsx)", type=["xlsx", "xls", "csv"], key="bcp_prueba_file")
    
    if ex_file:
        with st.spinner("Procesando BCP prueba…"):
            # Permite probar también con CSV si es necesario basado en el ejemplo subido
            if ex_file.name.endswith(".csv"):
                df_raw = pd.read_csv(ex_file, dtype=str)
            else:
                df_raw = pd.read_excel(ex_file, dtype=str)
            
            if "Observación" not in df_raw.columns:
                st.error("No se encontró la columna 'Observación' en el archivo.")
                return
            
            # Filtrar donde Observación no sea nula y sea diferente de "Ninguna"
            mask = df_raw["Observación"].notna() & (df_raw["Observación"].str.strip().str.lower() != "ninguna")
            df_valid = df_raw.loc[mask].reset_index(drop=True)
            
            if df_valid.empty:
                st.warning("No se encontraron registros con observaciones diferentes a 'Ninguna'.")
                return
            
            # Identificar columnas. Pandas renombra columnas duplicadas añadiendo .1, .2, etc.
            # "Documento" suele ser el DNI, "Documento.1" suele ser el PSPTIN (que inicia con 000).
            col_dni = "Documento" if "Documento" in df_valid.columns else df_valid.columns[3]
            col_ref = "Documento.1" if "Documento.1" in df_valid.columns else df_valid.columns[5]
            col_nombre = "Beneficiario - Nombre" if "Beneficiario - Nombre" in df_valid.columns else df_valid.columns[1]
            col_importe = "Monto" if "Monto" in df_valid.columns else df_valid.columns[7]

            df_out = pd.DataFrame({
                "dni/cex": df_valid[col_dni],
                "nombre": df_valid[col_nombre],
                "importe": df_valid[col_importe].apply(parse_amount),
                "Referencia": df_valid[col_ref],
            })
            
            df_out["Estado"] = ESTADO
            
            # Asignación de Código de Rechazo exclusiva para BCP (Sin R016), ahora con clean_text
            df_out["Codigo de Rechazo"] = [
                "R001" if any(k in clean_text(o) for k in KEYWORDS_NO_TIT) else "R002"
                for o in df_valid["Observación"]
            ]
            df_out["Descripcion de Rechazo"] = [
                CODE_DESC["R001"] if any(k in clean_text(o) for k in KEYWORDS_NO_TIT) else CODE_DESC["R002"]
                for o in df_valid["Observación"]
            ]
            
            df_out = df_out[OUT_COLS]

            cnt, total = _count_and_sum(df_out)
            st.write(f"**Total transacciones:** {cnt}   |   **Suma de importes:** {total:,.2f}")

            st.dataframe(df_out)

            eb = df_to_excel_bytes(df_out)
            st.download_button(
                "Descargar excel de registros",
                eb,
                file_name="rechazo_bcp_prueba.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

            _validate_and_post(df_out, "post_bcp_prueba")

def tab_pre_bcp_xlsx():
    st.header("Antigua manera de rechazar con PDF")
    code, desc = select_code("pre_xlsx_code", "R002")
    pdf_file = st.file_uploader("PDF con filas", type="pdf", key="pre_xlsx_pdf")
    ex_file = st.file_uploader("Excel masivo", type="xlsx", key="pre_xlsx_xls")
    
    if pdf_file and ex_file:
        with st.spinner("Procesando PRE BCP-xlsx…"):
            pdf_bytes = pdf_file.read()
            text = "".join(p.get_text() or "" for p in fitz.open(stream=io.BytesIO(pdf_bytes), filetype="pdf"))
            filas = sorted({int(n) + 1 for n in re.findall(r"Registro\s+(\d+)", text)})
            df_raw = pd.read_excel(ex_file, dtype=str)
            
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
            df_out["Estado"] = ESTADO
            df_out["Codigo de Rechazo"] = code
            df_out["Descripcion de Rechazo"] = desc
            df_out = df_out[OUT_COLS]

            cnt, total = _count_and_sum(df_out)
            st.write(f"**Total transacciones:** {cnt}   |   **Suma de importes:** {total:,.2f}")
            st.dataframe(df_out)
            
            eb = df_to_excel_bytes(df_out)
            st.download_button("Descargar excel", eb, file_name="pre_bcp_xlsx.xlsx")
            _validate_and_post(df_out, "post_pre_xlsx")

def tab_pre_bcp_txt():
    st.header("PRE BCP-txt")
    code, desc = select_code("pre_txt_code", "R002")
    pdf_file = st.file_uploader("PDF", type="pdf", key="pre_txt_pdf")
    txt_file = st.file_uploader("TXT", type="txt", key="pre_txt_txt")
    
    if pdf_file and txt_file:
        with st.spinner("Procesando PRE BCP-txt…"):
            pdf_bytes = pdf_file.read()
            text = "".join(p.get_text() or "" for p in fitz.open(stream=io.BytesIO(pdf_bytes), filetype="pdf"))
            regs = sorted({int(m) for m in re.findall(r"Registro\s+(\d{1,5})", text)})
            lines = txt_file.read().decode("utf-8", errors="ignore").splitlines()
            indices = sorted({r * MULT for r in regs})

            rows = []
            for i in indices:
                if 1 <= i <= len(lines):
                    ln = lines[i - 1]
                    dni = slice_fixed(ln, *TXT_POS["dni"])
                    nombre = slice_fixed(ln, *TXT_POS["nombre"])
                    ref = slice_fixed(ln, *TXT_POS["referencia"])
                    imp = parse_amount(slice_fixed(ln, *TXT_POS["importe"]))
                    rows.append({"dni/cex": dni, "nombre": nombre, "importe": imp, "Referencia": ref})

            df_out = pd.DataFrame(rows) if rows else pd.DataFrame(columns=["dni/cex", "nombre", "importe", "Referencia"])
            df_out["Estado"] = ESTADO
            df_out["Codigo de Rechazo"] = code
            df_out["Descripcion de Rechazo"] = desc
            df_out = df_out[OUT_COLS]

            st.dataframe(df_out)
            eb = df_to_excel_bytes(df_out)
            st.download_button("Descargar excel", eb, file_name="pre_bcp_txt.xlsx")
            _validate_and_post(df_out, "post_pre_txt")

def tab_rechazo_ibk():
    st.header("rechazo IBK")
    zip_file = st.file_uploader("ZIP con Excel", type="zip", key="ibk_zip")
    if zip_file:
        with st.spinner("Procesando…"):
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
            df_out["Estado"] = ESTADO
            
            # Ahora usamos la funcion clean_text para asegurar el reconocimiento de R016
            df_out["Codigo de Rechazo"] = [
                "R016" if any(k in clean_text(o) for k in KEYWORDS_NO_TIT) else "R002" 
                for o in df_valid.iloc[:, 14]
            ]
            df_out["Descripcion de Rechazo"] = [
                "CLIENTE NO TITULAR DE LA CUENTA" if any(k in clean_text(o) for k in KEYWORDS_NO_TIT) else "CUENTA INVALIDA" 
                for o in df_valid.iloc[:, 14]
            ]
            
            df_out = df_out[OUT_COLS]

            st.dataframe(df_out)
            eb = df_to_excel_bytes(df_out)
            st.download_button("Descargar excel", eb, file_name="rechazo_ibk.xlsx")
            _validate_and_post(df_out, "post_ibk")

def tab_post_bcp_xlsx():
    st.header("POST BCP-xlsx")
    code, desc = select_code("post_xlsx_code", "R001")
    pdf_file = st.file_uploader("PDF de DNIs", type="pdf", key="post_xlsx_pdf")
    ex_file = st.file_uploader("Excel masivo", type="xlsx", key="post_xlsx_xls")
    
    if pdf_file and ex_file:
        pdf_bytes = pdf_file.read()
        text = "".join(p.get_text() or "" for p in fitz.open(stream=io.BytesIO(pdf_bytes), filetype="pdf"))
        docs = set(re.findall(r"\b\d{6,}\b", text))
        df_raw = pd.read_excel(ex_file, dtype=str)
        
        if docs:
            mask = df_raw.astype(str).apply(lambda col: col.isin(docs)).any(axis=1)
            df_temp = df_raw.loc[mask].reset_index(drop=True)
            
            df_out = pd.DataFrame({
                "dni/cex": df_temp.iloc[:, 0],
                "nombre": df_temp.iloc[:, 3] if df_temp.shape[1] > 3 else df_temp.iloc[:, 1],
                "importe": df_temp.iloc[:, 12].apply(parse_amount),
                "Referencia": df_temp.iloc[:, 7],
            })
            df_out["Codigo de Rechazo"] = code
            
            edited_df = st.data_editor(df_out, num_rows="dynamic", key="editor_post_bcp")
            df_final = edited_df.copy()
            df_final["Estado"] = ESTADO
            df_final["Descripcion de Rechazo"] = df_final["Codigo de Rechazo"].map(CODE_DESC)
            df_final = df_final[OUT_COLS]
            
            st.dataframe(df_final)
            eb = df_to_excel_bytes(df_final)
            st.download_button("Descargar excel", eb, file_name="post_bcp_xlsx.xlsx")
            _validate_and_post(df_final, "post_post_xlsx")

def tab_sco_processor():
    st.header("Procesador Scotiabank")
    pdf_file = st.file_uploader("1. PDF Detalle", type="pdf", key="sco_pdf")
    txt_file = st.file_uploader("2. TXT Masivo", type="txt", key="sco_txt")
    xls_file = st.file_uploader("3. XLS Errores", type=["xls", "xlsx", "csv"], key="sco_xls")

    if txt_file and xls_file:
        txt_content = txt_file.read().decode("utf-8", errors="ignore")
        txt_lines = [line for line in txt_content.splitlines() if line.strip()]
        df_xls = pd.read_excel(xls_file, header=6, dtype=str)
        
        rows_to_reject = []
        for _, row in df_xls.iterrows():
            linea_val = row.get("Linea")
            if pd.isna(linea_val): continue
            idx_array = int(float(linea_val)) - 1
            if 0 <= idx_array < len(txt_lines):
                ln = txt_lines[idx_array]
                code, desc = map_sco_xls_error_to_code(row.get("Observación:"))
                rows_to_reject.append({
                    "dni/cex": slice_fixed(ln, *SCO_TXT_POS["dni"]),
                    "nombre": slice_fixed(ln, *SCO_TXT_POS["nombre"]),
                    "importe": parse_sco_importe(slice_fixed(ln, *SCO_TXT_POS["importe"])),
                    "Referencia": slice_fixed(ln, 116, 127),
                    "Codigo de Rechazo": code,
                    "Descripcion de Rechazo": desc
                })
        
        if rows_to_reject:
            df_out = pd.DataFrame(rows_to_reject)
            edited_df = st.data_editor(df_out, key="editor_sco_simple")
            df_final = edited_df.copy()
            df_final["Estado"] = ESTADO
            df_final["Descripcion de Rechazo"] = df_final["Codigo de Rechazo"].map(CODE_DESC)
            df_final = df_final[OUT_COLS]
            st.dataframe(df_final)
            _validate_and_post(df_final, "post_sco_simple")

def tab_rechazo_total_txt():
    st.header("Rechazo TOTAL (Banco Inoperativo)")
    txt_file = st.file_uploader("Cargar TXT Masivo", type="txt", key="total_txt")
    if txt_file:
        content = txt_file.read().decode("utf-8", errors="ignore")
        lines = content.splitlines()[1:]
        rows = []
        i = 0
        while i < len(lines):
            line1 = lines[i]
            dni = line1[24:32].strip()
            if len(dni) >= 6 and (i + 1) < len(lines):
                line2 = lines[i+1]
                rows.append({
                    "dni/cex": dni,
                    "nombre": line1[39:80].strip(),
                    "importe": parse_amount(line2[25:34].strip()),
                    "Referencia": line1[114:126].strip(),
                })
                i += 2
            else: i += 1
        
        df_out = pd.DataFrame(rows)
        df_out["Estado"] = ESTADO
        df_out["Codigo de Rechazo"] = "R020"
        df_out["Descripcion de Rechazo"] = CODE_DESC["R020"]
        df_out = df_out[OUT_COLS]
        st.dataframe(df_out)
        _validate_and_post(df_out, "post_total_txt")

# -------------- Render pestañas --------------
tabs = st.tabs([
    "PRE BCP-txt",
    "-", 
    "rechazo IBK",
    "POST BCP-xlsx",
    "Procesador SCO",
    "Rechazo TOTAL",
    "BCP prueba",
])

with tabs[0]:
    tab_pre_bcp_txt()
with tabs[1]:
    tab_pre_bcp_xlsx()
with tabs[2]:
    tab_rechazo_ibk()
with tabs[3]:
    tab_post_bcp_xlsx()
with tabs[4]:          
    tab_sco_processor()
with tabs[5]:
    tab_rechazo_total_txt()
with tabs[6]:
    tab_bcp_prueba()
