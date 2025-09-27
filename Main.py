# streamlit_app.py
import io
import re
import zipfile
import requests
import streamlit as st
import pandas as pd
from openpyxl import load_workbook, Workbook
from openpyxl.styles import PatternFill
from openpyxl.utils import get_column_letter

try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None

# -------------------
# CONFIGURACIÓN
# -------------------
st.set_page_config(layout="centered", page_title="Rechazos MASIVOS")
st.markdown(
    """
    <style>
      .main > div.block-container { max-width: 900px; padding: 1rem; }
    </style>
    """,
    unsafe_allow_html=True,
)

ENDPOINT = "https://q6caqnpy09.execute-api.us-east-1.amazonaws.com/OPS/kpayout/v1/payout_process/reject_invoices_batch"
TXT_POS = dict(dni=(25, 33), nombre=(40, 85), referencia=(115, 126), importe=(186, 195))
ESTADO = "rechazada"
MULT = 2

PDF_RECH = {
    "R001: DOCUMENTO ERRADO": ("R001", "DOCUMENTO ERRADO"),
    "R002: CUENTA INVALIDA": ("R002", "CUENTA INVALIDA"),
}
RECH_ZIP = [("R016", "CLIENTE NO TITULAR DE LA CUENTA"), ("R002", "CUENTA INVALIDA")]
KEYS_NO_TIT = ["no es titular", "beneficiario no", "continuar"]

OUT_COLS = [
    "dni/cex",
    "nombre",
    "importe",
    "Referencia",
    "Estado",
    "Codigo de Rechazo",
    "Descripcion de Rechazo",
]

# -------------------
# UTILIDADES
# -------------------
def parse_amount(raw):
    if raw is None:
        return 0.0
    s = re.sub(r"[^\d,.-]", "", str(raw).strip())
    if "." in s and "," in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    if s.count(".") > 1:
        parts = s.split(".")
        s = "".join(parts[:-1]) + "." + parts[-1]
    try:
        return float(s)
    except:
        return 0.0

def slice_fixed(line, start, end):
    if not line:
        return ""
    idx = max(0, start - 1)
    return line[idx:end].strip() if idx < len(line) else ""

def df_to_excel_bytes(df):
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        df.to_excel(w, index=False, sheet_name="Rechazos")
    return buf.getvalue()

