"""Barrido 3 — casos LEGÍTIMOS pero ATÍPICOS que NO deben marcarse.

Todos los textos son SINTÉTICOS (datos inventados, sin PII): imitan el layout que sale
del OCR en los formatos del corpus, con nombres/cédulas/diagnósticos falsos. Se procesan
por el mismo camino que producción: `RuleBasedExtractor` -> foto (`CLAVE_SNAPSHOT`) ->
`normalizar_fechas()` -> `reglas_tiempo.evaluar` -> `erp.mapear_a_staging`.

Cada caso declara qué se ESPERA (`espera_revision`) y por qué. Un caso legítimo que
exige revisión por los TIEMPOS es un falso positivo del frente.

Se usa `erp.LookupsNulos()` (sin BD): los problemas de cédula/CIE/EPS son inevitables sin
catálogos y se FILTRAN — aquí solo interesa el canal de tiempos.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

from _comun import RAIZ_REPO, evaluar_doc, registro_como_processor, reglas_tiempo  # noqa: F401

from incapacidad_ocr import erp

AQUI = Path(__file__).resolve().parent
HOY = date(2026, 9, 2)


def _f(d: date) -> str:
    return d.strftime("%d/%m/%Y")


# --------------------------------------------------------------------------- #
# Plantillas (sintéticas) de los formatos que el corpus demuestra que existen
# --------------------------------------------------------------------------- #
_ABREV_ES = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]


def _dmy_es(f: date) -> str:
    """dd+MMM+aaaa con el mes en ESPAÑOL ('09Jun2026'): `extract._MONTHS_ES` solo
    conoce las abreviaturas españolas, así que un '%b' de locale inglés no se lee."""
    return f"{f.day:02d}{_ABREV_ES[f.month - 1]}{f.year}"


def plantilla_emermedicas(inicio: date, fin: date, dias: str = "", retro: str = "NO",
                          registro: date | None = None) -> str:
    """Formato EMERMÉDICA (R06): rótulos pegados, fechas dd MMM yyyy."""
    reg = registro or inicio
    return (
        "EMERMEDICAS.A.SERVICIOSDEAMBULANCIAPREPAGADOS\n"
        "HISTORIACLINICAELECTRONICAPACIENTE\n"
        "CC1111111111 NOMBRE APELLIDO DEMO\n"
        f"INCAPACIDAD N.9999999 -Fecha Registro:{_dmy_es(reg)} 07:22AM\n"
        "Causa de Ingreso:\nENFERMEDADGENERAL\n"
        "Prorroga:\nNo\n"
        "Diagnostico Principal:\nM545-LUMBAGO NO ESPECIFICADO\n"
        f"FechaInicio:{_dmy_es(inicio)}\n"
        f"FechaFinalizacion:{_dmy_es(fin)}\n"
        f"No.Total dias: {dias}\n"
        f"Incapacidad Retroactiva: {retro}\n"
        "Profesional:\nMEDICO DEMO\n"
    )


def plantilla_colsubsidio(inicio: date, fin: date, dias: int, letra: str = "",
                          expedicion: date | None = None) -> str:
    """Formato Colsubsidio (R01): 'Dias de Incapacidad: N' + palabra debajo."""
    exp = f"Fecha de expedicion: {_f(expedicion)}\n" if expedicion else ""
    return (
        "CAJA COLOMBIANA DE SUBSIDIO FAMILIAR\nSalud\n"
        "Nombre del Paciente\nNOMBRE APELLIDO DEMO\n"
        "Numero de documento 1.111.111.111\n"
        "Incapacidad Medica\n"
        "Clase incapacidad: Enfermedad General\n"
        "Tipo Incapacidad:\nInicial\n"
        + exp +
        f"Dias de Incapacidad:  {dias}\n{letra}\n"
        f"FechaInicioIncapacidad:{_f(inicio)}\n"
        f"Fecha Fin Incapacidad:\n{_f(fin)}\n"
        "Diagnostico Principal: M545\n"
    )


def plantilla_sura(inicio: date, fin: date, dias_texto: str, origen: str) -> str:
    """Formato SURA (R07): fecha escrita en palabras + año aparte, por POSICIÓN."""
    meses = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
             "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
    dias_sem = ["LUNES", "MARTES", "MIERCOLES", "JUEVES", "VIERNES", "SABADO", "DOMINGO"]
    return (
        "EPS\nsura\nEPS SURAMERICANA S.A.800088702\nCERTIFICADO DE INCAPACIDAD\n"
        "Fecha\nIPS Atiende\n"
        f"{_f(inicio)} 11:03:58\nIPS DEMO\n"
        "CC\nAfiliado\n1111111111 NOMBRE DEMO\n"
        "Diagnostico principal\nM545\n"
        f"Origen\n{origen}\n"
        "Fecha P.P\nFecha Inicio\n"
        f"{dias_sem[inicio.weekday()]} {inicio.day:02d} DE{meses[inicio.month-1].upper()}Duracion\n"
        "Fecha Fin\n"
        f"{dias_texto}\n"
        f"{dias_sem[fin.weekday()]} {fin.day:02d} DE {meses[fin.month-1].upper()}\n"
        "DE\n"
        f"{inicio.year}\n"
        f"DE {fin.year}\n"
        "INFORMACION DEL PROFESIONAL\nProfesional\nCC - CED-23 MEDICO DEMO\n"
    )


def plantilla_vacaciones(periodos: list[tuple[date, date]]) -> str:
    """Carta 'Notificación Periodo de Vacaciones' (formato del repo, CLAUDE.md)."""
    palabras = {1: "uno", 2: "dos", 3: "tres", 4: "cuatro", 5: "cinco", 6: "seis",
                7: "siete", 8: "ocho", 9: "nueve", 10: "diez"}
    meses = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
             "agosto", "septiembre", "octubre", "noviembre", "diciembre"]

    def esc(f: date) -> str:
        return (f"{palabras.get(f.day, 'veintinueve')} ({f.day:02d}) de {meses[f.month-1]} "
                f"de dos mil veintiseis ({f.year})")

    cuerpo = ""
    for i, (ini, fin) in enumerate(periodos):
        cuerpo += (f"{'Asi mismo, ' if i else ''}se le notifica que disfrutara de sus vacaciones "
                   f"a partir del {esc(ini)} hasta el {esc(fin)}. ")
    return ("EMPRESA DEMO S.A.S\nNotificacion Periodo de Vacaciones\n"
            "Senor(a): NOMBRE APELLIDO DEMO\nCC: 1111111111\n" + cuerpo +
            "\nCordialmente,\nGESTION HUMANA\n")


# --------------------------------------------------------------------------- #
# Los casos
# --------------------------------------------------------------------------- #
CASOS: list[dict] = [
    dict(
        id="LA_1DIA", titulo="Incapacidad de UN día (inicio == fin)",
        texto=plantilla_colsubsidio(date(2026, 8, 20), date(2026, 8, 20), 1, "UNO"),
        espera_revision=False,
        por_que="span=1 y dias=1: el conteo inclusivo tiene que dar CUMPLE, no off-by-one",
    ),
    dict(
        id="LB_PRORROGA_1", titulo="Incapacidad inicial 3 días (antecedente de la prórroga)",
        texto=plantilla_emermedicas(date(2026, 8, 17), date(2026, 8, 19)),
        espera_revision=False, por_que="documento normal; sirve de antecedente del siguiente",
    ),
    dict(
        id="LB_PRORROGA_2", titulo="PRÓRROGA que empieza justo al día siguiente de la anterior",
        texto=plantilla_emermedicas(date(2026, 8, 20), date(2026, 8, 24), retro="NO")
              .replace("Prorroga:\nNo", "Prorroga:\nSI"),
        espera_revision=False,
        por_que="contiguo y legítimo: ni T15 (solapamiento) ni T16 (prórroga) deben opinar",
    ),
    dict(
        id="LC_FIN_DE_ANIO", titulo="Incapacidad que cruza el fin de año (7 días)",
        texto=plantilla_colsubsidio(date(2026, 12, 28), date(2027, 1, 3), 7, "SIETE"),
        hoy=date(2026, 12, 30),
        espera_revision=False,
        por_que="el año cambia entre inicio y fin: span=7 == dias=7 (radicado el 30/12)",
    ),
    dict(
        id="LD_MATERNIDAD_126", titulo="Licencia de maternidad de 126 días (numérica)",
        texto=plantilla_colsubsidio(date(2026, 6, 1), date(2026, 10, 4), 126)
              .replace("Enfermedad General", "LICENCIA DE MATERNIDAD"),
        espera_revision=False,
        por_que="126 < dias_sin_respaldo_aviso(180) y span=126: no debe marcarse",
    ),
    dict(
        id="LD_MATERNIDAD_SURA", titulo="Licencia de maternidad 126 días, formato SURA en palabras",
        texto=plantilla_sura(date(2026, 6, 1), date(2026, 10, 4), "126- CIENTO VEINTISEIS",
                             "LICENCIA DE MATERNIDAD"),
        espera_revision=False, por_que="mismo caso con fechas escritas y duración en palabra",
    ),
    dict(
        id="LE_SOLO_INICIO", titulo="El OCR solo pudo leer la FECHA DE INICIO",
        texto=("CERTIFICADO DE INCAPACIDAD\nIPS DEMO\n"
               "Paciente: NOMBRE DEMO  CC 1111111111\n"
               "Fecha Inicio Incapacidad: 20/08/2026\n"
               "Diagnostico: M545\n"),
        espera_revision=False,
        por_que="un solo dato NO es una contradicción: todo lo demás debe ser NO_EVALUABLE",
    ),
    dict(
        id="LE_SOLO_DIAS", titulo="El OCR solo pudo leer los DÍAS",
        texto=("CERTIFICADO DE INCAPACIDAD\nIPS DEMO\nPaciente: NOMBRE DEMO\n"
               "Dias de Incapacidad: 3\nDiagnostico: M545\n"),
        espera_revision=False, por_que="idem: un solo dato no puede contradecir nada",
    ),
    dict(
        id="LE_SOLO_FIN", titulo="El OCR solo pudo leer la FECHA FIN",
        texto=("CERTIFICADO DE INCAPACIDAD\nIPS DEMO\nPaciente: NOMBRE DEMO\n"
               "Fecha Fin Incapacidad: 22/08/2026\nDiagnostico: M545\n"),
        espera_revision=False, por_que="idem",
    ),
    dict(
        id="LF_VACACIONES_FUTURAS", titulo="Vacaciones notificadas con 45 días de antelación",
        texto=plantilla_vacaciones([(HOY + timedelta(days=45), HOY + timedelta(days=60))]),
        espera_revision=False,
        por_que=("una NOTIFICACIÓN de vacaciones es por definición futura; T09_INICIO_EN_FUTURO "
                 "(MEDIA, margen 30 días) no debería mandarla a revisión"),
    ),
    dict(
        id="LG_VACACIONES_2_PERIODOS", titulo="Vacaciones en DOS periodos separados",
        texto=plantilla_vacaciones([(date(2026, 5, 4), date(2026, 5, 8)),
                                    (date(2026, 7, 6), date(2026, 7, 10))]),
        espera_revision=False,
        por_que="el span se come el hueco entre periodos; ninguna regla debe acusar al documento",
    ),
    dict(
        id="LH_RETROACTIVA", titulo="Incapacidad RETROACTIVA (expedida 2 días después del inicio)",
        texto=plantilla_colsubsidio(date(2026, 8, 20), date(2026, 8, 22), 3, "TRES",
                                    expedicion=date(2026, 8, 22)),
        espera_revision=False,
        por_que="la retroactividad es legítima y frecuente: T14 es LEVE y no debe bloquear",
    ),
    dict(
        id="LI_NO_INCLUSIVO", titulo="Emisor con convención NO inclusiva (fin = día de reintegro)",
        texto=plantilla_colsubsidio(date(2026, 8, 20), date(2026, 8, 23), 3, "TRES"),
        espera_revision=None,
        por_que=("RIESGO conocido: si algún emisor imprime en 'Fecha Fin' el día de REINTEGRO, "
                 "T01 (GRAVE) marca desfase +1 en un documento legítimo. El corpus no trae "
                 "ninguno (4/4 reales son inclusivos) — se mide para dejar el número"),
    ),
    dict(
        id="LJ_PRELICENCIA_FUTURA", titulo="Prelicencia de maternidad que empieza en 45 días",
        texto=plantilla_colsubsidio(HOY + timedelta(days=45), HOY + timedelta(days=45 + 125), 126)
              .replace("Enfermedad General", "LICENCIA DE MATERNIDAD"),
        espera_revision=None,
        por_que=("la prelicencia se expide ANTES del parto; con margen de 30 días T09 (MEDIA) "
                 "marca el documento"),
    ),
    dict(
        id="LK_ANIO_TRAS_DURACION", titulo="Rótulo 'Duracion' seguido del AÑO (caso R16 del corpus)",
        texto=("CERTIFICADO DE INCAPACIDAD\nIPS DEMO\nPaciente: NOMBRE DEMO\n"
               "MARTES 09 DE JUNIO Duracion\nDE2026\nDiagnostico: M545\n"),
        espera_revision=False,
        por_que=("el informe de aritmetica_fechas midió que el pipeline leía dias=202 aquí "
                 "(documento REAL): con 202 > 180 T08 (MEDIA) marcaría el documento"),
    ),
    dict(
        id="LN_LARGA_SIN_FIN", titulo="Incapacidad legítima de 210 días sin fecha fin impresa",
        texto=("CERTIFICADO DE INCAPACIDAD\nIPS DEMO\nPaciente: NOMBRE DEMO\n"
               "Fecha Inicio Incapacidad: 01/02/2026\n"
               "Dias de Incapacidad: 210\nDiagnostico: M545\n"),
        espera_revision=None,
        por_que=("una prórroga larga de enfermedad general existe; T08 (MEDIA, umbral 180) la "
                 "manda a revisión sin que haya ninguna contradicción"),
    ),
]


def main() -> None:
    salida = []
    for caso in CASOS:
        rec = registro_como_processor(caso["texto"])
        inca = rec.get("incapacidad") or {}
        snap = inca.get(reglas_tiempo.CLAVE_SNAPSHOT) or {}
        hoy = caso.get("hoy") or HOY
        res = evaluar_doc(rec, hoy)
        ver = res["veredicto"]
        # Camino completo hasta el auxiliar (sin BD: los lookups no resuelven nada).
        mapeo = erp.mapear_a_staging({"incapacidad": rec, "texto_plano": caso["texto"]},
                                     "WHATSAPP", erp.LookupsNulos(), hoy=hoy)
        cods = set(ver.codigos)
        probl_tiempos = [p for p in mapeo["problemas"] if any(c in (mapeo["row"].get("alertas_tiempos") or "")
                                                              for c in cods)] if cods else []
        fila = {
            "id": caso["id"], "hoy": hoy.isoformat(), "titulo": caso["titulo"], "por_que": caso["por_que"],
            "espera_revision": caso["espera_revision"],
            "tipo_documento": rec.get("tipo_documento"),
            "leido": {k: snap.get(k) for k in ("fecha_inicio", "fecha_fin", "dias", "dias_letra")},
            "efectivo": {"fecha_inicio": inca.get("fecha_inicio"), "fecha_fin": inca.get("fecha_fin"),
                         "dias": inca.get("dias"),
                         "inicio_calculada": inca.get("fecha_inicio_calculada"),
                         "fin_recalculada": inca.get("fecha_fin_recalculada")},
            "veredicto": res["informe"]["veredicto"],
            "severidad_tiempos": ver.severidad_max,
            "exige_revision_tiempos": ver.exige_revision,
            "hallazgos": [h.como_dict() for h in ver.hallazgos],
            "alertas_tiempos_fila": mapeo["row"].get("alertas_tiempos"),
            "severidad_tiempos_fila": mapeo["row"].get("severidad_tiempos"),
            "fila_fechainicio": mapeo["row"].get("fechainicio"),
            "fila_fechavencimiento": mapeo["row"].get("fechavencimiento"),
            "fila_numerodias": mapeo["row"].get("Numerodias"),
            "avisos_tiempos": mapeo.get("avisos_tiempos"),
        }
        salida.append(fila)
        marca = "FP!" if (caso["espera_revision"] is False and ver.exige_revision) else \
                ("ok " if caso["espera_revision"] is False else "?? ")
        print(f"\n{'='*100}\n[{marca}] {caso['id']} — {caso['titulo']}")
        print(f"  esperado: {'NO debe exigir revision' if caso['espera_revision'] is False else 'RIESGO a medir'}"
              f" | {caso['por_que']}")
        print(f"  tipo={rec.get('tipo_documento')}  LEIDO inicio={snap.get('fecha_inicio')} "
              f"fin={snap.get('fecha_fin')} dias={snap.get('dias')} letra={snap.get('dias_letra')}")
        print(f"  EFECTIVO inicio={inca.get('fecha_inicio')} fin={inca.get('fecha_fin')} "
              f"dias={inca.get('dias')} calc={inca.get('fecha_inicio_calculada')} "
              f"fin_recalc={inca.get('fecha_fin_recalculada')}")
        print(f"  VEREDICTO {res['informe']['veredicto']} sev={ver.severidad_max} "
              f"exige_revision={ver.exige_revision} cobertura={res['informe']['resumen']['cobertura']}")
        for h in ver.hallazgos:
            print(f"    !! {h.severidad:5} {h.codigo}: {h.mensaje}")
        print(f"  FILA  fechainicio={fila['fila_fechainicio']} venc={fila['fila_fechavencimiento']} "
              f"dias={fila['fila_numerodias']} alertas={fila['alertas_tiempos_fila']}")
    fps = [f["id"] for f in salida if f["espera_revision"] is False and f["exige_revision_tiempos"]]
    riesgos = [f["id"] for f in salida if f["espera_revision"] is None and f["exige_revision_tiempos"]]
    print(f"\n{'='*100}\nFALSOS POSITIVOS confirmados: {len(fps)} -> {fps}")
    print(f"RIESGOS que se materializan:     {len(riesgos)} -> {riesgos}")
    (AQUI / "resultados_atipicos.json").write_text(
        json.dumps(salida, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
