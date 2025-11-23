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
    st.header("Procesador Scotiabank (PDF + TXT + XLS)")
    st.info("Este tab cruza 3 archivos para identificar rechazos y permite la edición final.")

    # 1. Carga de archivos
    pdf_file = st.file_uploader("PDF Detalle de orden", type="pdf", key="sco_pdf")
    txt_file = st.file_uploader("TXT Masivo", type="txt", key="sco_txt")
    xls_file = st.file_uploader("XLS Errores encontrados (Opcional)", type=["xls", "xlsx", "csv"], key="sco_xls")

    # --- NUEVO: Interruptor para mostrar el log de lectura ---
    show_debug = st.toggle("🛠️ Mostrar log de lectura del PDF (Debug)", value=False) 

    if not (pdf_file and txt_file):
        st.caption("Por favor, cargue al menos los archivos PDF y TXT.")
        return

    with st.spinner("Procesando archivos de Scotiabank..."):
        
        # --- Tareas de Extracción y Resumen (Usando fitz) ---
        pdf_bytes = pdf_file.read()
        try:
            pdf_text_fitz = "".join(p.get_text() or "" for p in fitz.open(stream=io.BytesIO(pdf_bytes), filetype="pdf"))
        except Exception as e:
            st.error(f"Error al leer el texto del PDF con fitz: {e}")
            return

        st.subheader("Resumen de la Orden (PDF)")
        col1, col2 = st.columns(2)
        
        # Columna 1
        with col1:
            orden_match = re.search(r"Detalle de orden No\.\s+(\d+)", pdf_text_fitz)
            orden_fija = f"9242{orden_match.group(1)}" if orden_match else "No encontrado"
            st.text_input("Nro. Orden (Formato Fijo)", orden_fija, key="sco_orden")
        
        # Columna 2
        with col2:
            cantidad_match = re.search(r"Total de la orden\s+([\d,\.]+)", pdf_text_fitz)
            cantidad_str = cantidad_match.group(1) if cantidad_match else "No encontrado"
            
            monto_match = re.search(r"Total de la orden\s+[\d,\.]+\s+([\d,\.]+)", pdf_text_fitz)
            monto_str = f"S/ {monto_match.group(1)}" if monto_match else "No encontrado"

            if monto_str == "No encontrado" and cantidad_str != "No encontrado":
                monto_str = f"S/ {cantidad_str}"
                cantidad_str = "N/A"

            st.text_input("Cantidad de Ordenes", cantidad_str, key="sco_cantidad")
            st.text_input("Monto Total de Orden", monto_str, key="sco_total")

        # --- Preparación de datos TXT ---
        txt_lines = txt_file.read().decode("utf-8", errors="ignore").splitlines()
        
        dni_map = {
            slice_fixed(line, *SCO_TXT_POS["dni"]): line 
            for line in txt_lines if line.strip()
        }
        line_num_map = {
            i + 1: line 
            for i, line in enumerate(txt_lines) if line.strip()
        }
        
        rows_to_reject = []
        dnis_not_in_txt = set()
        
        # --- Variable para guardar el log del PDF ---
        debug_log = [] # <--- DEBUG: Iniciamos lista vacía

        # --- Fuente A: Errores desde el PDF (Usando pdfplumber) ---
        try:
            pdf_file.seek(0)
            
            with pdfplumber.open(pdf_file) as pdf:
                for i, page in enumerate(pdf.pages):
                    table = page.extract_table()
                    if not table:
                        if show_debug: debug_log.append(f"[Página {i+1}] No se encontró tabla.")
                        continue  
                    
                    if show_debug: debug_log.append(f"--- [Página {i+1}] Iniciando lectura de tabla ---")

                    for row in table:
                        # Saltar filas vacías o cabeceras
                        if not row or str(row[0]).startswith("Documento"):
                            if show_debug: debug_log.append(f"SKIP (Cabecera/Vacío): {row}")
                            continue
                        
                        dni = str(row[0]).replace("\n", "")
                        
                        # Determinar estado crudo
                        estado_raw = ""
                        col_idx = -1 # Para saber de qué columna sacamos el dato
                        
                        if len(row) >= 6:
                            estado_raw = str(row[5]).replace("\n", " ")
                            col_idx = 6
                        elif len(row) == 5:
                            estado_raw = str(row[4]).replace("\n", " ")
                            col_idx = 5
                        else:
                            if show_debug: debug_log.append(f"SKIP (Columnas inusuales len={len(row)}): {row}")
                            continue 

                        # Normalizar
                        estado_norm = estado_raw.upper().replace("Ο", "O").replace("Κ", "K")

                        # --- LÓGICA DE DECISIÓN Y LOGGING ---
                        if "O.K." in estado_norm:
                            if show_debug: debug_log.append(f"OK (Ignorado): DNI={dni} | EstadoLeido='{estado_raw}'")
                            continue
                        
                        code, desc = "R002", "CUENTA INVALIDA"
                        tipo_error = "GENÉRICO"
                        
                        if "CTA ES CTS" in estado_norm:
                            code, desc = "R017", "CUENTA DE AFP / CTS"
                            tipo_error = "CTS"
                        
                        # Log del error encontrado
                        if show_debug: 
                            debug_log.append(f"🔴 ERROR DETECTADO ({tipo_error}): DNI={dni} | EstadoLeido='{estado_raw}' | Code={code}")

                        # Buscar en TXT
                        if dni in dni_map:
                            txt_line = dni_map[dni]
                            rows_to_reject.append({
                                "dni/cex": dni,
                                "nombre": slice_fixed(txt_line, *SCO_TXT_POS["nombre"]),
                                "importe": parse_sco_importe(slice_fixed(txt_line, *SCO_TXT_POS["importe"])),
                                "Referencia": slice_fixed(txt_line, *SCO_TXT_POS["referencia"]),
                                "Codigo de Rechazo": code,
                                "Fuente": "PDF"
                            })
                        else:
                            dnis_not_in_txt.add(dni)
                            if show_debug: debug_log.append(f"⚠️ ADVERTENCIA: DNI {dni} no encontrado en TXT.")
        
        except Exception as e:
            st.error(f"Error fatal al procesar la tabla del PDF con pdfplumber: {e}")
            return

        # --- MOSTRAR EL LOG SI ESTÁ ACTIVADO ---
        if show_debug:
            st.divider()
            st.subheader("🛠️ Log de Lectura del PDF")
            st.text_area(
                "Contenido leído línea por línea:", 
                value="\n".join(debug_log), 
                height=300
            )
            st.divider()

        # --- Advertencias de DNI ---
        if dnis_not_in_txt:
            st.warning("⚠️ **Advertencia:** Se encontraron DNIs en el PDF que no existen en el archivo TXT.")
            with st.expander("Ver DNIs no encontrados en el TXT"):
                st.write(sorted(list(dnis_not_in_txt)))

        # --- Fuente B: XLS (Opcional) ---
        if xls_file:
            try:
                # st.caption("Procesando archivo XLS opcional...") # Comentado para limpiar UI
                df_xls = pd.read_excel(xls_file, header=6, dtype=str)
                
                for _, row in df_xls.iterrows():
                    line_num_str = row.iloc[0]
                    if pd.isna(line_num_str): continue
                    try: line_num = int(float(line_num_str))
                    except ValueError: continue 

                    observation = row.iloc[3]
                    if line_num in line_num_map:
                        txt_line = line_num_map[line_num]
                        code, desc = map_sco_xls_error_to_code(observation)
                        
                        rows_to_reject.append({
                            "dni/cex": slice_fixed(txt_line, *SCO_TXT_POS["dni"]),
                            "nombre": slice_fixed(txt_line, *SCO_TXT_POS["nombre"]),
                            "importe": parse_sco_importe(slice_fixed(txt_line, *SCO_TXT_POS["importe"])),
                            "Referencia": slice_fixed(txt_line, 116, 127),
                            "Codigo de Rechazo": code,
                            "Fuente": "XLS"
                        })
            except Exception as e:
                st.warning(f"No se pudo leer el archivo XLS (opcional): {e}")

        # --- Resultado Final ---
        if not rows_to_reject:
            st.success("Proceso completado. No se encontraron registros para rechazar.")
            return

        df_out = pd.DataFrame(rows_to_reject)
        df_out = df_out.drop_duplicates(subset=["dni/cex"], keep="last")
        
        st.subheader("Registros a Rechazar (Editables)")
        
        valid_codes = list(CODE_DESC.keys())
        
        edited_df = st.data_editor(
            df_out,
            column_config={
                "Codigo de Rechazo": st.column_config.SelectboxColumn("Código de Rechazo", options=valid_codes, required=True),
                "Fuente": st.column_config.TextColumn("Fuente", disabled=True),
                "dni/cex": st.column_config.TextColumn("DNI/CEX", disabled=True),
                "nombre": st.column_config.TextColumn("Nombre", disabled=True),
                "importe": st.column_config.NumberColumn("Importe", format="%.2f", disabled=True),
                "Referencia": st.column_config.TextColumn("Referencia", disabled=True),
            },
            use_container_width=True,
            num_rows="dynamic",
            key="editor_sco"
        )
        
        df_final = edited_df.copy()
        df_final["Estado"] = ESTADO
        df_final["Descripcion de Rechazo"] = df_final["Codigo de Rechazo"].map(CODE_DESC)
        df_final = df_final[OUT_COLS]

        cnt, total = _count_and_sum(df_final)
        st.write(f"**Total transacciones a rechazar:** {cnt}  |  **Suma de importes:** {total:,.2f}")

        eb = df_to_excel_bytes(df_final)
        
        col1, col2 = st.columns(2)
        with col2:
            st.download_button("Descargar excel de rechazos", eb, file_name="rechazos_sco.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
        with col1:
            _validate_and_post(df_final, "post_sco")
# -------------- Render pestañas --------------
tabs = st.tabs([
    "PRE BCP-txt",
    "-", 
    "rechazo IBK",
    "POST BCP-xlsx",
    "Procesador SCO",
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
