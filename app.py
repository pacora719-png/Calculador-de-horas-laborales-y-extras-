"""
Calculador de horas laborales y extras by Juan Pablo Villegas
----------------------------------------------------------------
App de Streamlit para liquidar horas trabajadas y horas extra
semanales de varios empleados, con exportación a PDF.
"""

import io
import uuid
from datetime import date, timedelta, time, datetime

import pandas as pd
import streamlit as st
from fpdf import FPDF

# ----------------------------------------------------------------------
# Configuración general
# ----------------------------------------------------------------------
st.set_page_config(
    page_title="Calculador de horas laborales y extras",
    page_icon="🕒",
    layout="wide",
)

DIAS_ES = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
ESTADOS = ["Trabajó", "No trabajó", "Festivo", "Incapacidad"]
UMBRAL_MIN = 7 * 60  # horas extra a partir de 7 horas diarias trabajadas


def fmt_hm(minutos: float) -> str:
    """Convierte minutos a formato H:MM"""
    if minutos is None or pd.isna(minutos):
        minutos = 0
    signo = "-" if minutos < 0 else ""
    minutos = abs(round(minutos))
    h, m = divmod(int(minutos), 60)
    return f"{signo}{h}:{m:02d}"


def parse_hora(valor):
    """Convierte lo que devuelva el data_editor (time, str, NaT, None) a datetime.time o None."""
    if valor is None:
        return None
    try:
        if pd.isna(valor):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(valor, time):
        return valor
    if isinstance(valor, datetime):
        return valor.time()
    if isinstance(valor, str):
        v = valor.strip()
        if not v or v in ("-", "—"):
            return None
        for fmt in ("%H:%M:%S", "%H:%M"):
            try:
                return datetime.strptime(v, fmt).time()
            except ValueError:
                continue
        return None
    return None


def calcular_fila(entrada, salida, estado, almuerzo_min):
    """Calcula turno, almuerzo, horas trabajadas y horas extra (en minutos) para un día."""
    if estado == "Festivo":
        return UMBRAL_MIN, 0, UMBRAL_MIN, 0
    if estado != "Trabajó":
        return 0, 0, 0, 0
    entrada = parse_hora(entrada)
    salida = parse_hora(salida)
    if entrada is None or salida is None:
        return 0, 0, 0, 0
    e_min = entrada.hour * 60 + entrada.minute
    s_min = salida.hour * 60 + salida.minute
    turno = s_min - e_min
    if turno < 0:
        turno += 24 * 60
    almuerzo = almuerzo_min
    trabajadas = max(0, turno - almuerzo)
    extra = max(0, trabajadas - UMBRAL_MIN)
    return turno, almuerzo, trabajadas, extra


# ----------------------------------------------------------------------
# Estado de la sesión
# ----------------------------------------------------------------------
if "empleados" not in st.session_state:
    nombres_iniciales = ["Nicol", "Paola", "Gaby", "Alex", "Merli",
                          "Denis", "Blanca", "Nina", "María", "Zuli"]
    st.session_state.empleados = [{"id": str(uuid.uuid4()), "nombre": n} for n in nombres_iniciales]

if "registros" not in st.session_state:
    st.session_state.registros = {}  # registros[emp_id][fecha_iso] = {"entrada", "salida", "estado"}


def get_registro(emp_id, fecha_iso):
    return st.session_state.registros.setdefault(emp_id, {}).setdefault(
        fecha_iso, {"entrada": None, "salida": None, "estado": ""}
    )


def agregar_empleado():
    st.session_state.empleados.append({"id": str(uuid.uuid4()), "nombre": "Nuevo empleado"})


def eliminar_empleado(emp_id):
    st.session_state.empleados = [e for e in st.session_state.empleados if e["id"] != emp_id]
    st.session_state.registros.pop(emp_id, None)


# ----------------------------------------------------------------------
# Encabezado
# ----------------------------------------------------------------------
st.title("🕒 Calculador de horas laborales y extras")
st.caption("by Juan Pablo Villegas")

st.info(
    "**Normativa laboral colombiana vigente:** la jornada laboral máxima es de **42 horas semanales** "
    "(en promedio **7 horas diarias**). El **tiempo de alimentación no se considera tiempo laborado** "
    "y debe descontarse del total de horas trabajadas. Esta app calcula las horas extra diarias a partir "
    "de las 7 horas trabajadas cada día, después de descontar el tiempo de alimentación.",
    icon="⚖️",
)

