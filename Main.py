# streamlit_app.py

import io
import re
import zipfile
import requests
import streamlit as st
import pandas as pd
from typing import Tuple

try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None

# -------------------
# CONFIGURACIÓN
# -------------------
st.set_page_config(layout="centered", page_title="Rechazos MASIVOS Optimizado")

ENDPOINT = (
    "https://q6caqnpy09.execute-api.us-east-1.amazonaws.com"
    "/OPS/kpayout/v1/payout_process/reject_invoices_batch"
)
TXT_POS = dict(dni=(25, 33), nombre=(40, 85), referencia=(115, 126), importe=(186, 195))
ESTADO = "rechazada"
MULT = 2
CODE_DESC = {"R001": "DOCUMENTO ERRADO", "R002": "CUENTA INVALIDA"}
OUT_COLS = [
    "dni/cex", "nombre", "importe", "Referencia",
    "Estado", "Codigo de Rechazo", "Descripcion de Rechazo",
]

# Precompile regex once
REGEX_REG = re.compile(r"Registro\s+(\d{1,5})", re.IGNORECASE)
REGEX_DNI = re.compile(r"\b\d{6,}\b")

# -------------------
# CACHE y UTILIDADES
# -------------------
@st.cache_data(show_spinner=False)
def extract_pdf_text(pdf_bytes: bytes) -> str:
    if fitz is None:
        return ""
    text = []
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        for page in doc:
            text.append(page.get_text() or "")
    return "\n".join(text)

@st.cache_data(show_spinner=False)
def extract_registros(text: str) -> list[int]:
    nums = {int(m) for m in REGEX_REG.findall(text)}
    return sorted(nums)

@st.cache_data(show_spinner=False)
def load_txt_lines(txt_bytes: bytes) -> list[str]:
    return txt_bytes.decode("utf-8", errors="ignore").splitlines()

@st.cache_data(show_spinner=False)
def load_excel_from_zip(zip_bytes: bytes, usecols=None) -> pd.DataFrame:
    buf = io.BytesIO(zip_bytes)
    with zipfile.ZipFile(buf) as zf:
        name = next(n for n in zf.namelist() if n.lower().endswith((".xlsx", ".xls")))
        return pd.read_excel(zf.open(name), dtype=str, usecols=usecols)

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

