# streamlit_app.py

import io
import re
import zipfile
import requests
import streamlit as st
import pandas as pd
from openpyxl import load_workbook

try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None

# -------------- Configuración --------------
st.set_page_config(layout="centered", page_title="Rechazos MASIVOS Unificado")

ENDPOINT = (
    "https://q6caqnpy09.execute-api.us-east-1.amazonaws.com"
    "/OPS/kpayout/v1/payout_process/reject_invoices_batch"
)

TXT_POS = {
    "dni": (25, 33),
    "nombre": (40, 85),
    "referencia": (115, 126),
    "importe": (186, 195),
}

ESTADO = "rechazada"
MULT = 2

CODE_DESC = {
    "R001": "DOCUMENTO ERRADO",
    "R002": "CUENTA INVALIDA",
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

# -------------- Utilidades --------------
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

    c1, c2, c3 = st.columns([1, 2, 1])
    with c2:
        b1, b2 = st.columns(2, gap="small")
        if b1.button("R001\nDOCUMENTO ERRADO", key=f"{key}_r001"):
            st.session_state[key] = "R001"
        if b2.button("R002\nCUENTA INVALIDA", key=f"{key}_r002"):
            st.session_state[key] = "R002"

    code = st.session_state[key]
    desc = CODE_DESC[code]
    st.write("Código de rechazo seleccionado:", f"**{code} – {desc}**")
    return code, desc

# -------------- Pestañas --------------
def tab_pre_bcp_xlsx():
    st.header("PRE BCP-xlsx")
    code, desc = select_code("pre_xlsx_code", "R002")

    pdf_file = st.file_uploader("PDF con filas", type="pdf", key="pre_xlsx_pdf")
    ex_file  = st.file_uploader("Excel masivo", type="xlsx", key="pre_xlsx_xls")

    if pdf_file and ex_file:
        with st.spinner("Procesando PRE BCP-xlsx..."):
            text = ""
            for page in fitz.open(stream=pdf_file.read(), filetype="pdf"):
                text += page.get_text() or ""

            filas = sorted({int(n) + 1 for n in re.findall(r"Registro\s+(\d+)", text)})
            df_raw = pd.read_excel(ex_file, dtype=str)
            df_sel = df_raw.iloc[filas].reset_index(drop=True)

            st.dataframe(df_sel)
            excel_bytes = df_to_excel_bytes(df_sel)
            st.download_button(
                "Descargar excel de registros",
                excel_bytes,
                file_name="pre_bcp_xlsx.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
            if st.button("RECH-POSTMAN", key="post_pre_xlsx"):
                status, resp = post_to_endpoint(df_sel.iloc[:, 3:].pipe(df_to_excel_bytes))
                st.success(f"{status}: {resp}")

def tab_pre_bcp_txt():
    st.header("PRE BCP-txt")
    code, desc = select_code("pre_txt_code", "R002")

    pdf_file = st.file_uploader("PDF", type="pdf", key="pre_txt_pdf")
    txt_file = st.file_uploader("TXT", type="txt", key="pre_txt_txt")

    if pdf_file and txt_file:
        with st.spinner("Procesando PRE BCP-txt..."):
            text = ""
            for page in fitz.open(stream=pdf_file.read(), filetype="pdf"):
                text += page.get_text() or ""

            regs    = sorted({int(m) for m in re.findall(r"Registro\s+(\d{1,5})", text)})
            lines   = txt_file.read().decode("utf-8", errors="ignore").splitlines()
            indices = sorted({r * MULT for r in regs})

            rows = []
            for i in indices:
                if 1 <= i <= len(lines):
                    ln     = lines[i - 1]
                    dni    = slice_fixed(ln, *TXT_POS["dni"])
                    nombre = slice_fixed(ln, *TXT_POS["nombre"])
                    ref    = slice_fixed(ln, *TXT_POS["referencia"])
                    imp    = parse_amount(slice_fixed(ln, *TXT_POS["importe"]))
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
            st.dataframe(df)
            excel_bytes = df_to_excel_bytes(df)
            st.download_button(
                "Descargar excel de registros",
                excel_bytes,
                file_name="pre_bcp_txt.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
            if st.button("RECH-POSTMAN", key="post_pre_txt"):
                status, resp = post_to_endpoint(df.iloc[:, 3:].pipe(df_to_excel_bytes))
                st.success(f"{status}: {resp}")

def tab_rechazo_ibk():
    st.header("rechazo IBK")
    user_code, user_desc = select_code("ibk_code", "R002")

    zip_file = st.file_uploader("ZIP con Excel", type="zip", key="ibk_zip")
    if zip_file:
        with st.spinner("Procesando rechazo IBK..."):
            buf    = io.BytesIO(zip_file.read())
            zf     = zipfile.ZipFile(buf)
            fname  = next(n for n in zf.namelist() if n.lower().endswith((".xlsx", ".xls")))
            df_raw = pd.read_excel(zf.open(fname), dtype=str)
            df2    = df_raw.iloc[11:].reset_index(drop=True)

            rows = []
            for _, r in df2.iterrows():
                o = str(r.iloc[14] or "")
                if not o.strip():
                    continue

                dni    = r.iloc[4]
                nombre = r.iloc[5]
                ref    = r.iloc[7]
                imp    = parse_amount(r.iloc[13])

                # Aplicar regla R016 vs R002
                if any(k in o.lower() for k in KEYWORDS_NO_TIT):
                    code, desc = "R016", "CLIENTE NO TITULAR DE LA CUENTA"
                else:
                    code, desc = user_code, user_desc

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
            st.dataframe(df)

            excel_bytes = df_to_excel_bytes(df)
            st.download_button(
                "Descargar excel de registros",
                excel_bytes,
                file_name="rechazo_ibk.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
            if st.button("RECH-POSTMAN", key="post_ibk"):
                status, resp = post_to_endpoint(df.iloc[:, 3:].pipe(df_to_excel_bytes))
                st.success(f"{status}: {resp}")

def tab_post_bcp_xlsx():
    st.header("POST BCP-xlsx")
    code, desc = select_code("post_xlsx_code", "R001")

    pdf_file = st.file_uploader("PDF con DNI", type="pdf", key="post_xlsx_pdf")
    ex_file  = st.file_uploader("Excel masivo", type="xlsx", key="post_xlsx_xls")

    if pdf_file and ex_file:
        with st.spinner("Procesando POST BCP-xlsx..."):
            text = ""
            for page in fitz.open(stream=pdf_file.read(), filetype="pdf"):
                text += page.get_text() or ""
            docs = set(re.findall(r"\b\d{6,}\b", text))

            df_raw = pd.read_excel(ex_file, dtype=str)
            mask   = df_raw.astype(str).apply(lambda col: col.isin(docs)).any(axis=1)
            df_sel = df_raw.loc[mask].reset_index(drop=True)

            st.dataframe(df_sel)
            excel_bytes = df_to_excel_bytes(df_sel)
            st.download_button(
                "Descargar excel de registros",
                excel_bytes,
                file_name="post_bcp_xlsx.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
            if st.button("RECH-POSTMAN", key="post_post_xlsx"):
                status, resp = post_to_endpoint(df_sel.iloc[:, 3:].pipe(df_to_excel_bytes))
                st.success(f"{status}: {resp}")

# -------------- Render pestañas --------------
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
