# 📊 Gestor de Operaciones API (Streamlit)

Esta es una aplicación web interactiva creada con Streamlit, diseñada para automatizar y simplificar las llamadas a las APIs de Operaciones (Payouts y Payments) que originalmente se gestionaban desde Postman.

Permite a los usuarios realizar operaciones de Crédito y Débito, y consultar `order_name` a partir de PDFs del banco, sin necesidad de configurar colecciones en Postman.

## ✨ Funcionalidades

La aplicación se divide en tres pestañas principales:

* **💸 Pestaña Crédito:**
    * Realiza operaciones de **Crédito** (`method: CASH`).
    * Permite elegir entre "Acreditación" (descripción: `DEPOSITO`) o "Extorno" (descripción: `EXTORNO CCI - ...`).
    * Selecciona automáticamente la moneda (PEN/USD) basado en la cuenta del cliente.

* **↩️ Pestaña Débito:**
    * Realiza operaciones de **Débito** (`method: CASH_OUT`).
    * Permite elegir entre "Ajuste Acreditación Doble" (descripción fija) o "Ajuste Extorno" (descripción: `AJUSTE EXTORNO - ...`).
    * Selecciona automáticamente la moneda (PEN/USD).

* **🔍 Pestaña Consultar PSP_TIN:**
    * Permite **cargar un PDF** (ej. Reporte de Movimientos del BBVA).
    * Lee el PDF y **extrae automáticamente** los "Números de Movimiento" y los "PSP_TINs" (números de 12 dígitos que empiezan con `25`).
    * Consulta la API de Payments (`/consultar/{tin}`) por cada TIN encontrado.
    * Analiza la respuesta JSON anidada (`metadata.order_name`) para encontrar el nombre de la orden.
    * Muestra un **resultado final consolidado** y listo para copiar con el formato: `PSP_TIN | Orden del Banco | Order Name`.

## ⚙️ Instalación y 🚀 Ejecución

Solo ingresa mediante tu buscador favorito al enlace "https://acreditaextorna-qztyj3xhg5u4gqmuia4nhz.streamlit.app/"

## 📋 Modo de Uso

### 1. Autenticación (Para Crédito y Débito)

Las pestañas de Crédito y Débito requieren autenticación. La pestaña de Consulta **no la necesita**.

1.  Abre la aplicación.
2.  En la **barra lateral izquierda**, ingresa el **Usuario API (`_eApiUser`)** y la **Contraseña API (`_eApiPassword`)**.
3.  Estos son los mismos valores que usas en las variables de entorno de Postman.

### 2. Pestañas de Crédito y Débito

1.  Selecciona la pestaña "💸 CRÉDITO" o "↩️ DÉBITO".
2.  **Paso 1:** Selecciona el Cliente de la lista. La moneda (PEN/USD) y el ID de cuenta se cargarán automáticamente.
3.  **Paso 2:** Selecciona el Tipo de Operación.
4.  **Paso 3:** Completa los datos del formulario:
    * **Importe:** Ingresa el monto exacto (ej: `320.00`).
    * **Motivo (si aplica):** Escribe el texto variable para los extornos o ajustes.
5.  Presiona el botón **"Ejecutar Crédito"** o **"Ejecutar Débito"**.
6.  La respuesta de la API (éxito o error) se mostrará en la parte inferior.

### 3. Pestaña de Consultar PSP_TIN

1.  Selecciona la pestaña "🔍 CONSULTAR PSP_TIN".
2.  **Paso 1:** Carga el archivo PDF del banco usando el botón "Browse files".
3.  Presiona el botón **"Procesar PDF y Obtener Datos Completos"**.
4.  La aplicación mostrará una barra de progreso mientras lee el PDF y consulta la API para cada TIN encontrado.
5.  **Paso 2:** Al finalizar, aparecerá un cuadro de texto con todos los resultados en el formato `PSP_TIN | Orden del Banco | Order Name`, listos para copiar.
