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
    if st.button("RECH-POSTMAN", key=button_key, use_container_width=True):
        payload = df[SUBSET_COLS]
        excel_bytes = df_to_excel_bytes(payload)
        status, resp = post_to_endpoint(excel_bytes)
        st.success(f"{status}: {resp}")

def _count_and_sum(df: pd.DataFrame) -> tuple[int, float]:
    cnt = len(df)
    total = df["importe"].sum() if "importe" in df.columns else 0.0
    return cnt, total

def render_final_output(df: pd.DataFrame, file_name: str, post_key: str, editor_key: str, show_df: bool = True):
    """
    Función DRY que centraliza el cálculo de totales, dibujo de la tabla editable
    y la creación de los botones de Excel y POST.
    """
    valid_codes = list(CODE_DESC.keys())
    st.subheader("Registros a procesar (Editables)")
    st.caption("Puedes modificar los datos, cambiar el 'Código de Rechazo' o añadir/eliminar filas usando las casillas de la izquierda.")

    edited_df = st.data_editor(
        df,
        column_config={
            "Codigo de Rechazo": st.column_config.SelectboxColumn(
                "Código de Rechazo", options=valid_codes, required=True
            ),
            "Descripcion de Rechazo": st.column_config.TextColumn("Descripción (Auto)", disabled=True),
            "dni/cex": st.column_config.TextColumn("DNI/CEX"), # Ya no está bloqueado
            "nombre": st.column_config.TextColumn("Nombre"),   # Ya no está bloqueado
            "importe": st.column_config.NumberColumn("Importe", format="%.2f"), # Ya no está bloqueado
            "Referencia": st.column_config.TextColumn("Referencia"), # Ya no está bloqueado
            "Estado": st.column_config.TextColumn("Estado", disabled=True),
        },
        use_container_width=True,
        num_rows="dynamic",
        key=editor_key
    )
    
    # Actualizar descripciones por si el usuario cambió el código
    df_final = edited_df.copy()
    if "Codigo de Rechazo" in df_final.columns:
        df_final["Descripcion de Rechazo"] = df_final["Codigo de Rechazo"].map(CODE_DESC)
    
    cnt, total = _count_and_sum(df_final)
    st.write(f"**Total transacciones:** {cnt}   |   **Suma de importes:** {total:,.2f}")
        
    eb = df_to_excel_bytes(df_final)
    
    col1, col2 = st.columns(2)
    with col1:
        st.download_button(
            "Descargar excel de registros",
            eb,
            file_name=file_name,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )
    with col2:
        _validate_and_post(df_final, post_key)

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

            render_final_output(df_out, "pre_bcp_xlsx.xlsx", "post_pre_xlsx", "editor_pre_xlsx")

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

            render_final_output(df_out, "pre_bcp_txt.xlsx", "post_pre_txt", "editor_pre_txt")

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

            render_final_output(df_out, "rechazo_ibk.xlsx", "post_ibk", "editor_ibk")

def tab_post_bcp_xlsx():
    st.header("POST BCP-xlsx")
    
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

            render_final_output(df_out, "post_bcp_xlsx.xlsx", "post_post_xlsx", "editor_post_bcp")
            
