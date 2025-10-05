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

# Tipos globales
CODE_DESC = {
    "R001": "DOCUMENTO ERRADO",
    "R002": "CUENTA INVALIDA",
    "R007": "RECHAZO POR CCI",
}

# BBVA keywords solicitados
BBVA_KEYWORDS = {
    "R001": ["DOC. NO CORRESPONDE"],
    "R002": ["CUENTA INEXISTENTE", "CTA C/ERR NO IDENTIF"],
    "R007": ["REGISTRO CON ERRORES", "CUENTA NO ENCONTRADA"],
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

def _find_situacion_column_in_df(df: pd.DataFrame) -> str | None:
    def norm(s: str) -> str:
        return re.sub(r"[^\w]", "", s.strip().lower().replace("ó", "o").replace("í", "i"))
    for col in df.columns:
        if norm(col) == "situacion":
            return col
    return None

def _extract_text_from_pdf_bytes(pdf_bytes: bytes) -> str:
    if fitz is None:
        return ""
    try:
        return "".join(p.get_text() or "" for p in fitz.open(stream=io.BytesIO(pdf_bytes), filetype="pdf"))
    except Exception:
        return ""

def _extract_id_situ_pairs_from_pdf_text(text: str) -> dict:
    """
    Intenta extraer pares identificador -> situacion desde el texto del PDF.
    """
    pairs = {}
    if not text:
        return pairs

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    id_pattern = re.compile(r"\b\d{6,}\b")
    situ_pattern = re.compile(r"\bsituaci[oó]n\b", flags=re.IGNORECASE)

    for idx, ln in enumerate(lines):
        if situ_pattern.search(ln):
            parts = re.split(r":", ln, maxsplit=1)
            situ_val = parts[1].strip() if len(parts) > 1 else ln.strip()
            ids_here = id_pattern.findall(ln)
            if ids_here:
                for i in ids_here:
                    pairs[i] = situ_val
                continue
            found = False
            for rel in (-2, -1, 1, 2):
                ni = idx + rel
                if 0 <= ni < len(lines):
                    ids_near = id_pattern.findall(lines[ni])
                    if ids_near:
                        for i in ids_near:
                            pairs[i] = situ_val
                        found = True
                        break
            if not found:
                ids_in_situ = id_pattern.findall(situ_val)
                if ids_in_situ:
                    for i in ids_in_situ:
                        pairs[i] = re.sub(r"\b\d{6,}\b", "", situ_val).strip()
    return pairs

def _map_situacion_to_code_bbva(s: str) -> tuple[str, str]:
    if s is None:
        return "R002", CODE_DESC["R002"]
    su = re.sub(r"\s+", " ", s.strip().upper())
    for kw in BBVA_KEYWORDS["R001"]:
        if kw in su:
            return "R001", CODE_DESC["R001"]
    for kw in BBVA_KEYWORDS["R007"]:
        if kw in su:
            return "R007", CODE_DESC["R007"]
    for kw in BBVA_KEYWORDS["R002"]:
        if kw in su:
            return "R002", CODE_DESC["R002"]
    return "R002", CODE_DESC["R002"]

# -------------- Flujos --------------
def tab_pre_bcp_xlsx():
    st.header("Antigua manera de rechazar con PDF")
    code, desc = select_code("pre_xlsx_code", "R002")

    pdf_file = st.file_uploader("PDF con filas", type="pdf", key="pre_xlsx_pdf")
    ex_file = st.file_uploader("Excel masivo", type="xlsx", key="pre_xlsx_xls")
    if pdf_file and ex_file:
        with st.spinner("Procesando PRE BCP-xlsx…"):
            pdf_bytes = pdf_file.read()
            text = _extract_text_from_pdf_bytes(pdf_bytes)
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
            pdf_bytes = pdf_file.read()
            text = _extract_text_from_pdf_bytes(pdf_bytes)
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

            if not rows:
                df_out = pd.DataFrame(columns=["dni/cex", "nombre", "importe", "Referencia"])
            else:
                df_out = pd.DataFrame(rows)
            df_out = df_out.reindex(columns=["dni/cex", "nombre", "importe", "Referencia"])

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
            df_out["Estado"] = ESTADO
            # Conservador: IBK mantiene R016 para no-titulares; si deseas limitar a los 3 globales, cambia aquí
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
                mime="application/vnd.openxmlformats-officedocument-spreadsheetml.sheet",
            )

            _validate_and_post(df_out, "post_ibk")

