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
    resp = requests.post(ENDPOINT, files=files)
    return resp.status_code, resp.text

def select_code(key: str, default: str) -> tuple[str, str]:
    if key not in st.session_state:
        st.session_state[key] = default
    _, center, _ = st.columns([1, 2, 1])
    with center:
        b1, b2 = st.columns(2, gap="small")
        if b1.button("R001\nDOCUMENTO ERRADO", key=f"{key}_r001"):
            st.session_state[key] = "R001"
        if b2.button("R002\nCUENTA INVALIDA", key=f"{key}_r002"):
            st.session_state[key] = "R002"
    code = st.session_state[key]
    desc = CODE_DESC[code]
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

def _find_situacion_column_in_df(df: pd.DataFrame) -> str | None:
    # busca variantes de 'situación' en columnas (case-insensitive, sin tildes)
    def norm(s: str) -> str:
        return re.sub(r"[^\w]", "", s.strip().lower().replace("ó", "o").replace("í", "i"))
    for col in df.columns:
        if norm(col) in {"situacion", "situacion"}:
            return col
    return None

def _extract_situaciones_from_pdf(pdf_stream) -> list[str]:
    # retorna una lista de lines que contengan 'situación' o 'situacion', ordenadas por aparición
    text = "".join(p.get_text() or "" for p in fitz.open(stream=pdf_stream, filetype="pdf"))
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    situ_lines = [ln for ln in lines if re.search(r"\bsituaci[oó]n\b", ln, flags=re.IGNORECASE)]
    return situ_lines

def _map_situacion_to_code(s: str) -> tuple[str, str]:
    if s is None:
        return "R002", "CUENTA INVALIDA"
    su = s.upper()
    if "CUENTA INEXISTENTE" in su:
        return "R002", "CUENTA INEXISTENTE"
    if "DOC. NO CORRESPONDE" in su or "DOCUMENTO NO CORRESPONDE" in su or "DOC NO CORRESPONDE" in su:
        return "R001", "DOC. NO CORRESPONDE"
    if "CUENTA CANCELADA" in su:
        return "R002", "CUENTA CANCELADA"
    # por defecto R002 para cualquier otro mensaje
    return "R002", su.strip() if su.strip() else "CUENTA INVALIDA"