with st.expander("❓ ¿Cómo usar esta app? (guía rápida)"):
    st.markdown(
        """
        1. **Diligencia los datos de la empresa** (nombre, NIT) y el **tiempo de alimentación** que se debe descontar cada día trabajado.
        2. **Selecciona el periodo** (la semana) que vas a liquidar en el calendario.
        3. **Agrega los empleados** con el botón *"➕ Agregar empleado"* — no hay límite de cuántos puedes agregar.
        4. Para cada empleado, abre su casilla desplegable y **diligencia día por día**: hora de entrada, hora de salida y el **estado** del día (Trabajó, No trabajó, Festivo o Incapacidad).
           - Si el estado es **Festivo**, la app asigna automáticamente 7 horas trabajadas, sin necesidad de poner entrada/salida.
           - Si el estado es **No trabajó** o **Incapacidad**, ese día no suma horas.
        5. Revisa el **resumen total** al final de la página.
        6. Da clic en **"📄 Generar y descargar PDF"** para obtener el reporte completo, listo para archivar o entregar.
        """
    )

st.divider()

# ----------------------------------------------------------------------
# Datos de la empresa y configuración
# ----------------------------------------------------------------------
st.subheader("Datos de la liquidación")

col1, col2, col3 = st.columns(3)
with col1:
    empresa = st.text_input(
        "Nombre de la empresa",
        placeholder="Ej: Puli Magia y Sabor",
        help="Aparecerá en el encabezado del reporte en PDF.",
    )
with col2:
    nit = st.text_input(
        "NIT",
        placeholder="Ej: 900.123.456-7",
        help="Número de Identificación Tributaria de la empresa.",
    )
with col3:
    almuerzo_min = st.number_input(
        "Tiempo de alimentación a descontar (minutos)",
        min_value=0,
        max_value=180,
        value=20,
        step=5,
        help="Este tiempo se descuenta automáticamente cada día que el estado sea 'Trabajó'. "
             "Según la ley, el tiempo de alimentación no cuenta como tiempo laborado.",
    )

col4, col5 = st.columns([2, 3])
with col4:
    hoy = date.today()
    inicio_semana = hoy - timedelta(days=hoy.weekday())
    fin_semana = inicio_semana + timedelta(days=6)
    periodo = st.date_input(
        "Periodo a liquidar (semana)",
        value=(inicio_semana, fin_semana),
        help="Selecciona el primer y el último día de la semana que vas a liquidar.",
    )

if isinstance(periodo, tuple) and len(periodo) == 2:
    fecha_inicio, fecha_fin = periodo
elif isinstance(periodo, tuple) and len(periodo) == 1:
    fecha_inicio = fecha_fin = periodo[0]
else:
    fecha_inicio = fecha_fin = periodo

if fecha_fin < fecha_inicio:
    st.error("La fecha final del periodo no puede ser anterior a la fecha inicial.")
    st.stop()

dias_periodo = [fecha_inicio + timedelta(days=i) for i in range((fecha_fin - fecha_inicio).days + 1)]

st.divider()

# ----------------------------------------------------------------------
# Empleados
# ----------------------------------------------------------------------
st.subheader(f"Empleados ({len(st.session_state.empleados)})")
st.button("➕ Agregar empleado", on_click=agregar_empleado)

resumen_rows = []
detalle_por_empleado = {}  # nombre -> dataframe con detalle diario (para el PDF)