def tab_sco_processor():
    st.header("Procesador Scotiabank (Redefinido)")
    st.info("Módulo simplificado: Auditoría de cantidades y Procesamiento de errores por Excel.")

    col_up1, col_up2, col_up3 = st.columns(3)
    with col_up1:
        pdf_file = st.file_uploader("1. PDF Detalle (Para Auditoría)", type="pdf", key="sco_pdf")
    with col_up2:
        txt_file = st.file_uploader("2. TXT Masivo (Base de datos)", type="txt", key="sco_txt")
    with col_up3:
        xls_file = st.file_uploader("3. XLS Errores (Para Rechazos)", type=["xls", "xlsx", "csv"], key="sco_xls")

    txt_lines = []
    
    # ---------------------------------------------------------
    # SECCIÓN 1: AUDITORÍA (PDF vs TXT)
    # ---------------------------------------------------------
    if pdf_file and txt_file:
        st.divider()
        st.subheader("📊 Sección 1: Auditoría de Cantidades")
        
        txt_content = txt_file.read().decode("utf-8", errors="ignore")
        txt_lines = [line for line in txt_content.splitlines() if line.strip()]
        count_txt = len(txt_lines)

        pdf_bytes = pdf_file.read()
        pdf_text = ""
        with fitz.open(stream=io.BytesIO(pdf_bytes), filetype="pdf") as doc:
            for page in doc:
                pdf_text += page.get_text()
        
        pdf_text_norm = pdf_text.upper().replace("Ο", "O").replace("Κ", "K")
        count_ok_pdf = pdf_text_norm.count("O.K.")

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
            df_xls = pd.read_excel(xls_file, header=6, dtype=str)
            
            if "Linea" not in df_xls.columns:
                st.error("El Excel no tiene la columna 'Linea'. Verifique el formato (header=6).")
            else:
                for _, row in df_xls.iterrows():
                    linea_val = row.get("Linea")
                    obs_val = row.get("Observación:")
                    
                    if pd.isna(linea_val): 
                        continue
                    
                    try:
                        line_idx = int(float(linea_val))
                    except ValueError:
                        continue

                    idx_array = line_idx - 1
                    
                    if 0 <= idx_array < len(txt_lines):
                        raw_line = txt_lines[idx_array]
                        
                        dni = slice_fixed(raw_line, *SCO_TXT_POS["dni"])
                        nombre = slice_fixed(raw_line, *SCO_TXT_POS["nombre"])
                        importe = parse_sco_importe(slice_fixed(raw_line, *SCO_TXT_POS["importe"]))
                        referencia = slice_fixed(raw_line, 116, 127) 
                        
                        code, desc = map_sco_xls_error_to_code(obs_val)

                        rows_to_reject.append({
                            "dni/cex": dni,
                            "nombre": nombre,
                            "importe": importe,
                            "Referencia": referencia,
                            "Codigo de Rechazo": code,
                            "Descripcion de Rechazo": desc
                        })

        except Exception as e:
            st.error(f"Error al leer el archivo XLS: {e}")
            st.write("Asegúrese de instalar 'xlrd' si es un archivo .xls antiguo.")

        if rows_to_reject:
            df_out = pd.DataFrame(rows_to_reject)
            df_out["Estado"] = ESTADO
            df_out = df_out[OUT_COLS]

            render_final_output(df_out, "rechazos_sco.xlsx", "post_sco_simple", "editor_sco_simple")
        
        elif xls_file:
            st.info("El archivo XLS se leyó, pero no contenía líneas válidas para rechazar.")

    elif not pdf_file and not txt_file:
        st.info("👆 Carga los archivos arriba para comenzar.")

def tab_rechazo_total_txt():
    st.header("Rechazo TOTAL (Banco Inoperativo)")
    st.warning("⚠️ ESTA OPCIÓN RECHAZARÁ TODO EL ARCHIVO EXCEL CON EL CÓDIGO SELECCIONADO.")

    code, desc = select_code("total_excel_code", "R020")

    ex_file = st.file_uploader("Cargar Excel Masivo para rechazar totalmente", type=["xlsx", "xls", "csv"], key="total_excel")
    
    if ex_file:
        with st.spinner("Procesando rechazo total..."):
            if ex_file.name.endswith(".csv"):
                df_raw = pd.read_csv(ex_file, dtype=str)
            else:
                df_raw = pd.read_excel(ex_file, dtype=str)
            
            # El input tiene la misma estructura que POST BCP-xlsx (Referencia en columna 7)
            if df_raw.shape[1] <= 7:
                st.error("El archivo no tiene las columnas necesarias (se espera el formato POST BCP-xlsx).")
                return
            
            # Usar la columna 7 (Referencia) para validar nulos y eliminar celdas vacías
            col_ref_name = df_raw.columns[7]
            df_valid = df_raw.dropna(subset=[col_ref_name]).copy()
            df_valid[col_ref_name] = df_valid[col_ref_name].astype(str).str.strip()
            df_valid = df_valid[df_valid[col_ref_name] != ""]
            df_valid = df_valid[df_valid[col_ref_name].str.lower() != "nan"]
            df_valid = df_valid.reset_index(drop=True)

            if df_valid.empty:
                st.error("No se detectaron registros válidos en la columna de Referencia (columna 8).")
                return

            # Extraemos las mismas columnas que en POST BCP-xlsx
            dni_out = df_valid.iloc[:, 0]
            nombre_out = df_valid.iloc[:, 3] if df_valid.shape[1] > 3 else (df_valid.iloc[:, 1] if df_valid.shape[1] > 1 else pd.Series([""] * len(df_valid)))
            ref_out = df_valid.iloc[:, 7]
            importe_out = df_valid.iloc[:, 12].apply(parse_amount) if df_valid.shape[1] > 12 else pd.Series([0.0] * len(df_valid))

            # Construir DataFrame de salida con todo el contenido
            df_out = pd.DataFrame({
                "dni/cex": dni_out,
                "nombre": nombre_out,
                "importe": importe_out,
                "Referencia": ref_out,
            })

            df_out["Estado"] = ESTADO
            df_out["Codigo de Rechazo"] = code
            df_out["Descripcion de Rechazo"] = desc
            
            df_out = df_out[OUT_COLS]

            render_final_output(df_out, "rechazo_total_inoperativo.xlsx", "post_total_excel", "editor_total_excel")

