🏦 Rechazos Masivos Unificado - Procesador de Extornos Bancarios

Esta es una aplicación desarrollada con Streamlit diseñada para automatizar, unificar y simplificar la conciliación de rechazos masivos (extornos) provenientes de múltiples entidades bancarias (BCP, Interbank, BBVA y Scotiabank).

La herramienta procesa diferentes formatos de entrada (PDFs, TXTs, Excel, CSV y archivos ZIP) proporcionados por los bancos, extrae los registros fallidos, permite su edición manual mediante una interfaz unificada y genera un payload estructurado para enviarlo automáticamente a un endpoint API (POST) o descargarlo como archivo Excel.

✨ Características Principales

Interfaz de Datos Unificada: Todas las operaciones resultan en una tabla interactiva y editable (st.data_editor) donde los analistas pueden añadir, eliminar o modificar los rechazos antes del envío.

Mapeo Automático de Errores: Asignación inteligente de Códigos de Rechazo (ej. R001, R002, R016, R017, R020) basados en la lectura de observaciones (XLS) o cruce de datos (PDF vs TXT).

Auditoría de Scotiabank: Módulo especializado que compara la cantidad de registros de un TXT contra las confirmaciones "O.K." de un reporte PDF para detectar cuadraturas imperfectas.

Módulo de "Botón de Pánico": Pestaña de Rechazo TOTAL diseñada para escenarios de caída del banco (Banco Inoperativo), asumiendo el rechazo automático de todos los registros válidos.

Integración API Directa: Envío automatizado de los registros procesados mediante peticiones POST al endpoint de conciliación.

🗂️ Flujos por Entidad Bancaria

BCP

PRE RECHAZO BCP: Cruza información de un PDF (búsqueda de "Registro N") contra un archivo TXT plano usando lectura posicional de caracteres.

POST RECHAZO BCP: Lee un archivo Excel/CSV y filtra los registros en base al contenido de la columna de Observación, asignando códigos dinámicamente.

IBK (Interbank)

Procesa un archivo ZIP que contiene el reporte en Excel.

Extrae directamente la data a partir de la fila 11 y filtra los registros basándose en palabras clave ("no es titular", "cuenta inválida", etc.) de la columna de observaciones.

BBVA

Combina un PDF con identificadores (DNIs) y una base de datos maestra en Excel.

Cruza la información buscando qué DNIs del PDF están presentes en el Excel y los separa para aplicarles el código de rechazo por defecto seleccionado en la UI.

SCO (Scotiabank)

Permite realizar una Auditoría verificando la cantidad de "O.K." en un PDF contra la cantidad de líneas enviadas en un TXT.

Permite procesar los errores cargando el XLS de reporte (buscando observaciones específicas como "Abono AFP" o "Verificar cuenta") y extrayendo los importes y nombres desde la fila exacta del TXT base.

Rechazo TOTAL

Módulo de emergencia. Toma una base en Excel, detecta automáticamente la columna "Referencia" y asigna el código R020: CUENTA BANCARIA INOPERATIVA masivamente a todos los registros no nulos.

🛠️ Tecnologías y Requisitos

El proyecto requiere Python 3.8+. Las dependencias principales se encuentran listadas a continuación:

streamlit (Framework web UI)

pandas (Manipulación de datos)

PyMuPDF / fitz (Extracción de texto avanzado de PDFs)

requests (Llamadas HTTP API REST)

openpyxl (Motor para escribir archivos .xlsx)

🚀 Instalación y Uso

Clonar el repositorio:

git clone [https://github.com/tu-usuario/rechazos-masivos-unificado.git](https://github.com/tu-usuario/rechazos-masivos-unificado.git)
cd rechazos-masivos-unificado


Crear un entorno virtual (Recomendado):

python -m venv venv
source venv/bin/activate  # En Windows usa: venv\Scripts\activate


Instalar las dependencias:

pip install streamlit pandas PyMuPDF requests openpyxl


Ejecutar la aplicación:

streamlit run streamlit_app.py


⚙️ Configuración (Importante para Producción)

Actualmente, el ENDPOINT de la API de AWS se encuentra definido como una constante en la cabecera de streamlit_app.py.

Para despliegues en producción (por ejemplo en Streamlit Community Cloud, AWS EC2, o Docker), se recomienda trasladar esta URL a los Streamlit Secrets o variables de entorno (os.environ) para mantener la seguridad de la infraestructura.

# Ejemplo sugerido para producción:
# ENDPOINT = st.secrets["AWS_ENDPOINT"]

Utiliza la función unificada render_final_output() al final de tu script para mantener la consistencia en la interfaz de usuario, la tabla editable y los botones de descarga/envío.Esta aplicación requiere varias librerías de Python, Streamlitse encarga de usar el archivo un archivo `requirements.txt`.

Solo ingresas con el link "https://rechazo-consolidado-9dtveqcnpuqru5v786vcm6.streamlit.app/" y empieza a usarlo!
