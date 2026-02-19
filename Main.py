# streamlit_app.py

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
# NUEVA CONSTANTE para el layout del TXT de Scotiabank
SCO_TXT_POS = {
    "dni": (2, 9),        # Posición del DNI
    "nombre": (14, 73),   # Posición del Nombre
    "importe": (105, 115),  # Posición del Importe
    "referencia": (116, 127), # Posición de Referencia
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

def _find_situacion_column_in_df(df: pd.DataFrame) -> str | None:
    def norm(s: str) -> str:
        return re.sub(r"[^\w]", "", s.strip().lower().replace("ó", "o").replace("í", "i"))
    for col in df.columns:
        if norm(col) == "situacion":
            return col
    return None

def _extract_situaciones_from_pdf(pdf_stream) -> list[str]:
    text = "".join(p.get_text() or "" for p in fitz.open(stream=pdf_stream, filetype="pdf"))
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    situ_lines = [ln for ln in lines if re.search(r"\bsituaci[oó]n\b", ln, flags=re.IGNORECASE)]
    return situ_lines

def _map_situacion_to_code(s: str) -> tuple[str, str]:
    if s is None:
        return "R002", "CUENTA INVALIDA"
    su = s.upper()
    if "CUENTA INEXISTENTE" in su or "INEXISTENTE" in su:
        return "R002", "CUENTA INEXISTENTE"
    if "DOC. NO CORRESPONDE" in su or "DOCUMENTO NO CORRESPONDE" in su or "DOC NO CORRESPONDE" in su:
        return "R001", "DOCUMENTO ERRADO"
    if "CUENTA CANCELADA" in su or "CANCELADA" in su:
        return "R002", "CUENTA CANCELADA"
    return "R002", "CUENTA INVALIDA"
# ... (después de la función _map_situacion_to_code)

def parse_sco_importe(raw: str) -> float:
    """Convierte un importe de TXT Scotiabank (ej. '00000004814') a float."""
    try:
        # Asume que los últimos 2 dígitos son decimales
        return float(raw) / 100.0
    except ValueError:
        return 0.0

def map_sco_pdf_error_to_code(line: str) -> tuple[str | None, str, str]:
    """
    Analiza una línea del PDF de Scotiabank.
    Retorna (dni, code, description) si es un error, o (None, "", "") si está O.K.
    """
    line = line.strip()
    if not line:
        return None, "", ""

    # 1. Buscar el DNI al inicio de la línea
    match = re.search(r"^(\d{8})\b", line)
    if not match:
        return None, "", ""
    
    dni = match.group(1)
    
    # 2. Normalizar la línea para la verificación
    # Convertimos a mayúsculas y reemplazamos caracteres griegos
    check_line = line.upper()
    check_line = check_line.replace("Ο", "O")  # Griego Omicron -> 'O' Latina
    check_line = check_line.replace("Κ", "K")  # Griego Kappa -> 'K' Latina

    # 3. REVISAR ERRORES PRIMERO
    if "CTA ES CTS" in check_line:
        return dni, "R017", "CUENTA DE AFP / CTS"
    
    # 4. REVISAR ÉXITO DESPUÉS
    # Ahora 'check_line.endswith("O.K.")' funcionará para ambas versiones
    if check_line.endswith("O.K."):
        return None, "", ""  # No es un error
    
    # 5. Si no es éxito ni error conocido, es un rechazo genérico
    # Esta regla ya no se basará en mi ejemplo erróneo de "181-0"
    return dni, "R002", "CUENTA INVALIDA"

def map_sco_xls_error_to_code(observation: str) -> tuple[str, str]:
    """Asigna código de rechazo según la columna 'Observación:' del XLS."""
    obs = str(observation).strip()
    
    if "Verificar cuenta y/o documento" in obs:
        return "R001", "DOCUMENTO ERRADO"
    if obs == "Cancelada" or obs == "Verificar cuenta.":
        return "R002", "CUENTA INVALIDA"
    if "Abono AFP" in obs:
        return "R017", "CUENTA DE AFP / CTS"
    
    # Fallback por si aparece una observación nueva
    return "R002", "CUENTA INVALIDA"

# -------------- Flujos --------------
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
                st.warning("No se detectaron filas en el PDF con el patrón 'Registro N'.")
                return
            # proteger índices fuera de rango
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
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
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
    
    # 1. Los botones siguen aquí, ahora definen el CÓDIGO POR DEFECTO
    code, desc = select_code("post_xlsx_code", "R001")
    st.info("Elige un código por defecto. Podrás editar cada fila individualmente en la tabla de resultados.")

    pdf_file = st.file_uploader("PDF de DNIs", type="pdf", key="post_xlsx_pdf")
    ex_file = st.file_uploader("Excel masivo", type="xlsx", key="post_xlsx_xls")
    
    if pdf_file and ex_file:
        with st.spinner("Procesando POST BCP-xlsx…"):
            pdf_bytes = pdf_file.read()
            text = "".join(p.get_text() or "" for p in fitz.open(stream=io.BytesIO(pdf_bytes), filetype="pdf"))
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

            # --- MODIFICACIÓN INICIA ---
            
            # 2. Se crea el DataFrame BASE (solo con los datos extraídos)
            df_out = pd.DataFrame({
                "dni/cex": df_temp.iloc[:, 0],
                "nombre": nombre_out,
                "importe": df_temp.iloc[:, 12].apply(parse_amount) if df_temp.shape[1] > 12 else pd.Series([0.0] * len(df_temp)),
                "Referencia": ref_out,
            })
            
            # 3. Se asigna el CÓDIGO POR DEFECTO a la nueva columna
            df_out["Codigo de Rechazo"] = code
            
            # 4. Obtenemos la lista de códigos válidos para el desplegable
            valid_codes = list(CODE_DESC.keys())

            st.subheader("Registros encontrados (editables)")
            st.caption("Puedes cambiar el 'Código de Rechazo' de cada fila usando el desplegable.")

            # 5. REEMPLAZAMOS st.dataframe POR st.data_editor
            edited_df = st.data_editor(
                df_out,
                column_config={
                    "Codigo de Rechazo": st.column_config.SelectboxColumn(
                        "Código de Rechazo",
                        help="Seleccione un código para esta fila",
                        options=valid_codes,
                        required=True,
                    ),
                    # Configuramos las otras columnas como "deshabilitadas" para evitar editarlas
                    "dni/cex": st.column_config.TextColumn("DNI/CEX", disabled=True),
                    "nombre": st.column_config.TextColumn("Nombre", disabled=True),
                    "importe": st.column_config.NumberColumn("Importe", format="%.2f", disabled=True),
                    "Referencia": st.column_config.TextColumn("Referencia", disabled=True),
                },
                use_container_width=True,
                num_rows="dynamic", # Permite al usuario añadir o eliminar filas si lo necesita
                key="editor_post_bcp"
            )

            # 6. Creamos el DataFrame FINAL basado en las ediciones del usuario
            df_final = edited_df.copy()
            df_final["Estado"] = ESTADO
            
            # 7. APLICAMOS LA DESCRIPCIÓN BASADA EN EL CÓDIGO DE CADA FILA
            df_final["Descripcion de Rechazo"] = df_final["Codigo de Rechazo"].map(CODE_DESC)
            
            # 8. Aseguramos el orden final de las columnas
            df_final = df_final[OUT_COLS]

            # 9. Usamos el 'df_final' (editado) para el resto de operaciones
            cnt, total = _count_and_sum(df_final)
            st.write(f"**Total transacciones:** {cnt}  |  **Suma de importes:** {total:,.2f}")

            # 10. El botón de descarga usará el 'df_final'
            eb = df_to_excel_bytes(df_final)
            st.download_button(
                "Descargar excel de registros",
                eb,
                file_name="post_bcp_xlsx.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

            # 11. El POST usará el 'df_final'
            _validate_and_post(df_final, "post_post_xlsx")
            
def tab_sco_processor():
    st.header("Procesador Scotiabank (Redefinido)")
    st.info("Módulo simplificado: Auditoría de cantidades y Procesamiento de errores por Excel.")

    # 1. Carga de archivos
    col_up1, col_up2, col_up3 = st.columns(3)
    with col_up1:
        pdf_file = st.file_uploader("1. PDF Detalle (Para Auditoría)", type="pdf", key="sco_pdf")
    with col_up2:
        txt_file = st.file_uploader("2. TXT Masivo (Base de datos)", type="txt", key="sco_txt")
    with col_up3:
        xls_file = st.file_uploader("3. XLS Errores (Para Rechazos)", type=["xls", "xlsx", "csv"], key="sco_xls")

    # Variables compartidas
    txt_lines = []
    
    # ---------------------------------------------------------
    # SECCIÓN 1: AUDITORÍA (PDF vs TXT)
    # ---------------------------------------------------------
    if pdf_file and txt_file:
        st.divider()
        st.subheader("📊 Sección 1: Auditoría de Cantidades")
        
        # A. Procesar TXT
        txt_content = txt_file.read().decode("utf-8", errors="ignore")
        # Filtramos líneas vacías para tener el conteo real de registros
        txt_lines = [line for line in txt_content.splitlines() if line.strip()]
        count_txt = len(txt_lines)

        # B. Procesar PDF (Contar "O.K.")
        pdf_bytes = pdf_file.read()
        pdf_text = ""
        with fitz.open(stream=io.BytesIO(pdf_bytes), filetype="pdf") as doc:
            for page in doc:
                pdf_text += page.get_text()
        
        # Normalización de caracteres griegos (Omicron/Kappa) a Latinos
        pdf_text_norm = pdf_text.upper().replace("Ο", "O").replace("Κ", "K")
        
        # Contamos cuántas veces aparece "O.K."
        count_ok_pdf = pdf_text_norm.count("O.K.")

        # C. Mostrar Comparación
        c1, c2, c3 = st.columns(3)
        c1.metric("Registros en TXT", count_txt)
        c2.metric("Confirmaciones 'O.K.' en PDF", count_ok_pdf)
        
        diff = count_txt - count_ok_pdf
        c3.metric("Diferencia", diff, delta_color="inverse")

        if diff == 0:
            st.success("✅ ¡Cuadratura Perfecta! Todos los registros del TXT tienen su 'O.K.' en el PDF.")
        elif diff > 0:
            st.warning(f"⚠️ Hay {diff} registros en el TXT que NO tienen 'O.K.' en el PDF (Posibles rechazos).")
        else:
            st.error(f"🚨 Extraño: Hay más 'O.K.' en el PDF que líneas en el TXT. Revise los archivos.")

    # ---------------------------------------------------------
    # SECCIÓN 2: GENERACIÓN DE RECHAZOS (Desde XLS)
    # ---------------------------------------------------------
    if xls_file and txt_lines:
        st.divider()
        st.subheader("🚫 Sección 2: Generar Rechazos desde XLS")
        
        rows_to_reject = []
        try:
            # Leemos el XLS asumiendo que la cabecera está en la fila 7 (index 6)
            df_xls = pd.read_excel(xls_file, header=6, dtype=str)
            
            # Verificamos que tenga las columnas esperadas
            if "Linea" not in df_xls.columns:
                st.error("El Excel no tiene la columna 'Linea'. Verifique el formato (header=6).")
            else:
                for _, row in df_xls.iterrows():
                    linea_val = row.get("Linea")
                    obs_val = row.get("Observación:")
                    
                    # Validar que sea un número de línea válido
                    if pd.isna(linea_val): 
                        continue
                    
                    try:
                        # El excel trae "129.0", lo convertimos a entero 129
                        line_idx = int(float(linea_val))
                    except ValueError:
                        continue

                    # Validar que la línea exista en el TXT (TXT es base 0, Excel suele ser base 1)
                    # PERO: En tu lógica anterior, usabas el número directo. 
                    # Asumimos que "Linea 1" del Excel corresponde al primer registro del TXT.
                    
                    # Ajuste de índice: Si Excel dice 1, es index 0 del array
                    idx_array = line_idx - 1
                    
                    if 0 <= idx_array < len(txt_lines):
                        raw_line = txt_lines[idx_array]
                        
                        # Extraemos datos del TXT usando tus posiciones fijas
                        dni = slice_fixed(raw_line, *SCO_TXT_POS["dni"])
                        nombre = slice_fixed(raw_line, *SCO_TXT_POS["nombre"])
                        importe = parse_sco_importe(slice_fixed(raw_line, *SCO_TXT_POS["importe"]))
                        # Referencia especial para SCO (116-127)
                        referencia = slice_fixed(raw_line, 116, 127) 
                        
                        # Mapeamos el código de error
                        code, desc = map_sco_xls_error_to_code(obs_val)

                        rows_to_reject.append({
                            "dni/cex": dni,
                            "nombre": nombre,
                            "importe": importe,
                            "Referencia": referencia,
                            "Codigo de Rechazo": code,
                            "Descripcion de Rechazo": desc # Pre-asignamos para mostrar
                        })

        except Exception as e:
            st.error(f"Error al leer el archivo XLS: {e}")
            st.write("Asegúrese de instalar 'xlrd' si es un archivo .xls antiguo.")

        # Mostrar tabla si hay rechazos
        if rows_to_reject:
            df_out = pd.DataFrame(rows_to_reject)
            
            # Preparamos dataframe editable
            valid_codes = list(CODE_DESC.keys())
            
            edited_df = st.data_editor(
                df_out,
                column_config={
                    "Codigo de Rechazo": st.column_config.SelectboxColumn(
                        "Código de Rechazo", options=valid_codes, required=True
                    ),
                    "Descripcion de Rechazo": st.column_config.TextColumn("Descripción (Auto)", disabled=True),
                    "dni/cex": st.column_config.TextColumn("DNI/CEX", disabled=True),
                    "nombre": st.column_config.TextColumn("Nombre", disabled=True),
                    "importe": st.column_config.NumberColumn("Importe", format="%.2f", disabled=True),
                    "Referencia": st.column_config.TextColumn("Referencia", disabled=True),
                },
                use_container_width=True,
                num_rows="dynamic",
                key="editor_sco_simple"
            )
            
            # Preparar salida final
            df_final = edited_df.copy()
            df_final["Estado"] = ESTADO
            # Actualizar descripción por si el usuario cambió el código
            df_final["Descripcion de Rechazo"] = df_final["Codigo de Rechazo"].map(CODE_DESC)
            df_final = df_final[OUT_COLS] # Ordenar columnas

            # Métricas finales
            cnt, total = _count_and_sum(df_final)
            st.write(f"**Total a rechazar:** {cnt} | **Monto Total:** {total:,.2f}")

            # Botones de Acción
            col_b1, col_b2 = st.columns(2)
            with col_b1:
                eb = df_to_excel_bytes(df_final)
                st.download_button("Descargar Excel", eb, "rechazos_sco.xlsx", 
                                 "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", 
                                 use_container_width=True)
            with col_b2:
                _validate_and_post(df_final, "post_sco_simple")
        
        elif xls_file:
            st.info("El archivo XLS se leyó, pero no contenía líneas válidas para rechazar.")

    elif not pdf_file and not txt_file:
        st.info("👆 Carga los archivos arriba para comenzar.")
        
def tab_rechazo_total_txt():
    st.header("Rechazo TOTAL (Banco Inoperativo)")
    st.warning("⚠️ ESTA OPCIÓN RECHAZARÁ TODO EL ARCHIVO TXT CON EL CÓDIGO R020.")

    txt_file = st.file_uploader("Cargar TXT Masivo para rechazar totalmente", type="txt", key="total_txt")
    
    if txt_file:
        with st.spinner("Procesando rechazo total (Formato 2 líneas)..."):
            # Leer el archivo
            content = txt_file.read().decode("utf-8", errors="ignore")
            lines = content.splitlines()
            
            # --- MODIFICACIÓN: Saltar la primera línea (Encabezado) ---
            if len(lines) > 0:
                lines = lines[1:]

            rows = []
            i = 0
            while i < len(lines):
                line1 = lines[i]
                
                # --- LÓGICA DE DETECCIÓN ---
                # Verificamos si en la posición del DNI (25-32) hay números.
                # Índices en Python: 24 al 32
                dni_candidate = line1[24:32].strip()
                
                # Si parece un DNI válido y hay una línea siguiente para el importe
                if len(dni_candidate) >= 6 and dni_candidate.isdigit() and (i + 1) < len(lines):
                    
                    # Capturamos la Línea 2 (la siguiente)
                    line2 = lines[i + 1]
                    
                    # --- EXTRACCIÓN LINEA 1 ---
                    dni = dni_candidate
                    # Nombre del 40 al 80 (índices 39:80)
                    nombre = line1[39:80].strip()
                    # Referencia: 115-126 (índices 114:126)
                    ref = line1[114:126].strip()
                    
                    # --- EXTRACCIÓN LINEA 2 ---
                    # Importe del 26 al 34 (índices 25:34)
                    imp_str = line2[25:34].strip()
                    imp = parse_amount(imp_str)
                    
                    rows.append({
                        "dni/cex": dni,
                        "nombre": nombre,
                        "importe": imp,
                        "Referencia": ref,
                    })
                    
                    # ¡IMPORTANTE! Saltamos 2 líneas (la 1 y la 2 del cliente actual)
                    i += 2
                else:
                    # Si la línea no tiene DNI (es basura o separador), avanzamos solo 1
                    i += 1

            if not rows:
                st.error("No se detectaron registros válidos. Verifique que el archivo no esté vacío.")
                return

            # Crear DataFrame
            df_out = pd.DataFrame(rows)
            
            # Asignar valores fijos para TODO el archivo
            df_out["Estado"] = ESTADO
            df_out["Codigo de Rechazo"] = "R020"
            df_out["Descripcion de Rechazo"] = CODE_DESC["R020"]
            
            # Ordenar columnas
            df_out = df_out[OUT_COLS]

            # Mostrar métricas
            cnt, total = _count_and_sum(df_out)
            st.metric("Total a Rechazar", cnt)
            st.metric("Monto Total", f"{total:,.2f}")

            # Mostrar tabla
            st.dataframe(df_out)

            # Botones de descarga y envío
            eb = df_to_excel_bytes(df_out)
            
            col1, col2 = st.columns(2)
            with col1:
                st.download_button(
                    "Descargar excel de rechazos",
                    eb,
                    file_name="rechazo_total_inoperativo.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True
                )
            with col2:
                _validate_and_post(df_out, "post_total_txt")
# -------------- Render pestañas --------------
tabs = st.tabs([
    "PRE BCP-txt",
    "-", 
    "rechazo IBK",
    "POST BCP-xlsx",
    "Procesador SCO",
    "Rechazo TOTAL",
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
