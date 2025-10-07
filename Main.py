# Main.py - Versión completa y estable con botones RECH-POSTMAN y Descarga (keys únicas)

import io
import re
import zipfile
from typing import Callable, Dict, List, Optional, Tuple

import pandas as pd
import requests
import streamlit as st

try:
    import fitz  # PyMuPDF
except Exception:
    fitz = None

# -------------------- Configuración y constantes --------------------
ENDPOINT = "https://q6caqnpy09.execute-api.us-east-1.amazonaws.com/OPS/kpayout/v1/payout_process/reject_invoices_batch"

OUT_COLS: List[str] = [
    "dni/cex",
    "nombre",
    "importe",
    "Referencia",
    "Estado",
    "Codigo de Rechazo",
    "Descripcion de Rechazo",
]

SUBSET_COLS: List[str] = [
    "Referencia",
    "Estado",
    "Codigo de Rechazo",
    "Descripcion de Rechazo",
]

CODE_DESC: Dict[str, str] = {
    "R001": "DOCUMENTO ERRADO",
    "R002": "CUENTA INVALIDA",
    "R007": "RECHAZO POR CCI",
}

ESTADO = "rechazada"
ID_RE = re.compile(r"\b\d{6,9}\b")

# -------------------- Utilidades generales --------------------
def parse_amount(raw: Optional[str]) -> float:
    """Normaliza una cadena numérica y la convierte a float; retorna 0.0 en caso de error."""
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
    except Exception:
        return 0.0

def df_to_excel_bytes(df: pd.DataFrame) -> bytes:
    """Convierte DataFrame a bytes Excel (.xlsx) usando openpyxl."""
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Rechazos")
    return buf.getvalue()