def tab_post_bcp_xlsx():
    st.header("POST BCP-xlsx")
    code, desc = select_code("post_xlsx_code", "R001")

    pdf_file = st.file_uploader("PDF de DNIs", type="pdf", key="post_xlsx_pdf")
    ex_file = st.file_uploader("Excel masivo", type="xlsx", key="post_xlsx_xls")
    if pdf_file and ex_file:
        with st.spinner("Procesando POST BCP-xlsx…"):
            pdf_bytes = pdf_file.read()
            text = _extract_text_from_pdf_bytes(pdf_bytes)
            docs = set(re.findall(r"\b\d{6,}\b", text))

            df_raw = pd.read_excel(ex_file, dtype=str)
            if docs:
                mask = df_raw.astype(str).apply(lambda col: col.isin(docs)).any(axis=1)
                df_temp = df_raw.loc[mask].reset_index(drop=True)
            else:
                st.error("No se detectaron identificadores en el PDF. Adjunte un PDF válido.")
                return

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
            st.download_button(
                "Descargar excel de registros",
                eb,
                file_name="post_bcp_xlsx.xlsx",
                mime="application/vnd.openxmlformats-officedocument-spreadsheetml.sheet",
            )

            _validate_and_post(df_out, "post_post_xlsx")

# --- Reemplazar/insertar en tu streamlit_app.py: funciones utilitarias y tab_bbva actualizado ---

# tolerancia ampliada para ids
ID_RE_PATTERN = re.compile(r"\b\d{6,9}\b")

def _find_situacion_column_in_df(df: pd.DataFrame) -> str | None:
    """
    Busca variantes comunes del encabezado 'situacion' (tildes, :, paréntesis, sufijos).
    """
    def norm(s: str) -> str:
        return re.sub(r"[^\w]", "", str(s).strip().lower().replace("ó", "o").replace("í", "i"))
    for col in df.columns:
        n = norm(col)
        if n == "situacion" or n.startswith("situacion"):
            return col
    # aceptar variantes con palabra situacion en cualquier parte
    for col in df.columns:
        if "situac" in str(col).lower():
            return col
    return None

def _extract_id_situ_pairs_from_pdf_text(text: str) -> dict:
    """
    Heurística mejorada:
    - buscar líneas que contengan 'situaci' (tolerante)
    - buscar ids con el patrón ID_RE_PATTERN en la misma línea o en líneas adyacentes (-2..+2)
    - devolver map id -> situacion_text (limpio)
    """
    pairs = {}
    if not text:
        return pairs
    lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
    situ_pattern = re.compile(r"\bsituaci", flags=re.IGNORECASE)
    for idx, ln in enumerate(lines):
        if situ_pattern.search(ln):
            # tomar parte después de ":" si existe
            parts = re.split(r":", ln, maxsplit=1)
            situ_val = parts[1].strip() if len(parts) > 1 else ln.strip()
            ids_here = ID_RE_PATTERN.findall(ln)
            if ids_here:
                for i in ids_here:
                    pairs[i] = situ_val
                continue
            # buscar ids en líneas cercanas
            found = False
            for rel in (-2, -1, 1, 2):
                ni = idx + rel
                if 0 <= ni < len(lines):
                    ids_near = ID_RE_PATTERN.findall(lines[ni])
                    if ids_near:
                        for i in ids_near:
                            pairs[i] = situ_val
                        found = True
                        break
            if not found:
                # intentar extraer id dentro de situ_val
                ids_in_situ = ID_RE_PATTERN.findall(situ_val)
                if ids_in_situ:
                    for i in ids_in_situ:
                        cleaned = re.sub(ID_RE_PATTERN, "", situ_val).strip()
                        pairs[i] = cleaned
    return pairs

