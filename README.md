# Suite de pruebas de SICEDU contra QA

Corre los casos de prueba del plan v1.15 contra **qa-huascaran** desde tu PC y guarda la evidencia
(capturas y `steps.json` por caso) en un .zip para analizarla.

Tanda 1 (esta versión): **Asistencias, Seguimiento de Lectura, Rúbrica y Registro de Vuelo** (45 casos,
18 de los 32 rechazados en la ronda 6). `correr.bat` sin argumentos lista los 139 casos y dice cuáles
están automatizados; también deja `catalogo.csv` para abrir en Excel.

## 1. Instalar (una sola vez)

1. Instala **Python 3.11 o superior** desde python.org y marca *"Add python.exe to PATH"*.
2. Doble clic en **`instalar.bat`**. Crea el entorno `.venv`, instala Playwright y descarga Chromium.
3. Abre **`.env`** con el Bloc de notas y completa:
   - `QA_SUPERVISOR_CORREO` y `QA_SUPERVISOR_CLAVE`: la Supervisora E2E de QA (solo se usa por la API).
   - `QA_CLAVE_CUENTAS`: la clave que tendrán las cuentas de la suite (mínimo 8 caracteres, con
     mayúscula, minúscula, número y un carácter especial).
   - El `.env` queda solo en tu PC: no lo compartas ni lo subas a ningún repositorio.

## 2. Preparar QA (la primera vez y cuando quieras)

Ejecuta **`preparar.bat`**. La primera vez crea **7 cuentas** con alias de tu correo
(`joaquin.mercado+sicedu-docente-a@utec.edu.pe`, `…+sicedu-rv-uno`, `…+sicedu-retro`,
`…+sicedu-docente-b`, `…+sicedu-sin-grupos`, `…+sicedu-directivo`, `…+sicedu-supervisor-2`).
A cada una le llega un correo de bienvenida con su **contraseña temporal**: la suite se detiene y te pide
pegarla. Con eso hace el primer ingreso y la cuenta queda con `QA_CLAVE_CUENTAS`.

- Si una temporal no llega todavía, presiona Enter para saltarla y vuelve a ejecutar `preparar.bat` luego.
- La temporal vence a las 48 horas.
- `preparar.bat --estado` muestra qué cuentas están listas.

### Colegio de demostración (opcional)

`preparar.bat --demo` crea **"I.E. Demo QA Huascarán"** (Independencia, Huaraz) con los 6 grados, cada uno
con su día de clase y **entre 30 y 40 alumnos** con nombres peruanos (unos 200 en total). En 1.º todos son
de Alfabetización y en los demás grados se reparten entre Alfabetización y Comprensión Lectora. Lo atiende
una cuenta más, **Docente Demo** (`…+sicedu-docente-demo`), que también pide pegar su contraseña temporal
la primera vez. Este colegio **queda activo** y no lo tocan los casos: sirve para revisar las pantallas a
mano con un volumen real o medir tiempos de carga. Si lo vuelves a ejecutar, solo completa lo que falte.

## 3. Correr los casos

```
correr.bat --modulo Asistencias          un módulo (también: ASI, LEC, RUB, RV o el nombre)
correr.bat --caso CP-ASI-04 CP-RUB-01    casos sueltos
correr.bat --rechazados                  los rechazados en la ronda 6 que estén automatizados
correr.bat --todo                        todo lo automatizado
correr.bat --ver --caso CP-ASI-01        con el navegador visible
```

Al terminar dice dónde quedó el **.zip** (`resultados\AAAAMMDD-HHMM.zip`). Ese archivo es el que se
envía para el análisis.

## Cómo funciona

- **Datos nuevos por caso.** Antes de cada caso se crean dos colegios (`QA AUTO <caso> <hora> Norte` y
  `… Sur`) con sus alumnos y se reasigna a los Docentes de la suite. Al terminar, esos colegios se
  **inactivan**. Así cada caso empieza limpio, como en local con la base restaurada. Los datos quedan en
  QA (inactivos); no se borra nada.
- **Fechas reales.** Las fechas salen del calendario del colegio: la clase de hoy, la anterior, el
  receso, un feriado, el PA culminado… No hay fechas fijas.
- **Sin base de datos ni reloj.** Lo que en local se verificaba en la base se verifica por la API. Lo
  que en QA no se puede hacer queda como **NOTA** en el `steps.json` del caso (por ejemplo, la sesión
  expirada se simula cerrándola en el servidor).
- La Supervisora E2E solo se usa por la API. En la interfaz, el rol Supervisor usa la cuenta
  `supervisor-2` de la suite.

## Cuidados

- **No inicies sesión con las cuentas de la suite mientras corre**: el sistema cierra la sesión anterior
  al volver a entrar y el caso fallaría.
- No cambies la contraseña de la Supervisora E2E ni la del Supervisor original.
- Un caso tarda entre 1 y 4 minutos. `--todo` de esta tanda tarda alrededor de 2 horas.
- Si un caso termina en *error*, su carpeta tiene un `error.txt`; el resto sigue corriendo.