for emp in st.session_state.empleados:
    emp_id = emp["id"]

    col_nombre, col_borrar = st.columns([5, 1])
    with col_nombre:
        nombre = st.text_input(
            "Nombre del empleado",
            value=emp["nombre"],
            key=f"nombre_{emp_id}",
            label_visibility="collapsed",
            placeholder="Nombre del empleado",
        )
        emp["nombre"] = nombre
    with col_borrar:
        st.button("🗑️ Eliminar", key=f"del_{emp_id}", on_click=eliminar_empleado, args=(emp_id,))

    with st.expander(f"📅 Horario semanal — {nombre or 'Sin nombre'}", expanded=False):
        st.caption(
            "Selecciona la **hora militar** (24 h) de entrada y salida, y el **estado** de cada día. "
            "Si el día es Festivo, no necesitas llenar entrada/salida: la app suma 7 horas automáticamente."
        )

        filas = []
        for d in dias_periodo:
            fecha_iso = d.isoformat()
            rec = get_registro(emp_id, fecha_iso)
            filas.append({
                "Día": DIAS_ES[d.weekday()],
                "Fecha": d,
                "Entrada": rec["entrada"],
                "Salida": rec["salida"],
                "Estado": rec["estado"],
            })
        df_dias = pd.DataFrame(filas)

        editado = st.data_editor(
            df_dias,
            key=f"editor_{emp_id}",
            hide_index=True,
            width="stretch",
            disabled=["Día", "Fecha"],
            column_config={
                "Día": st.column_config.TextColumn("Día"),
                "Fecha": st.column_config.DateColumn("Fecha", format="DD/MM/YYYY"),
                "Entrada": st.column_config.TimeColumn(
                    "Entrada", format="HH:mm", step=600,
                    help="Hora militar de entrada (ej: 07:10)."
                ),
                "Salida": st.column_config.TimeColumn(
                    "Salida", format="HH:mm", step=600,
                    help="Hora militar de salida (ej: 18:00)."
                ),
                "Estado": st.column_config.SelectboxColumn(
                    "Estado", options=[""] + ESTADOS,
                    help="Trabajó / No trabajó / Festivo / Incapacidad."
                ),
            },
        )

        # Guardar cambios de vuelta en el estado de sesión
        calc_rows = []
        for _, row in editado.iterrows():
            fecha_iso = row["Fecha"].isoformat() if hasattr(row["Fecha"], "isoformat") else str(row["Fecha"])
            entrada_h = parse_hora(row["Entrada"])
            salida_h = parse_hora(row["Salida"])
            st.session_state.registros.setdefault(emp_id, {})[fecha_iso] = {
                "entrada": entrada_h,
                "salida": salida_h,
                "estado": row["Estado"] or "",
            }
            turno, almuerzo, trabajadas, extra = calcular_fila(
                entrada_h, salida_h, row["Estado"], almuerzo_min
            )
            calc_rows.append({
                "Día": row["Día"],
                "Fecha": row["Fecha"],
                "Entrada": entrada_h.strftime("%H:%M") if entrada_h else "-",
                "Salida": salida_h.strftime("%H:%M") if salida_h else "-",
                "Estado": row["Estado"] or "-",
                "Turno": fmt_hm(turno),
                "Almuerzo": fmt_hm(almuerzo),
                "Trabajadas": fmt_hm(trabajadas),
                "Extra": fmt_hm(extra),
                "_trabajadas_min": trabajadas,
                "_extra_min": extra,
            })

        df_calc = pd.DataFrame(calc_rows)
        total_trabajadas = df_calc["_trabajadas_min"].sum()
        total_extra = df_calc["_extra_min"].sum()

        st.dataframe(
            df_calc[["Día", "Entrada", "Salida", "Estado", "Turno", "Almuerzo", "Trabajadas", "Extra"]],
            hide_index=True,
            width="stretch",
        )
        st.markdown(
            f"**Total horas trabajadas:** `{fmt_hm(total_trabajadas)}`   |   "
            f"**Total horas extra:** `{fmt_hm(total_extra)}`"
        )

        detalle_por_empleado[nombre or "(Sin nombre)"] = df_calc

        dias_festivo = int((df_calc["Estado"] == "Festivo").sum())
        dias_incapacidad = int((df_calc["Estado"] == "Incapacidad").sum())
        dias_no_trabajo = int((df_calc["Estado"] == "No trabajó").sum())

        resumen_rows.append({
            "Empleado": nombre or "(Sin nombre)",
            "Horas trabajadas": fmt_hm(total_trabajadas),
            "Horas extra": fmt_hm(total_extra),
            "Días festivo": dias_festivo,
            "Días incapacidad": dias_incapacidad,
            "Días no trabajó": dias_no_trabajo,
            "_trabajadas_min": total_trabajadas,
            "_extra_min": total_extra,
        })

st.divider()

# ----------------------------------------------------------------------
# Resumen general
# ----------------------------------------------------------------------
st.subheader("Resumen general de la semana")

if resumen_rows:
    df_resumen = pd.DataFrame(resumen_rows)
    total_gen_trabajadas = df_resumen["_trabajadas_min"].sum()
    total_gen_extra = df_resumen["_extra_min"].sum()

    st.dataframe(
        df_resumen[["Empleado", "Horas trabajadas", "Horas extra",
                    "Días festivo", "Días incapacidad", "Días no trabajó"]],
        hide_index=True,
        width="stretch",
    )

    c1, c2, c3 = st.columns(3)
    c1.metric("Empleados", len(resumen_rows))
    c2.metric("Total horas trabajadas", fmt_hm(total_gen_trabajadas))
    c3.metric("Total horas extra", fmt_hm(total_gen_extra))
else:
    st.info("Agrega al menos un empleado para ver el resumen.")
    df_resumen = pd.DataFrame(columns=["Empleado", "Horas trabajadas", "Horas extra",
                                        "Días festivo", "Días incapacidad", "Días no trabajó"])
    total_gen_trabajadas = 0
    total_gen_extra = 0

st.divider()