# Tab BBVA con diagnóstico
def tab_bbva():
    st.header("BBVA")
    code_ui, desc_ui = select_code("bbva_code", "R002")

    pdf_file = st.file_uploader("PDF de DNIs (debe contener columna Situación)", type="pdf", key="bbva_pdf")
    ex_file = st.file_uploader("Excel masivo", type="xlsx", key="bbva_xls")
    enable_diag = st.checkbox("Mostrar diagnósticos (texto extraído, encabezados, map id→situación)", value=True)

    if pdf_file and ex_file:
        with st.spinner("Procesando BBVA…"):
            pdf_bytes = pdf_file.read()
            text = _extract_text_from_pdf_bytes(pdf_bytes)

            # Diagnóstico: mostrar texto parcial si está habilitado
            if enable_diag:
                st.subheader("Diagnóstico: texto extraído (primeros 8000 chars)")
                st.text(text[:8000])

            # líneas que contienen 'situaci' para inspección
            situ_lines = [ln for ln in text.splitlines() if re.search(r"situa", ln, flags=re.IGNORECASE)]
            if enable_diag:
                st.subheader("Líneas detectadas con 'situaci'")
                st.write(situ_lines[:50])

            docs = set(ID_RE_PATTERN.findall(text))

            df_raw = pd.read_excel(ex_file, dtype=str)
            if not docs:
                st.error("No se detectaron identificadores en el PDF. Adjunte un PDF válido.")
                if enable_diag:
                    st.warning("IDs detectados: [] -- revise el texto extraído arriba.")
                return

            mask = df_raw.astype(str).apply(lambda col: col.isin(docs)).any(axis=1)
            df_temp = df_raw.loc[mask].reset_index(drop=True)
            if df_temp.empty:
                st.warning("No se encontraron filas en el Excel que coincidan con los identificadores del PDF.")
                if enable_diag:
                    st.write("IDs detectados:", sorted(list(docs))[:50])
                    st.write("Encabezados Excel:", list(df_raw.columns))
                return

            if enable_diag:
                st.subheader("Encabezados del DataFrame filtrado (df_temp)")
                st.write(list(df_temp.columns))

            # Extraer id->situacion desde el PDF (preferible)
            id_situ_map = _extract_id_situ_pairs_from_pdf_text(text)
            if enable_diag:
                st.subheader("Mapa id -> situacion detectado")
                st.write(id_situ_map)

            # Si no hay pares, intentar columna 'Situación' en el Excel filtrado
            situ_col = _find_situacion_column_in_df(df_temp)
            if enable_diag:
                st.write("Columna 'Situación' detectada en df_temp:", situ_col)

            situaciones_alineadas = []
            situ_source = None
            if id_situ_map:
                # asignar situacion por matching de identificador en cada fila del df_temp
                for _, row in df_temp.iterrows():
                    matched = ""
                    for cell in row.astype(str).values:
                        ids_here = ID_RE_PATTERN.findall(cell)
                        found_id = None
                        for iid in ids_here:
                            if iid in id_situ_map:
                                found_id = iid
                                break
                        if found_id:
                            matched = id_situ_map.get(found_id, "")
                            break
                    situaciones_alineadas.append(matched)
                situ_source = "pdf_pairs"
            elif situ_col:
                situaciones_alineadas = df_temp[situ_col].astype(str).fillna("").tolist()
                situ_source = "excel_column"
            else:
                # diagnóstico final antes de abortar
                st.error("No se encontró la columna 'Situación' en el Excel filtrado ni pares identificador→situación en el PDF. El PDF debe contener la columna 'Situación'.")
                if enable_diag:
                    st.info("Diagnóstico resumen:")
                    st.write("- IDs detectados:", sorted(list(docs))[:50])
                    st.write("- Líneas con 'situaci' (muestras):", situ_lines[:20])
                    st.write("- Encabezados df_temp:", list(df_temp.columns))
                    st.write("- id_situ_map (size):", len(id_situ_map))
                return

            # Alineamiento de longitud
            if len(situaciones_alineadas) < len(df_temp):
                situaciones_alineadas += [""] * (len(df_temp) - len(situaciones_alineadas))
            situaciones_alineadas = situaciones_alineadas[: len(df_temp)]

            ref_out = df_temp.iloc[:, 7] if df_temp.shape[1] > 7 else pd.Series([""] * len(df_temp))
            nombre_out = df_temp.iloc[:, 3] if df_temp.shape[1] > 3 else (df_temp.iloc[:, 1] if df_temp.shape[1] > 1 else pd.Series([""] * len(df_temp)))
            dni_out = df_temp.iloc[:, 0] if df_temp.shape[1] > 0 else pd.Series([""] * len(df_temp))

            df_out = pd.DataFrame({
                "dni/cex": dni_out,
                "nombre": nombre_out,
                "importe": df_temp.iloc[:, 12].apply(parse_amount) if df_temp.shape[1] > 12 else pd.Series([0.0] * len(df_temp)),
                "Referencia": ref_out,
            })

            # Mapear situación a código y descripción estandarizados
            cods = []
            descs = []
            for s in situaciones_alineadas:
                if s and s.strip():
                    code_m, desc_m = _map_situacion_to_code_bbva(s)
                else:
                    code_m, desc_m = code_ui, desc_ui
                cods.append(code_m)
                descs.append(desc_m)

            df_out["Estado"] = ESTADO
            df_out["Codigo de Rechazo"] = cods
            df_out["Descripcion de Rechazo"] = descs
            df_out = df_out[OUT_COLS]

            cnt, total = _count_and_sum(df_out)
            counts_by_code = df_out["Codigo de Rechazo"].value_counts().to_dict()
            st.write(f"**Total transacciones:** {cnt}   |   **Suma de importes:** {total:,.2f}")
            st.write("Asignación por código:", counts_by_code)
            st.write("Fuente de situaciones usada:", situ_source)

            st.dataframe(df_out)

            eb = df_to_excel_bytes(df_out)
            st.download_button(
                "Descargar excel de registros",
                eb,
                file_name="bbva_rechazos_diagnostic.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

            _validate_and_post(df_out, "post_bbva")

# -------------- Render pestañas --------------
tabs = st.tabs([
    "PRE BCP-txt",
    "-", 
    "rechazo IBK",
    "POST BCP-xlsx",
    "BBVA",
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
    tab_bbva()