# -------------- Flujos --------------
def tab_pre_bcp_xlsx():
    st.header("Antigua manera de rechazar con PDF")
    code, desc = select_code("pre_xlsx_code", "R002")

    pdf_file = st.file_uploader("PDF con filas", type="pdf", key="pre_xlsx_pdf")
    ex_file = st.file_uploader("Excel masivo", type="xlsx", key="pre_xlsx_xls")
    if pdf_file and ex_file:
        with st.spinner("Procesando PRE BCP-xlsx…"):
            text = "".join(p.get_text() or "" for p in fitz.open(
                stream=pdf_file.read(), filetype="pdf"
            ))
            filas = sorted({int(n) + 1 for n in re.findall(r"Registro\s+(\d+)", text)})

            df_raw = pd.read_excel(ex_file, dtype=str)
            df_temp = df_raw.iloc[filas].reset_index(drop=True)

            # referencias internas y de salida
            ref_int = df_temp.iloc[:, 3]   # col D para lógica interna
            ref_out = df_temp.iloc[:, 7]   # col H para output

            # nombres internos y de salida
            nombre_int = df_temp.iloc[:, 1]  # col B para lógica interna
            nombre_out = df_temp.iloc[:, 3]  # col D para output

            df_out = pd.DataFrame({
                "dni/cex": df_temp.iloc[:, 0],
                "nombre": nombre_out,
                "importe": df_temp.iloc[:, 12].apply(parse_amount),
                "Referencia": ref_out,
            })
            df_out["Estado"] = ESTADO
            df_out["Codigo de Rechazo"] = code
            df_out["Descripcion de Rechazo"] = desc
            df_out = df_out[OUT_COLS]

            # contador y suma
            cnt, total = _count_and_sum(df_out)
            st.write(f"**Total transacciones:** {cnt}   |   **Suma de importes:** {total:,.2f}")

            st.dataframe(df_out)

            eb = df_to_excel_bytes(df_out)
            st.download_button(
                "Descargar excel de registros",
                eb,
                file_name="pre_bcp_xlsx.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

            _validate_and_post(df_out, "post_pre_xlsx")

def tab_pre_bcp_txt():
    st.header("PRE BCP-txt")
    code, desc = select_code("pre_txt_code", "R002")

    pdf_file = st.file_uploader("PDF", type="pdf", key="pre_txt_pdf")
    txt_file = st.file_uploader("TXT", type="txt", key="pre_txt_txt")
    if pdf_file and txt_file:
        with st.spinner("Procesando PRE BCP-txt…"):
            text = "".join(p.get_text() or "" for p in fitz.open(
                stream=pdf_file.read(), filetype="pdf"
            ))
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
                else:
                    dni = nombre = ref = ""
                    imp = 0.0
                rows.append({
                    "dni/cex": dni,
                    "nombre": nombre,
                    "importe": imp,
                    "Referencia": ref,
                })

            df_out = pd.DataFrame(rows)[["dni/cex", "nombre", "importe", "Referencia"]]
            df_out["Estado"] = ESTADO
            df_out["Codigo de Rechazo"] = code
            df_out["Descripcion de Rechazo"] = desc
            df_out = df_out[OUT_COLS]

            cnt, total = _count_and_sum(df_out)
            st.write(f"**Total transacciones:** {cnt}   |   **Suma de importes:** {total:,.2f}")

            st.dataframe(df_out)

            eb = df_to_excel_bytes(df_out)
            st.download_button(
                "Descargar excel de registros",
                eb,
                file_name="pre_bcp_txt.xlsx",
                mime="application/vnd.openxmlformats-officedocument-spreadsheetml.sheet",
            )

            _validate_and_post(df_out, "post_pre_txt")

def tab_rechazo_ibk():
    st.header("rechazo IBK")

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
            # mapa conservador para IBK (igual que antes)
            df_out["Estado"] = ESTADO
            df_out["Codigo de Rechazo"] = [
                "R016" if any(k in str(o).lower() for k in KEYWORDS_NO_TIT) else "R002"
                for o in df_valid.iloc[:, 14]
            ]
            df_out["Descripcion de Rechazo"] = [
                "CLIENTE NO TITULAR DE LA CUENTA" if any(k in str(o).lower() for k in KEYWORDS_NO_TIT)
                else "CUENTA INVALIDA"
                for o in df_valid.iloc[:, 14]
            ]
            df_out = df_out[OUT_COLS]

            cnt, total = _count_and_sum(df_out)
            st.write(f"**Total transacciones:** {cnt}   |   **Suma de importes:** {total:,.2f}")

            st.dataframe(df_out)

            eb = df_to_excel_bytes(df_out)
            st.download_button(
                "Descargar excel de registros",
                eb,
                file_name="rechazo_ibk.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

            _validate_and_post(df_out, "post_ibk")

def tab_post_bcp_xlsx():
    st.header("POST BCP-xlsx")
    code, desc = select_code("post_xlsx_code", "R001")

    pdf_file = st.file_uploader("PDF de DNIs", type="pdf", key="post_xlsx_pdf")
    ex_file = st.file_uploader("Excel masivo", type="xlsx", key="post_xlsx_xls")
    if pdf_file and ex_file:
        with st.spinner("Procesando POST BCP-xlsx…"):
            text = "".join(p.get_text() or "" for p in fitz.open(
                stream=pdf_file.read(), filetype="pdf"
            ))
            docs = set(re.findall(r"\b\d{6,}\b", text))

            df_raw = pd.read_excel(ex_file, dtype=str)
            mask = df_raw.astype(str).apply(lambda col: col.isin(docs)).any(axis=1)
            df_temp = df_raw.loc[mask].reset_index(drop=True)

            # referencias internas y de salida
            ref_int = df_temp.iloc[:, 3]   # col D para lógica interna
            ref_out = df_temp.iloc[:, 7]   # col H para output

            # nombres internos y de salida
            nombre_int = df_temp.iloc[:, 1]  # col B para lógica interna
            nombre_out = df_temp.iloc[:, 3]  # col D para output

            df_out = pd.DataFrame({
                "dni/cex": df_temp.iloc[:, 0],
                "nombre": nombre_out,
                "importe": df_temp.iloc[:, 12].apply(parse_amount),
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
            st.download_button(
                "Descargar excel de registros",
                eb,
                file_name="post_bcp_xlsx.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

            _validate_and_post(df_out, "post_post_xlsx")

def tab_pre_bbva_xlsx():
    # misma lógica que POST BCP-xlsx pero mapeo de 'situación' para códigos
    st.header("PRE BBVA-xlsx")
    code, _ = select_code("pre_bbva_code", "R002")  # default en UI, pero se sobrescribe por situacion
    pdf_file = st.file_uploader("PDF con Situación", type="pdf", key="pre_bbva_pdf")
    ex_file = st.file_uploader("Excel masivo", type="xlsx", key="pre_bbva_xls")
    if pdf_file and ex_file:
        with st.spinner("Procesando PRE BBVA-xlsx…"):
            # intento leer situaciones desde el DataFrame primero
            df_raw = pd.read_excel(ex_file, dtype=str)
            df_temp = df_raw.reset_index(drop=True)

            # prioridad: buscar columna 'situación' en el excel
            situ_col = _find_situacion_column_in_df(df_temp)
            situaciones = None
            if situ_col:
                situaciones = df_temp[situ_col].astype(str).fillna("").tolist()
            else:
                # fallback: extraer líneas del PDF que mencionen 'situación'
                situ_lines = _extract_situaciones_from_pdf(pdf_file.read())
                # tomar la parte después de ':' si existe, o la línea completa; repetir/trim
                situaciones = []
                for ln in situ_lines:
                    m = re.split(r":", ln, maxsplit=1)
                    situaciones.append(m[1].strip() if len(m) > 1 else ln.strip())
                # si no encontramos ninguna situación en el pdf, rellenamos con empty
                if not situaciones:
                    situaciones = [""] * len(df_temp)

            # ahora aplicamos match por filas: asumimos 1:1 entre df_temp rows y situaciones
            # si hay menos situaciones que filas, rellenamos con empty
            if len(situaciones) < len(df_temp):
                situaciones = situaciones + [""] * (len(df_temp) - len(situaciones))
            situaciones = situaciones[: len(df_temp)]

            # referencias internas y de salida (como en POST)
            ref_int = df_temp.iloc[:, 3] if df_temp.shape[1] > 3 else pd.Series([""] * len(df_temp))
            ref_out = df_temp.iloc[:, 7] if df_temp.shape[1] > 7 else pd.Series([""] * len(df_temp))

            # nombres internos y de salida
            nombre_int = df_temp.iloc[:, 1] if df_temp.shape[1] > 1 else pd.Series([""] * len(df_temp))
            nombre_out = df_temp.iloc[:, 3] if df_temp.shape[1] > 3 else nombre_int

            # construir df_out
            df_out = pd.DataFrame({
                "dni/cex": df_temp.iloc[:, 0] if df_temp.shape[1] > 0 else pd.Series([""] * len(df_temp)),
                "nombre": nombre_out,
                "importe": df_temp.iloc[:, 12].apply(parse_amount) if df_temp.shape[1] > 12 else pd.Series([0.0] * len(df_temp)),
                "Referencia": ref_out,
            })

            # construir códigos/descripciones a partir de 'situaciones'
            cods = []
            descs = []
            for s in situaciones:
                code_m, desc_m = _map_situacion_to_code(s)
                cods.append(code_m)
                descs.append(desc_m)

            df_out["Estado"] = ESTADO
            df_out["Codigo de Rechazo"] = cods
            df_out["Descripcion de Rechazo"] = descs
            df_out = df_out[OUT_COLS]

            cnt, total = _count_and_sum(df_out)
            st.write(f"**Total transacciones:** {cnt}   |   **Suma de importes:** {total:,.2f}")

            st.dataframe(df_out)

            eb = df_to_excel_bytes(df_out)
            st.download_button(
                "Descargar excel de registros",
                eb,
                file_name="pre_bbva_xlsx.xlsx",
                mime="application/vnd.openxmlformats-officedocument-spreadsheetml.sheet",
            )

            _validate_and_post(df_out, "post_pre_bbva_xlsx")

# -------------- Render pestañas --------------
tabs = st.tabs([
    "PRE BCP-txt",
    "-",  # Antigua manera de rechazar con PDF
    "PRE BBVA-xlsx",
    "rechazo IBK",
    "POST BCP-xlsx",
])

with tabs[0]:
    tab_pre_bcp_txt()
with tabs[1]:
    tab_pre_bcp_xlsx()
with tabs[2]:
    tab_pre_bbva_xlsx()
with tabs[3]:
    tab_rechazo_ibk()
with tabs[4]:
    tab_post_bcp_xlsx()