# ----------------------------------------------------------------------
# Generación de PDF
# ----------------------------------------------------------------------
def generar_pdf(empresa, nit, fecha_inicio, fecha_fin, df_resumen, detalle_por_empleado,
                 total_gen_trabajadas, total_gen_extra, almuerzo_min):
    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 9, "Calculador de horas laborales y extras", ln=1)
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(90, 90, 90)
    pdf.cell(0, 6, "by Juan Pablo Villegas", ln=1)
    pdf.set_text_color(0, 0, 0)
    pdf.ln(2)

    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 7, f"Empresa: {empresa or '-'}", ln=1)
    pdf.cell(0, 7, f"NIT: {nit or '-'}", ln=1)
    pdf.cell(0, 7, f"Periodo liquidado: {fecha_inicio.strftime('%d/%m/%Y')} a {fecha_fin.strftime('%d/%m/%Y')}", ln=1)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(90, 90, 90)
    pdf.multi_cell(
        0, 5,
        "Jornada laboral según normativa colombiana vigente: 42 horas semanales / 7 horas diarias en promedio. "
        f"Tiempo de alimentación descontado: {almuerzo_min} minutos por día trabajado (no se cuenta como tiempo laborado). "
        "Las horas extra se calculan a partir de las 7 horas trabajadas cada día."
    )
    pdf.set_text_color(0, 0, 0)
    pdf.ln(3)

    # Resumen general
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "Resumen general", ln=1)
    with pdf.table(col_widths=(58, 32, 30, 24, 24, 22), text_align=("LEFT", "CENTER", "CENTER", "CENTER", "CENTER", "CENTER")) as table:
        row = table.row()
        for h in ["Empleado", "H. trabajadas", "H. extra", "Festivo", "Incapac.", "No trab."]:
            row.cell(h)
        for _, r in df_resumen.iterrows():
            row = table.row()
            row.cell(str(r["Empleado"]))
            row.cell(str(r["Horas trabajadas"]))
            row.cell(str(r["Horas extra"]))
            row.cell(str(r["Días festivo"]))
            row.cell(str(r["Días incapacidad"]))
            row.cell(str(r["Días no trabajó"]))
        row = table.row()
        row.cell("TOTAL GENERAL")
        row.cell(fmt_hm(total_gen_trabajadas))
        row.cell(fmt_hm(total_gen_extra))
        row.cell(str(int(df_resumen["Días festivo"].sum())) if len(df_resumen) else "0")
        row.cell(str(int(df_resumen["Días incapacidad"].sum())) if len(df_resumen) else "0")
        row.cell(str(int(df_resumen["Días no trabajó"].sum())) if len(df_resumen) else "0")
    pdf.ln(4)

    # Detalle por empleado
    for nombre, df_calc in detalle_por_empleado.items():
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 13)
        pdf.cell(0, 8, f"Detalle diario - {nombre}", ln=1)
        pdf.set_font("Helvetica", "", 9)

        cols = ["Día", "Entrada", "Salida", "Estado", "Turno", "Almuerzo", "Trabajadas", "Extra"]
        widths = (22, 20, 20, 26, 20, 22, 26, 20)
        with pdf.table(col_widths=widths, text_align="CENTER") as table:
            row = table.row()
            for h in cols:
                row.cell(h)
            for _, r in df_calc.iterrows():
                row = table.row()
                for c in cols:
                    row.cell(str(r[c]))
            total_t = df_calc["_trabajadas_min"].sum()
            total_e = df_calc["_extra_min"].sum()
            row = table.row()
            row.cell("TOTAL")
            row.cell("")
            row.cell("")
            row.cell("")
            row.cell("")
            row.cell("")
            row.cell(fmt_hm(total_t))
            row.cell(fmt_hm(total_e))

    return bytes(pdf.output())


st.subheader("Exportar")
if st.button("📄 Generar y descargar PDF", type="primary", disabled=len(resumen_rows) == 0):
    pdf_bytes = generar_pdf(
        empresa, nit, fecha_inicio, fecha_fin, df_resumen, detalle_por_empleado,
        total_gen_trabajadas, total_gen_extra, almuerzo_min,
    )
    nombre_archivo = f"liquidacion-horas-{fecha_inicio.isoformat()}-a-{fecha_fin.isoformat()}.pdf"
    st.download_button(
        "⬇️ Descargar PDF",
        data=pdf_bytes,
        file_name=nombre_archivo,
        mime="application/pdf",
    )
    st.success("PDF generado. Da clic en 'Descargar PDF' para guardarlo.")

if len(resumen_rows) == 0:
    st.caption("Agrega al menos un empleado con datos para poder generar el PDF.")