def df_to_excel_bytes(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        df.to_excel(w, index=False, sheet_name="Rechazos")
    return buf.getvalue()

def post_to_endpoint(excel_bytes: bytes) -> Tuple[int, str]:
    files = {
        "edt": (
            "rechazos.xlsx",
            excel_bytes,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    }
    resp = requests.post(ENDPOINT, files=files)
    return resp.status_code, resp.text

def select_code(key: str, default: str = "R002") -> Tuple[str, str]:
    if key not in st.session_state:
        st.session_state[key] = default
    c1, c2, c3 = st.columns([1, 2, 1])
    with c2:
        btn1, btn2 = st.columns(2, gap="small")
        if btn1.button("R001\nDOCUMENTO ERRADO", key=f"{key}_r001"):
            st.session_state[key] = "R001"
        if btn2.button("R002\nCUENTA INVALIDA", key=f"{key}_r002"):
            st.session_state[key] = "R002"
    code = st.session_state[key]
    return code, CODE_DESC[code]

# -------------------
# Pestañas / Flujos
# -------------------
def tab_pre_bcp_xlsx():
    st.header("PRE BCP-xlsx")
    code, desc = select_code("pre_xlsx_code", "R002")
    pdf = st.file_uploader("PDF con filas", type="pdf", key="pre_xlsx_pdf")
    xls = st.file_uploader("Excel masivo", type="xlsx", key="pre_xlsx_xls")
    if pdf and xls:
        with st.spinner("Procesando…"):
            text = extract_pdf_text(pdf.read())
            filas = [i + 1 for i in extract_registros(text)]
            df = pd.read_excel(xls, dtype=str)
            # vectorized slice of rows
            df_sel = df.iloc[filas].copy()
            st.dataframe(df_sel)
            xb = df_to_excel_bytes(df_sel)
            st.download_button(
                "Descargar excel de registros", xb,
                file_name="pre_bcp_xlsx.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
            if st.button("RECH-POSTMAN", key="post_pre_xlsx"):
                code, _ = post_to_endpoint(df_sel.iloc[:, 3:].pipe(df_to_excel_bytes))
                st.success(f"OK {code}")

def tab_pre_bcp_txt():
    st.header("PRE BCP-txt")
    code, desc = select_code("pre_txt_code", "R002")
    pdf = st.file_uploader("PDF", type="pdf", key="pre_txt_pdf")
    txt = st.file_uploader("TXT", type="txt", key="pre_txt_txt")
    if pdf and txt:
        with st.spinner("Procesando…"):
            text = extract_pdf_text(pdf.read())
            regs = extract_registros(text)
            lines = load_txt_lines(txt.read())
            idxs = [r * MULT for r in regs]
            rows = []
            for i in idxs:
                if 1 <= i <= len(lines):
                    ln = lines[i - 1]
                    dni = slice_fixed(ln, *TXT_POS["dni"])
                    nom = slice_fixed(ln, *TXT_POS["nombre"])
                    ref = slice_fixed(ln, *TXT_POS["referencia"])
                    imp = parse_amount(slice_fixed(ln, *TXT_POS["importe"]))
                else:
                    dni = nom = ref = ""
                    imp = 0.0
                rows.append({
                    "dni/cex": dni, "nombre": nom, "importe": imp,
                    "Referencia": ref,
                    "Estado": ESTADO,
                    "Codigo de Rechazo": code,
                    "Descripcion de Rechazo": desc
                })
            df = pd.DataFrame(rows, columns=OUT_COLS)
            st.dataframe(df)
            xb = df_to_excel_bytes(df)
            st.download_button(
                "Descargar excel de registros", xb,
                file_name="pre_bcp_txt.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
            if st.button("RECH-POSTMAN", key="post_pre_txt"):
                code, _ = post_to_endpoint(df.iloc[:, 3:].pipe(df_to_excel_bytes))
                st.success(f"OK {code}")

def tab_rechazo_ibk():
    st.header("rechazo IBK")
    code, desc = select_code("ibk_code", "R002")
    zipf = st.file_uploader("ZIP con Excel", type="zip", key="ibk_zip")
    if zipf:
        with st.spinner("Procesando…"):
            df_raw = load_excel_from_zip(zipf.read())
            df2 = df_raw.iloc[11:].reset_index(drop=True)
            # vectorized filter on column O (15th col, index14)
            mask = df2.iloc[:, 14].astype(str).str.strip().astype(bool)
            df_sel = df2.loc[mask, [4,5,7,13]].copy()
            df_sel.columns = ["dni/cex","nombre","Referencia","importe_raw"]
            df_sel["importe"] = df_sel["importe_raw"].apply(parse_amount)
            df_sel["Estado"] = ESTADO
            df_sel["Codigo de Rechazo"] = code
            df_sel["Descripcion de Rechazo"] = desc
            df = df_sel[OUT_COLS]
            st.dataframe(df)
            xb = df_to_excel_bytes(df)
            st.download_button(
                "Descargar excel de registros", xb,
                file_name="rechazo_ibk.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
            if st.button("RECH-POSTMAN", key="post_ibk"):
                code, _ = post_to_endpoint(df.iloc[:, 3:].pipe(df_to_excel_bytes))
                st.success(f"OK {code}")

def tab_post_bcp_xlsx():
    st.header("POST BCP-xlsx")
    code, desc = select_code("post_xlsx_code", "R001")
    pdf = st.file_uploader("PDF con DNI", type="pdf", key="post_xlsx_pdf")
    xls = st.file_uploader("Excel masivo", type="xlsx", key="post_xlsx_xls")
    if pdf and xls:
        with st.spinner("Procesando…"):
            text = extract_pdf_text(pdf.read())
            docs = set(REGEX_DNI.findall(text))
            df = pd.read_excel(xls, dtype=str)
            # vectorized any-match across rows
            mask = df.astype(str).apply(lambda col: col.isin(docs)).any(axis=1)
            df_sel = df.loc[mask].copy()
            st.dataframe(df_sel)
            xb = df_to_excel_bytes(df_sel)
            st.download_button(
                "Descargar excel de registros", xb,
                file_name="post_bcp_xlsx.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
            if st.button("RECH-POSTMAN", key="post_post_xlsx"):
                code, _ = post_to_endpoint(df_sel.iloc[:, 3:].pipe(df_to_excel_bytes))
                st.success(f"OK {code}")

# -------------------
# RENDER
# -------------------
tabs = st.tabs([
    "PRE BCP-xlsx",
    "PRE BCP-txt",
    "rechazo IBK",
    "POST BCP-xlsx",
])
with tabs[0]:
    tab_pre_bcp_xlsx()
with tabs[1]:
    tab_pre_bcp_txt()
with tabs[2]:
    tab_rechazo_ibk()
with tabs[3]:
    tab_post_bcp_xlsx()