def post_to_endpoint(excel_bytes: bytes, timeout: int = 30) -> Tuple[int, str]:
    """Envía multipart/form-data al ENDPOINT y devuelve (status_code, text)."""
    files = {
        "edt": ("rechazos.xlsx", excel_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    }
    resp = requests.post(ENDPOINT, files=files, timeout=timeout)
    return resp.status_code, resp.text

def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    """Extrae texto con PyMuPDF cuando está disponible, retorna cadena vacía si falla."""
    if fitz is None:
        return ""
    try:
        doc = fitz.open(stream=io.BytesIO(pdf_bytes), filetype="pdf")
        return "".join(page.get_text() or "" for page in doc)
    except Exception:
        return ""

# -------------------- Handler de envío (RECH) --------------------
def rech_post_handler(df: pd.DataFrame, feedback: Optional[Callable[[str, str], None]] = None) -> Tuple[bool, str]:
    """
    Valida y envía df al endpoint.
    feedback(level, message) opcional: level in {'success','error','info'}.
    Retorna (ok, mensaje).
    """
    def fb(level: str, msg: str):
        if feedback:
            try:
                feedback(level, msg)
            except Exception:
                pass

    if list(df.columns) != OUT_COLS:
        msg = f"Encabezados inválidos. Se requieren: {OUT_COLS}"
        fb("error", msg)
        return False, msg

    payload = df[SUBSET_COLS]
    try:
        excel_bytes = df_to_excel_bytes(payload)
    except Exception as e:
        msg = f"Error generando Excel: {e}"
        fb("error", msg)
        return False, msg

    try:
        status, resp = post_to_endpoint(excel_bytes)
    except Exception as e:
        msg = f"Error realizando POST: {e}"
        fb("error", msg)
        return False, msg

    msg = f"{status}: {resp}"
    if 200 <= status < 300:
        fb("success", msg)
        return True, msg
    fb("error", msg)
    return False, msg

# -------------------- Helpers de UI --------------------
def rech_button_and_send(df: pd.DataFrame, key: str, label: str = "RECH-POSTMAN") -> None:
    """Botón RECH-POSTMAN con key única; envía df al endpoint."""
    if st.button(label, key=key):
        ok, msg = rech_post_handler(df, feedback=lambda lvl, m: getattr(st, lvl)(m))
        if ok:
            st.success("Envío completado correctamente.")
        else:
            st.error(f"Envío fallido: {msg}")

def download_button_for_df(df: pd.DataFrame, key: str, filename: str) -> None:
    """Botón Descarga con key única; descarga el df mostrado en el preview."""
    excel_bytes = df_to_excel_bytes(df)
    st.download_button(
        label="Descarga",
        data=excel_bytes,
        file_name=filename,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key=key,
    )

def _select_code_ui(key: str, default: str = "R002") -> Tuple[str, str]:
    """UI para seleccionar código por defecto (conserva en session_state)."""
    if key not in st.session_state:
        st.session_state[key] = default
    c1, c2, c3 = st.columns(3)
    if c1.button("R001\nDOCUMENTO ERRADO", key=f"{key}_r001"):
        st.session_state[key] = "R001"
    if c2.button("R002\nCUENTA INVALIDA", key=f"{key}_r002"):
        st.session_state[key] = "R002"
    if c3.button("R007\nRECHAZO POR CCI", key=f"{key}_r007"):
        st.session_state[key] = "R007"
    code = st.session_state[key]
    return code, CODE_DESC.get(code, "CUENTA INVALIDA")

# -------------------- Pestañas (Flujos) --------------------
def tab_pre_bcp_xlsx():
    st.header("PRE BCP-xlsx")
    code, desc = _select_code_ui("pre_xlsx_code", "R002")

    pdf_file = st.file_uploader("PDF con filas", type="pdf", key="pre_xlsx_pdf")
    ex_file = st.file_uploader("Excel masivo", type="xlsx", key="pre_xlsx_xls")
    if not (pdf_file and ex_file):
        return

    pdf_bytes = pdf_file.read()
    text = extract_text_from_pdf(pdf_bytes)
    matches = re.findall(r"Registro\s+(\d+)", text)
    if not matches:
        st.warning("No se detectaron filas en el PDF con el patrón 'Registro N'.")
        return

    df_raw = pd.read_excel(ex_file, dtype=str)
    rows = sorted({int(n) + 1 for n in matches})
    rows_valid = [r for r in rows if 0 <= r - 1 < len(df_raw)]
    if not rows_valid:
        st.warning("Los índices detectados están fuera del rango del Excel.")
        return

    df_temp = df_raw.iloc[[r - 1 for r in rows_valid]].reset_index(drop=True)
    ref_out = df_temp.iloc[:, 7] if df_temp.shape[1] > 7 else pd.Series([""] * len(df_temp))
    nombre_out = df_temp.iloc[:, 3] if df_temp.shape[1] > 3 else (df_temp.iloc[:, 1] if df_temp.shape[1] > 1 else pd.Series([""] * len(df_temp)))

    df_out = pd.DataFrame({
        "dni/cex": df_temp.iloc[:, 0] if df_temp.shape[1] > 0 else pd.Series([""] * len(df_temp)),
        "nombre": nombre_out,
        "importe": df_temp.iloc[:, 12].apply(parse_amount) if df_temp.shape[1] > 12 else pd.Series([0.0] * len(df_temp)),
        "Referencia": ref_out,
    })
    df_out["Estado"] = ESTADO
    df_out["Codigo de Rechazo"] = code
    df_out["Descripcion de Rechazo"] = desc
    df_out = df_out[OUT_COLS]

    cnt, total = len(df_out), df_out["importe"].sum()
    st.write(f"Total transacciones: {cnt} | Suma importes: {total:,.2f}")
    st.dataframe(df_out)

    # Botones: Descarga y RECH (keys únicas)
    download_button_for_df(
        df_out,
        key="download_pre_bcp_xlsx",
        filename=f"pre_bcp_preview_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
    )
    rech_button_and_send(df_out, key="rech_postman_pre_bcp_xlsx")

def tab_pre_bcp_txt():
    st.header("PRE BCP-txt")
    code, desc = _select_code_ui("pre_txt_code", "R002")

    pdf_file = st.file_uploader("PDF", type="pdf", key="pre_txt_pdf")
    txt_file = st.file_uploader("TXT", type="txt", key="pre_txt_txt")
    if not (pdf_file and txt_file):
        return

    pdf_bytes = pdf_file.read()
    text = extract_text_from_pdf(pdf_bytes)
    regs = sorted({int(m) for m in re.findall(r"Registro\s+(\d{1,5})", text)})
    lines = txt_file.read().decode("utf-8", errors="ignore").splitlines()
    indices = sorted({r * 2 for r in regs})  # multiplicador fijo según lógica previa

    rows = []
    for i in indices:
        if 1 <= i <= len(lines):
            ln = lines[i - 1]
            dni = ln[24:33].strip() if len(ln) >= 33 else ""
            nombre = ln[39:85].strip() if len(ln) >= 85 else ""
            ref = ln[114:126].strip() if len(ln) >= 126 else ""
            imp = parse_amount(ln[185:195] if len(ln) >= 195 else "")
        else:
            dni = nombre = ref = ""
            imp = 0.0
        rows.append({"dni/cex": dni, "nombre": nombre, "importe": imp, "Referencia": ref})

    df_out = pd.DataFrame(rows).reindex(columns=["dni/cex", "nombre", "importe", "Referencia"])
    df_out["Estado"] = ESTADO
    df_out["Codigo de Rechazo"] = code
    df_out["Descripcion de Rechazo"] = desc
    df_out = df_out[OUT_COLS]

    cnt, total = len(df_out), df_out["importe"].sum()
    st.write(f"Total transacciones: {cnt} | Suma importes: {total:,.2f}")
    st.dataframe(df_out)

    download_button_for_df(
        df_out,
        key="download_pre_bcp_txt",
        filename=f"pre_bcp_txt_preview_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
    )
    rech_button_and_send(df_out, key="rech_postman_pre_bcp_txt")

def tab_rechazo_ibk():
    st.header("Rechazo IBK")
    zip_file = st.file_uploader("ZIP con Excel", type="zip", key="ibk_zip")
    if not zip_file:
        return

    buf = io.BytesIO(zip_file.read())
    zf = zipfile.ZipFile(buf)
    fname = next((n for n in zf.namelist() if n.lower().endswith((".xlsx", ".xls"))), None)
    if fname is None:
        st.error("No se encontró archivo Excel en el ZIP.")
        return

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
    df_out["Codigo de Rechazo"] = [
        "R016" if "no titular" in str(o).lower() else "R002"
        for o in df_valid.iloc[:, 14]
    ]
    df_out["Descripcion de Rechazo"] = [
        "CLIENTE NO TITULAR DE LA CUENTA" if "no titular" in str(o).lower()
        else "CUENTA INVALIDA"
        for o in df_valid.iloc[:, 14]
    ]
    df_out = df_out[OUT_COLS]

    cnt, total = len(df_out), df_out["importe"].sum()
    st.write(f"Total transacciones: {cnt} | Suma importes: {total:,.2f}")
    st.dataframe(df_out)

    download_button_for_df(
        df_out,
        key="download_rechazo_ibk",
        filename=f"rechazo_ibk_preview_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
    )
    rech_button_and_send(df_out, key="rech_postman_ibk")

def tab_post_bcp_xlsx():
    st.header("POST BCP-xlsx")
    code, desc = _select_code_ui("post_xlsx_code", "R001")

    pdf_file = st.file_uploader("PDF de DNIs", type="pdf", key="post_xlsx_pdf")
    ex_file = st.file_uploader("Excel masivo", type="xlsx", key="post_xlsx_xls")
    if not (pdf_file and ex_file):
        return

    pdf_bytes = pdf_file.read()
    text = extract_text_from_pdf(pdf_bytes)
    docs = set(ID_RE.findall(text))
    if not docs:
        st.error("No se detectaron identificadores en el PDF. Adjunte un PDF válido.")
        return

    df_raw = pd.read_excel(ex_file, dtype=str)
    mask = df_raw.astype(str).apply(lambda col: col.isin(docs)).any(axis=1)
    df_temp = df_raw.loc[mask].reset_index(drop=True)
    if df_temp.empty:
        st.warning("No se encontraron filas en el Excel que coincidan con los identificadores del PDF.")
        return

    ref_out = df_temp.iloc[:, 7] if df_temp.shape[1] > 7 else pd.Series([""] * len(df_temp))
    nombre_out = df_temp.iloc[:, 3] if df_temp.shape[1] > 3 else (df_temp.iloc[:, 1] if df_temp.shape[1] > 1 else pd.Series([""] * len(df_temp)))

    df_out = pd.DataFrame({
        "dni/cex": df_temp.iloc[:, 0] if df_temp.shape[1] > 0 else pd.Series([""] * len(df_temp)),
        "nombre": nombre_out,
        "importe": df_temp.iloc[:, 12].apply(parse_amount) if df_temp.shape[1] > 12 else pd.Series([0.0] * len(df_temp)),
        "Referencia": ref_out,
    })
    df_out["Estado"] = ESTADO
    df_out["Codigo de Rechazo"] = code
    df_out["Descripcion de Rechazo"] = desc
    df_out = df_out[OUT_COLS]

    cnt, total = len(df_out), df_out["importe"].sum()
    st.write(f"Total transacciones: {cnt} | Suma importes: {total:,.2f}")
    st.dataframe(df_out)

    download_button_for_df(
        df_out,
        key="download_post_bcp_xlsx",
        filename=f"post_bcp_preview_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
    )
    rech_button_and_send(df_out, key="rech_postman_post_bcp_xlsx")

# -------------------- Render pestañas --------------------
def main():
    st.set_page_config(layout="centered", page_title="Rechazos MASIVOS Unificado")
    tabs = st.tabs(["PRE BCP-txt", "-", "rechazo IBK", "POST BCP-xlsx"])
    with tabs[0]:
        tab_pre_bcp_txt()
    with tabs[1]:
        tab_pre_bcp_xlsx()
    with tabs[2]:
        tab_rechazo_ibk()
    with tabs[3]:
        tab_post_bcp_xlsx()

if __name__ == "__main__":
    main()