def post_to_endpoint(excel_bytes):
    files = {
        "edt": (
            "rechazos.xlsx",
            excel_bytes,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    }
    r = requests.post(ENDPOINT, files=files)
    return r.status_code, r.text

# -------------------
# FLUJOS
# -------------------
def flujo_pre_bcp_txt():
    st.header("PRE BCP-txt")
    st.write("Extrae Registro N del PDF, multiplica por 2 internamente, lee línea del TXT y genera Excel.")
    if "sel_pre_txt" not in st.session_state:
        st.session_state.sel_pre_txt = list(PDF_RECH.keys())[0]

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        b1, b2 = st.columns(2, gap="small")
        if b1.button("R001\nDOCUMENTO ERRADO"):
            st.session_state.sel_pre_txt = "R001: DOCUMENTO ERRADO"
        if b2.button("R002\nCUENTA INVALIDA"):
            st.session_state.sel_pre_txt = "R002: CUENTA INVALIDA"

    st.write("Selección:", f"**{st.session_state.sel_pre_txt}**")
    code, desc = PDF_RECH[st.session_state.sel_pre_txt]

    pdf_file = st.file_uploader("Sube PDF", type="pdf", key="pre_txt_pdf")
    txt_file = st.file_uploader("Sube TXT", type="txt", key="pre_txt_txt")
    if pdf_file and txt_file:
        with st.spinner("Procesando..."):
            lines = txt_file.read().decode("utf-8", errors="ignore").splitlines()
            if not fitz:
                st.error("Módulo PyMuPDF no disponible")
                return

            text = ""
            for page in fitz.open(stream=pdf_file.read(), filetype="pdf"):
                text += page.get_text()
            regs = sorted({int(m) for m in re.findall(r"Registro\s+(\d{1,5})", text, re.IGNORECASE)})
            indices = sorted({r * MULT for r in regs})

            rows = []
            for i in indices:
                if 1 <= i <= len(lines):
                    ln = lines[i - 1]
                    dni = slice_fixed(ln, *TXT_POS["dni"])
                    nombre = slice_fixed(ln, *TXT_POS["nombre"])
                    ref = slice_fixed(ln, *TXT_POS["referencia"])
                    imp = parse_amount(slice_fixed(ln, *TXT_POS["importe"]))
                else:
                    dni = nombre = ref = ""
                    imp = 0.0
                rows.append({
                    "dni/cex": dni,
                    "nombre": nombre,
                    "importe": imp,
                    "Referencia": ref,
                    "Estado": ESTADO,
                    "Codigo de Rechazo": code,
                    "Descripcion de Rechazo": desc,
                })

            df = pd.DataFrame(rows, columns=OUT_COLS)
            df["importe"] = pd.to_numeric(df["importe"], errors="coerce").fillna(0.0)
            st.dataframe(df.head(50))

            excel_all = df_to_excel_bytes(df)
            if st.button("Validar", key="val_pre_txt"):
                st.download_button(
                    "Descargar Excel completo",
                    excel_all,
                    file_name="pre_bcp_txt.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            if st.button("RECH-POSTMAN", key="post_pre_txt"):
                df_post = df.iloc[:, 3:]
                excel_post = df_to_excel_bytes(df_post)
                status, resp = post_to_endpoint(excel_post)
                st.success(f"POST status: {status}, respuesta: {resp}")

def flujo_rechazo_ibk():
    st.header("rechazo IBK")
    st.write("Sube ZIP con un Excel, procesa desde fila 12 y filtra por columna O.")
    zip_file = st.file_uploader("Sube ZIP con Excel", type="zip", key="ibk_zip")
    if zip_file:
        with st.spinner("Procesando ZIP..."):
            buf = io.BytesIO(zip_file.read())
            zf = zipfile.ZipFile(buf)
            name = next(n for n in zf.namelist() if n.lower().endswith((".xlsx", ".xls")))
            df_raw = pd.read_excel(zf.open(name), dtype=str)
            df_proc = df_raw.iloc[11:].reset_index(drop=True)

            rows = []
            for _, r in df_proc.iterrows():
                o = str(r.iloc[14] or "")
                if not o.strip():
                    continue
                dni = r.iloc[4]
                nombre = r.iloc[5]
                ref = r.iloc[7]
                imp = parse_amount(r.iloc[13])
                code, desc = RECH_ZIP[0] if any(k in o.lower() for k in KEYS_NO_TIT) else RECH_ZIP[1]
                rows.append({
                    "dni/cex": dni,
                    "nombre": nombre,
                    "importe": imp,
                    "Referencia": ref,
                    "Estado": ESTADO,
                    "Codigo de Rechazo": code,
                    "Descripcion de Rechazo": desc,
                })

            df = pd.DataFrame(rows, columns=OUT_COLS)
            df["importe"] = pd.to_numeric(df["importe"], errors="coerce").fillna(0.0)
            st.dataframe(df.head(50))

            excel_all = df_to_excel_bytes(df)
            if st.button("Validar", key="val_ibk"):
                st.download_button(
                    "Descargar Excel completo",
                    excel_all,
                    file_name="rechazo_ibk.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            if st.button("RECH-POSTMAN", key="post_ibk"):
                df_post = df.iloc[:, 3:]
                excel_post = df_to_excel_bytes(df_post)
                status, resp = post_to_endpoint(excel_post)
                st.success(f"POST status: {status}, respuesta: {resp}")

def flujo_pre_bcp_xlsx():
    st.header("PRE BCP-xlsx")
    st.write("Extrae número de fila desde PDF y filtra esas filas en el Excel masivo.")
    pdf_file = st.file_uploader("Sube PDF con filas", type="pdf", key="pre_xlsx_pdf")
    ex_file = st.file_uploader("Sube Excel masivo", type="xlsx", key="pre_xlsx_xls")
    if pdf_file and ex_file:
        with st.spinner("Procesando PRE..."):
            text = ""
            for page in fitz.open(stream=pdf_file.read(), filetype="pdf"):
                text += page.get_text()
            filas = sorted({int(n) + 1 for n in re.findall(r"Registro\s+(\d+)", text, re.IGNORECASE)})

            wb = load_workbook(ex_file)
            ws = wb.active
            cols = [c.value for c in ws[1]]
            rows = []
            for f in filas:
                if f <= ws.max_row:
                    rows.append([cell.value for cell in ws[f]])

            df = pd.DataFrame(rows, columns=cols)
            st.dataframe(df.head(50))

            excel_all = df_to_excel_bytes(df)
            if st.button("Validar", key="val_pre_xlsx"):
                st.download_button(
                    "Descargar Excel completo",
                    excel_all,
                    file_name="pre_bcp_xlsx.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            if st.button("RECH-POSTMAN", key="post_pre_xlsx"):
                df_post = df.iloc[:, 3:]
                excel_post = df_to_excel_bytes(df_post)
                status, resp = post_to_endpoint(excel_post)
                st.success(f"POST status: {status}, respuesta: {resp}")

def flujo_post_bcp_xlsx():
    st.header("POST BCP-xlsx")
    st.write("Extrae DNI desde PDF y filtra filas en el Excel masivo.")
    pdf_file = st.file_uploader("Sube PDF con DNI", type="pdf", key="post_xlsx_pdf")
    ex_file = st.file_uploader("Sube Excel masivo", type="xlsx", key="post_xlsx_xls")
    if pdf_file and ex_file:
        with st.spinner("Procesando POST..."):
            text = ""
            for page in fitz.open(stream=pdf_file.read(), filetype="pdf"):
                text += page.get_text()
            docs =