def tab_bcp_prueba():
    st.header("BCP Prueba")
    st.info("Módulo para procesar rechazos desde Excel BCP basado en la columna 'Observación'.")
    
    code, desc = select_code("bcp_prueba_code", "R001")
    
    ex_file = st.file_uploader("Cargar Excel BCP (.xlsx o .csv)", type=["xlsx", "xls", "csv"], key="bcp_prueba_file")
    
    if ex_file:
        with st.spinner("Procesando BCP prueba…"):
            if ex_file.name.endswith(".csv"):
                df_raw = pd.read_csv(ex_file, dtype=str)
            else:
                df_raw = pd.read_excel(ex_file, dtype=str)
            
            if "Observación" not in df_raw.columns:
                st.error("No se encontró la columna 'Observación' en el archivo.")
                return
            
            mask = df_raw["Observación"].notna() & (df_raw["Observación"].str.strip().str.lower() != "ninguna")
            df_valid = df_raw.loc[mask].reset_index(drop=True)
            
            if df_valid.empty:
                st.warning("No se encontraron registros con observaciones diferentes a 'Ninguna'.")
                return
            
            # Extraer columnas usando los índices basados en los encabezados reales indicados:
            # 0: Beneficiario - Nombre, 2: Documento (DNI), 4: Documento.1 (Referencia), 6: Monto (Importe)
            nombre_out = df_valid.iloc[:, 0] if df_valid.shape[1] > 0 else pd.Series([""] * len(df_valid))
            dni_out = df_valid.iloc[:, 2] if df_valid.shape[1] > 2 else pd.Series([""] * len(df_valid))
            ref_out = df_valid.iloc[:, 4] if df_valid.shape[1] > 4 else pd.Series([""] * len(df_valid))
            importe_out = df_valid.iloc[:, 6].apply(parse_amount) if df_valid.shape[1] > 6 else pd.Series([0.0] * len(df_valid))

            df_out = pd.DataFrame({
                "dni/cex": dni_out,
                "nombre": nombre_out,
                "importe": importe_out,
                "Referencia": ref_out.astype(str).apply(lambda x: x[3:] if x.startswith("000") else x),
            })
            
            df_out["Estado"] = ESTADO
            df_out["Codigo de Rechazo"] = code
            df_out["Descripcion de Rechazo"] = desc
            
            df_out = df_out[OUT_COLS]

            render_final_output(df_out, "rechazo_bcp_prueba.xlsx", "post_bcp_prueba", "editor_bcp_prueba")

# -------------- Render pestañas --------------
tabs = st.tabs([
    "PRE BCP-txt",
    "-", 
    "rechazo IBK",
    "POST BCP-xlsx",
    "Procesador SCO",
    "Rechazo TOTAL",
    "BCP Prueba",
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
