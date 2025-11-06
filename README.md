# ⚙️ Procesador de Rechazos Masivos Unificado

Esta es una aplicación interna construida con [Streamlit] diseñada para **automatizar y unificar los procesos de rechazo masivo** de pagos para diferentes entidades bancarias (BCP, IBK, BBVA, Scotiabank).

La herramienta permite a los operadores cargar archivos de reporte (PDF, TXT, XLS/XLSX) para extraer, cruzar y formatear los datos de las transacciones a rechazar. Finalmente, genera un archivo Excel listo para su descarga y ofrece la opción de enviar los rechazos directamente a un endpoint (API).

## ✨ Características Principales

La aplicación se organiza en pestañas, cada una para un flujo de trabajo distinto:

* **PRE BCP-txt:** Procesa rechazos cruzando un PDF que contiene números de "Registro" contra un archivo maestro de formato fijo (`.txt`).
* **PRE BCP-xlsx:** Procesa rechazos cruzando un PDF que contiene números de "Registro" contra un archivo maestro de Excel (`.xlsx`) - Está oculto.
* **rechazo IBK:** Procesa el archivo de rechazos específico de Interbank, extrayendo el Excel de un archivo `.zip` y asignando códigos de rechazo basados en las observaciones.
* **POST BCP-xlsx:** Identifica números de DNI/CEX en un PDF y los cruza contra un Excel maestro. Incluye una **tabla de edición por fila** que permite al operador asignar/cambiar el código de rechazo para cada transacción.
* **Procesador SCO:** Un flujo de trabajo avanzado para Scotiabank que:
    * Procesa 3 archivos: PDF de detalle de orden, TXT masivo y (opcionalmente) un XLS de errores.
    * Extrae un resumen de la orden (Nro. de Orden, Montos).
    * Lee las tablas del PDF (manejando múltiples formatos) para identificar errores (`CTA ES CTS`, etc.).
    * Lee el XLS de errores para identificar más rechazos.
    * **Pre-asigna inteligentemente** los códigos de rechazo (`R001`, `R002`, `R017`) según las reglas de negocio.
    * Muestra una advertencia si los archivos PDF y TXT no coinciden.

## 🛠️ Instalación y Dependencias

Esta aplicación requiere varias librerías de Python, Streamlitse encarga de usar el archivo un archivo `requirements.txt`.
Solo ingresas con el link "https://rechazo-consolidado-9dtveqcnpuqru5v786vcm6.streamlit.app/" y empieza a usarlo!
