# streamlit_app.py

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

CODE_DESC = {
    "R001": "DOCUMENTO ERRADO",
    "R002": "CUENTA INVALIDA",
    "R007": "RECHAZO POR CCI",
}

KEYWORDS_NO_TIT = [
    "no es titular",
    "beneficiario no",
    "cliente no titular",
    "no titular",
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
    try:
        resp = requests.post(ENDPOINT, files=files, timeout=30)
        return resp.status_code, resp.text
    except requests.RequestException as e:
        return 0, f"Network error: {e}"

def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    if fitz is None or pdf_bytes is None:
        return ""
    try:
        doc = fitz.open(stream=io.BytesIO(pdf_bytes), filetype="pdf")
        return "".join((p.get_text() or "") for p in doc)
    except Exception:
        return ""

def select_code(key: str, default: str) -> tuple[str, str]:
    if key not in st.session_state:
        st.session_state[key] = default
    _, center, _ = st.columns([1, 2, 1])
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
        if 200 <= status < 300:
            st.success(f"{status}: {resp}")
        else:
            st.error(f"{status}: {resp}")

def render_preview_and_actions(df_out: pd.DataFrame, download_key: str, download_name: str, post_key: str):
    cnt = len(df_out)
    total = df_out["importe"].sum() if "importe" in df_out.columns else 0.0
    st.write(f"**Total transacciones:** {cnt}   |   **Suma de importes:** {total:,.2f}")
    st.dataframe(df_out)
    eb = df_to_excel_bytes(df_out)
    c1, c2 = st.columns(2)
    with c1:
        st.download_button(
            "Descargar excel de registros",
            eb,
            file_name=download_name,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key=download_key,
        )
    with c2:
        _validate_and_post(df_out, post_key)

# -------------- Flujos --------------
def tab_pre_bcp_xlsx():
    st.header("PRE BCP-xlsx")
    code, desc = select_code("pre_xlsx_code", "R002")

    pdf_file = st.file_uploader("PDF con filas", type="pdf", key="pre_xlsx_pdf")
    ex_file = st.file_uploader("Excel masivo", type="xlsx", key="pre_xlsx_xls")
    if pdf_file and ex_file:
        pdf_bytes = pdf_file.read()
        text = extract_text_from_pdf(pdf_bytes)
        filas = sorted({int(n) + 1 for n in re.findall(r"Registro\s+(\d+)", text)})

        df_raw = pd.read_excel(ex_file, dtype=str)
        if not filas:
            st.warning("No se detectaron filas en el PDF con el patrón 'Registro N'.")
            return
        filas_valid = [i for i in filas if 0 <= i - 1 < len(df_raw)]
        if not filas_valid:
            st.warning("Los índices detectados están fuera del rango del Excel.")
            return
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

        render_preview_and_actions(df_out, "download_pre_bcp_xlsx", f"pre_bcp_xlsx_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}.xlsx", "post_pre_xlsx")

def tab_pre_bcp_txt():
    st.header("PRE BCP-txt")
    code, desc = select_code("pre_txt_code", "R002")

    pdf_file = st.file_uploader("PDF", type="pdf", key="pre_txt_pdf")
    txt_file = st.file_uploader("TXT", type="txt", key="pre_txt_txt")
    if pdf_file and txt_file:
        pdf_bytes = pdf_file.read()
        text = extract_text_from_pdf(pdf_bytes)
        regs = sorted({int(m) for m in re.findall(r"Registro\s+(\d{1,5})", text)})
        lines = txt_file.read().decode("utf-8", errors="ignore").splitlines()
        indices = sorted({r * MULT for r in regs})

        rows = []
        for i
