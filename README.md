# Suite de pruebas de SICEDU contra QA

Corre los casos de prueba del plan v1.16 contra **qa-huascaran** desde tu PC y guarda la evidencia
(capturas y `steps.json` por caso) en un .zip para analizarla.

Esta versión trae **las tres tandas** (**133 de los 139 casos**): Asistencias, Seguimiento de Lectura, Rúbrica,
Registro de Vuelo, Roles, Colegios, Alumnos, Usuarios, Permisos de corrección, Sesiones, Seguimiento,
Autenticación, Inicio y Calendario. `correr.bat` sin argumentos lista los 139 casos y dice cuáles están
automatizados, cuáles son *parciales* (algún paso queda como NOTA) y cuáles solo pueden correr en local; también
deja `catalogo.csv` para abrir en Excel. Los 6 que solo corren en local son CP22, CP-INI-20, CP-INI-24,
CP-INI-29, CP-CAL-04 y CP-USR-08.

## 1. Instalar (una sola vez)

1. Instala **Python 3.11 o superior** desde python.org y marca *"Add python.exe to PATH"*.
2. Doble clic en **`instalar.bat`**. Crea el entorno `.venv`, instala Playwright y descarga Chromium.
3. Abre **`.env`** con el Bloc de notas y completa:
   - `QA_SUPERVISOR_CORREO` y `QA_SUPERVISOR_CLAVE`: la Supervisora E2E de QA (solo se usa por la API).
   - `QA_CLAVE_CUENTAS`: la clave que tendrán las cuentas de la suite (mínimo 8 caracteres, con
     mayúscula, minúscula, número y un carácter especial).
   - El `.env` queda solo en tu PC: no lo compartas ni lo subas a ningún repositorio.

## 2. Preparar QA (la primera vez y cuando quieras)

Ejecuta **`preparar.bat`**. La primera vez crea **13 cuentas** con alias de tu correo:
las 7 de los módulos (`joaquin.mercado+sicedu-docente-a@utec.edu.pe`, `…+sicedu-rv-uno`, `…+sicedu-retro`,
`…+sicedu-docente-b`, `…+sicedu-sin-grupos`, `…+sicedu-directivo`, `…+sicedu-supervisor-2`) y 6 que solo usa
Autenticación (`…+sicedu-aut-docente`, `-aut-supervisor`, `-aut-pin`, `-aut-limite`, `-aut-reset` y
`-aut-inactivo`). **Si ya habías preparado QA con la versión anterior, vuelve a ejecutar `preparar.bat` una vez**:
solo crea las 6 de Autenticación (6 contraseñas temporales para pegar).
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
correr.bat --modulo Asistencias          un módulo (ASI, LEC, RUB, RV, ROL, COL, ALU, USR, PER, SES, SEG, AUT, INI, CAL o el nombre)
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

## Cuentas y datos que crea la tanda 2

- **Seguimiento y Usuarios necesitan más de 40 Docentes activos.** Si QA tiene menos, CP-SEG-01 (o CP-USR-01)
  crea **una sola vez** las cuentas que falten, "Seguimiento <nombre>" (`…+sicedu-seg-01` a `-36`), en colegios
  de volumen que se inactivan enseguida. También crea `…+sicedu-seg-sin-login` (nunca entra) y
  `…+sicedu-seg-inactivo` (queda inactiva). **A tu correo llega un mensaje de bienvenida por cada una**: no hay
  que pegar nada, puedes ignorarlos.
- **CP-COL-01** necesita más de 40 colegios activos: crea los que falten para el caso y los inactiva al terminar.
- **CP-USR-02 y CP-USR-09** crean Docentes y un Directivo nuevos con alias como `…+sicedu-usr02-docente-<hora>`;
  también reciben su correo de bienvenida.
- **CP-USR-04** inactiva y reactiva a Docente B (la suite la reactiva aunque el caso falle).
- **CP-USR-05 no toca al Supervisor original**: solo verifica que sus controles estén bloqueados. Lo demás queda
  como NOTA.
- **CP-USR-08** solo corre en local: necesita romper la configuración del correo del backend y mover 48 horas la
  emisión de la contraseña temporal en la base de datos.
- Los casos de permisos (CP-PER-01, 03 y 10) **esperan de 1 a 4 minutos** a que venza un permiso: es normal.

## Autenticación, Inicio y Calendario (tanda 3)

- **PIN y contraseñas temporales.** Los casos de recuperación de contraseña piden **pegar el PIN** que llega a tu
  correo: CP07 (2), CP18 (4), CP20, CP23 y CP24 (1 cada uno). CP25 crea un Docente nuevo y pide su **contraseña
  temporal**. Si en **10 minutos** no pegas nada, el paso queda como NOTA y el caso sigue (se cambia con
  `QA_ESPERA_CORREO` en el `.env`, en minutos). Conviene estar frente a la PC mientras corre `--modulo AUT`.
- **Las cuentas de Autenticación cambian de contraseña.** La suite guarda la vigente en `estado\claves.json`; no la
  cambies a mano. `aut-inactivo` queda inactiva a propósito.
- **Esperas largas:** CP11 espera 15 minutos a que se levante el bloqueo y CP18 otros 15 a que venza un PIN.
- **Límite de PIN.** CP23 pide 5 PIN para la misma cuenta y CP18 pide 4: el sistema solo da 5 por hora por correo.
  Si repites CP23 o CP18, deja pasar una hora.
- **Calendario.** La suite **nunca edita el calendario general de QA**: las ediciones, validaciones y rechazos se
  hacen sobre las fechas particulares de los colegios del caso (que luego se inactivan).
- **Inicio.** Los indicadores de la Supervisora y del Directivo son de todo QA: la suite verifica cuánto cambian con
  cada acción, no el valor total. Los recesos se hacen con fechas particulares de los colegios del caso.

## Cuidados

- **No inicies sesión con las cuentas de la suite mientras corre**: el sistema cierra la sesión anterior
  al volver a entrar y el caso fallaría.
- No cambies la contraseña de la Supervisora E2E ni la del Supervisor original.
- Un caso tarda entre 1 y 5 minutos (algunos esperan hasta 15). `--todo` tarda alrededor de **7 horas**:
  conviene correr por módulo, y Autenticación cuando estés frente a la PC para pegar los PIN.
- Si un caso termina en *error*, su carpeta tiene un `error.txt`; el resto sigue corriendo.
