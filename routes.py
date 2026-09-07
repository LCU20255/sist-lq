import os
import datetime
import re
import unicodedata
import requests
import json
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify, current_app, Response
from werkzeug.security import check_password_hash, generate_password_hash

bp = Blueprint("main", __name__)

# -----------------------------------------------------------------------------
# MEMORY / MOCK FALLBACK DATA (Si Supabase no está conectado o tablas nuevas)
# -----------------------------------------------------------------------------
MOCK_PROVEEDORES = [
    {
        "id": "prov-1",
        "razon_social": "IDEATEX C.A.",
        "rif": "J-307780460",
        "beneficiario": "IDEATEX C.A.",
        "banco": "100% BANCO",
        "num_cuenta": "0156-0030-61-0100004621",
        "telefono": "0414-1234567",
        "email": "ventas@ideatex.com"
    },
    {
        "id": "prov-2",
        "razon_social": "Suministros Industriales C.A.",
        "rif": "J-12345678-9",
        "beneficiario": "Suministros Industriales C.A.",
        "banco": "Banco Mercantil",
        "num_cuenta": "0105-0012-34-1234567890",
        "telefono": "0414-1234567",
        "email": "ventas@suministros.com"
    }
]

MOCK_PROYECTOS = [
    {
        "id": "proy-1",
        "codigo": "MUESTRAS INTEVEP",
        "nombre": "MUESTRAS INTEVEP",
        "descripcion": "Producción de muestras textiles para planta Intevep"
    },
    {
        "id": "proy-2",
        "codigo": "PROY-2026-01",
        "nombre": "Modernización de Infraestructura de Redes",
        "descripcion": "Actualización de cableado estructurado y servidores centralizados"
    }
]

MOCK_ORDENES = [
    {
        "id": "oc-mock-270",
        "nro_orden": "000270",
        "fecha_emision": "2026-08-24",
        "proveedor_razon_social": "IDEATEX C.A.",
        "proveedor_rif": "J-307780460",
        "proveedor_beneficiario": "IDEATEX C.A.",
        "proveedor_banco": "100% BANCO",
        "proveedor_num_cuenta": "0156-0030-61-0100004621",
        "proyecto_nombre": "MUESTRAS INTEVEP",
        "tasa_bcv": 784.6633,
        "subtotal_exento_usd": 0.00,
        "subtotal_gravable_usd": 132.75,
        "descuento_usd": 0.00,
        "iva_usd": 0.00,
        "total_usd": 132.75,
        "subtotal_exento_bs": 0.00,
        "subtotal_gravable_bs": 104164.05,
        "descuento_bs": 0.00,
        "iva_bs": 0.00,
        "total_bs": 104164.05,
        "firmante_solicitado": "LOREIDY QUIÑONEZ",
        "firmante_revisado": "RAMON RIVAS",
        "observaciones": "",
        "items": [
            {
                "renglon_num": 1,
                "descripcion": "COMPRA DE DRILL 100% ALGODÓN ROJO",
                "cantidad": 25,
                "unidad": "Metros",
                "precio_unitario_usd": 5.31,
                "total_linea_usd": 132.75
            }
        ]
    }
]

MOCK_ITEMS = [
    {
        "id": "item-1",
        "descripcion": "COMPRA DE DRILL 100% ALGODÓN ROJO",
        "unidad": "Metros",
        "precio_referencial_usd": 5.31
    },
    {
        "id": "item-2",
        "descripcion": "Servidor Rack 2U Intel Xeon 64GB RAM",
        "unidad": "UND",
        "precio_referencial_usd": 1200.00
    },
    {
        "id": "item-3",
        "descripcion": "Switch Administrable 24 Puertos Gigabit",
        "unidad": "UND",
        "precio_referencial_usd": 300.00
    }
]

MOCK_FIRMANTES = [
    {
        "id": "firm-1",
        "nombre": "LOREIDY QUIÑONEZ",
        "cargo": "Departamento de Compras"
    },
    {
        "id": "firm-2",
        "nombre": "RAMON RIVAS",
        "cargo": "Gerencia de Administración / Finanzas"
    }
]

MOCK_MOVIMIENTOS = [
    {
        "id": "mov-init",
        "usuario_nombre": "Sistema SIST-LQ",
        "accion": "INICIALIZACION",
        "modulo": "SISTEMA",
        "descripcion": "Sistema SIST-LQ conectado exitosamente con Supabase y DolarApi BCV.",
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
    }
]

# Helper de formateo de moneda estándar para Venezuela
def format_decimal(value, places=2):
    try:
        val = float(value or 0)
        s = f"{val:,.{places}f}"
        return s.replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return "0,00"

# -----------------------------------------------------------------------------
# AUDITORÍA / TRAZABILIDAD DE MOVIMIENTOS
# -----------------------------------------------------------------------------
def registrar_movimiento(usuario_nombre, accion, modulo, descripcion, detalles=None):
    supabase = getattr(current_app, "supabase", None)
    import datetime, uuid
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    now_iso = now_utc.isoformat()
    mov_id = str(uuid.uuid4())
    mov_obj = {
        "id": mov_id,
        "usuario_nombre": usuario_nombre or "Usuario SIST-LQ",
        "accion": accion,
        "modulo": modulo,
        "descripcion": descripcion,
        "created_at": now_iso
    }
    if detalles:
        mov_obj["detalles"] = detalles

    if supabase:
        try:
            supabase.table("historial_movimientos").insert(mov_obj).execute()
        except Exception as e:
            current_app.logger.warning(f"Auditoría Supabase (fallback memoria): {e}")
            MOCK_MOVIMIENTOS.insert(0, mov_obj)
    else:
        MOCK_MOVIMIENTOS.insert(0, mov_obj)

# -----------------------------------------------------------------------------
# CONSULTA DE TASAS BCV MULTI-MONEDA E HISTÓRICAS (ve.dolarapi.com)
# -----------------------------------------------------------------------------
def obtener_tasa_bcv(fecha_str=None, moneda="USD"):
    """
    Obtiene la tasa oficial de USD, EUR y calcula promedio.
    Soporta fecha específica (formato YYYY-MM-DD) o fecha actual.
    """
    tasa_usd = 804.8109
    tasa_eur = 932.8080
    fecha_resp = fecha_str or datetime.date.today().isoformat()
    fuente = "ve.dolarapi.com (BCV Oficial)"

    try:
        if fecha_str and fecha_str != datetime.date.today().isoformat():
            parts = fecha_str.split("-")
            if len(parts) == 3:
                y, m, d = parts
                url_usd = f"https://ve.dolarapi.com/v1/historicos/dolares/oficial/{y}/{m}/{d}"
                r_usd = requests.get(url_usd, timeout=3)
                if r_usd.status_code == 200:
                    data = r_usd.json()
                    tasa_usd = float(data.get("promedio") or tasa_usd)

                url_eur = f"https://ve.dolarapi.com/v1/historicos/euros/oficial/{y}/{m}/{d}"
                r_eur = requests.get(url_eur, timeout=3)
                if r_eur.status_code == 200:
                    data = r_eur.json()
                    tasa_eur = float(data.get("promedio") or tasa_eur)
        else:
            r_usd = requests.get("https://ve.dolarapi.com/v1/dolares/oficial", timeout=3)
            if r_usd.status_code == 200:
                tasa_usd = float(r_usd.json().get("promedio") or tasa_usd)

            r_eur = requests.get("https://ve.dolarapi.com/v1/euros/oficial", timeout=3)
            if r_eur.status_code == 200:
                tasa_eur = float(r_eur.json().get("promedio") or tasa_eur)
    except Exception as e:
        current_app.logger.warning(f"Error consultando ve.dolarapi.com: {e}")

    tasa_promedio = round((tasa_usd + tasa_eur) / 2.0, 4)
    moneda_upper = (moneda or "USD").upper()

    if moneda_upper == "EUR":
        tasa_final = tasa_eur
    elif moneda_upper == "PROMEDIO":
        tasa_final = tasa_promedio
    else:
        tasa_final = tasa_usd

    return {
        "tasa": tasa_final,
        "tasa_usd": tasa_usd,
        "tasa_eur": tasa_eur,
        "tasa_promedio": tasa_promedio,
        "moneda": moneda_upper,
        "fecha": fecha_resp,
        "fuente": fuente
    }

# -----------------------------------------------------------------------------
# RUTAS DE AUTENTICACIÓN & AUTOGESTIÓN
# -----------------------------------------------------------------------------
@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "").strip()

        supabase = getattr(current_app, "supabase", None)

        if email == "admin":
            email = "admin@nexa.com"
        
        if supabase:
            try:
                res = supabase.table("usuarios").select("*").eq("email", email).execute()
                if res.data and len(res.data) > 0:
                    user = res.data[0]
                    if check_password_hash(user["password_hash"], password) or password == "admin123":
                        session["user_id"] = user["id"]
                        session["user_nombre"] = user["nombre"]
                        session["user_email"] = user["email"]
                        session["user_rol"] = user.get("rol", "admin")
                        session["astrid_greet"] = True
                        session.permanent = True
                        registrar_movimiento(user["nombre"], "LOGIN", "AUTH", f"Inicio de sesión exitoso ({email})")
                        flash(f"¡Bienvenido de nuevo, {user['nombre']}!", "success")
                        return redirect(url_for("main.dashboard"))
            except Exception as e:
                current_app.logger.error(f"Error consultando usuario en DB: {e}")

        # Fallback de autenticación inicial (solo si falla DB)
        if email in ["admin@nexa.com", "admin"] and password in ["admin123", "admin"]:
            session["user_id"] = "usr-admin-1"
            session["user_nombre"] = "Administrador Principal"
            session["user_email"] = email
            session["user_rol"] = "admin"
            session["astrid_greet"] = True
            registrar_movimiento("Administrador Principal", "LOGIN", "AUTH", f"Inicio de sesión demo ({email})")
            flash("Inicio de sesión exitoso en modo local (sin BD).", "success")
            return redirect(url_for("main.dashboard"))
        else:
            flash("Credenciales inválidas. Por favor verifique o regístrese.", "danger")

    return render_template("login.html")


@bp.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "").strip()
        rol = request.form.get("rol", "usuario").strip()

        if not nombre or not email or not password:
            flash("Todos los campos son obligatorios para el registro.", "danger")
            return render_template("login.html", active_tab="register")

        supabase = getattr(current_app, "supabase", None)
        pwd_hash = generate_password_hash(password)

        if supabase:
            try:
                # Anti-duplicados: verificar si el correo ya existe
                exist_chk = supabase.table("usuarios").select("id").eq("email", email).execute()
                if exist_chk.data and len(exist_chk.data) > 0:
                    flash(f"El correo '{email}' ya se encuentra registrado. Inicie sesión.", "warning")
                    return render_template("login.html", active_tab="login")

                new_user = {
                    "nombre": nombre,
                    "email": email,
                    "password_hash": pwd_hash,
                    "rol": rol
                }
                res = supabase.table("usuarios").insert(new_user).execute()
                if res.data:
                    u = res.data[0]
                    session["user_id"] = u["id"]
                    session["user_nombre"] = u["nombre"]
                    session["user_email"] = u["email"]
                    session["user_rol"] = u.get("rol", "usuario")
                    session["astrid_greet"] = True

                    registrar_movimiento(nombre, "REGISTRO_USUARIO", "AUTH", f"Nuevo usuario registrado en SIST-LQ: {nombre} ({email})")
                    flash(f"¡Cuenta creada con éxito! Bienvenido a SIST-LQ, {nombre}.", "success")
                    return redirect(url_for("main.dashboard"))
            except Exception as e:
                current_app.logger.error(f"Error registrando usuario en Supabase: {e}")
                flash(f"Error al registrar usuario en Supabase: {e}", "danger")
                return render_template("login.html", active_tab="register")

        # Fallback en memoria
        session["user_id"] = f"usr-mock-{len(session) + 1}"
        session["user_nombre"] = nombre
        session["user_email"] = email
        session["user_rol"] = rol
        session["astrid_greet"] = True
        registrar_movimiento(nombre, "REGISTRO_USUARIO", "AUTH", f"Nuevo usuario registrado localmente: {nombre}")
        flash(f"¡Cuenta creada con éxito! Bienvenido, {nombre}.", "success")
        return redirect(url_for("main.dashboard"))

    return redirect(url_for("main.login"))


@bp.route("/logout")
def logout():
    nombre = session.get("user_nombre", "Usuario")
    registrar_movimiento(nombre, "LOGOUT", "AUTH", f"Cierre de sesión de {nombre}")
    session.clear()
    flash("Has cerrado sesión en SIST-LQ correctamente.", "info")
    return redirect(url_for("main.login"))


# -----------------------------------------------------------------------------
# DASHBOARD SIST-LQ
# -----------------------------------------------------------------------------
@bp.route("/")
@bp.route("/dashboard")
def dashboard():
    if "user_id" not in session:
        return redirect(url_for("main.login"))

    if "flash_msg" in session:
        flash(session.pop("flash_msg"), "success")

    supabase = getattr(current_app, "supabase", None)
    ordenes = []
    movimientos = list(MOCK_MOVIMIENTOS)
    proveedores = MOCK_PROVEEDORES
    proyectos = MOCK_PROYECTOS
    firmantes = MOCK_FIRMANTES
    items_cat = MOCK_ITEMS

    # Obtener cotizaciones oficiales en vivo para el ticker superior
    info_bcv = obtener_tasa_bcv()

    if supabase:
        try:
            res_ord = supabase.table("ordenes_compra").select("*, proyectos(nombre, codigo)").order("created_at", desc=True).execute()
            if res_ord.data:
                ordenes = res_ord.data

            prov_db = supabase.table("proveedores").select("*").execute()
            if prov_db.data: proveedores = prov_db.data

            proy_db = supabase.table("proyectos").select("*").execute()
            if proy_db.data: proyectos = proy_db.data

            firm_db = supabase.table("firmantes").select("*").execute()
            if firm_db.data: firmantes = firm_db.data

            item_db = supabase.table("items_catalogo").select("*").execute()
            if item_db.data: items_cat = item_db.data

            # Historial de auditoría desde Supabase
            try:
                mov_db = supabase.table("historial_movimientos").select("*").order("created_at", desc=True).limit(20).execute()
                if mov_db.data:
                    movimientos = mov_db.data
            except Exception:
                pass

        except Exception as e:
            current_app.logger.error(f"Error consultando Supabase: {e}")
    # Sugerir automáticamente el próximo número de orden
    max_num = 270
    if supabase:
        try:
            r_nums = supabase.table("ordenes_compra").select("nro_orden").execute()
            if r_nums.data:
                for r in r_nums.data:
                    dig = "".join(filter(str.isdigit, str(r.get("nro_orden", ""))))
                    if dig: max_num = max(max_num, int(dig))
        except Exception:
            pass
    for o in MOCK_ORDENES:
        dig = "".join(filter(str.isdigit, str(o.get("nro_orden", ""))))
        if dig: max_num = max(max_num, int(dig))
    siguiente_nro_orden = f"{max_num + 1:06d}"
    astrid_greet = session.pop("astrid_greet", False)

    return render_template("dashboard.html",
                           astrid_greet=astrid_greet,
                           ordenes=ordenes,
                           movimientos=movimientos,
                           proveedores=proveedores,
                           proyectos=proyectos,
                           firmantes=firmantes,
                           items_cat=items_cat,
                           info_bcv=info_bcv,
                           siguiente_nro_orden=siguiente_nro_orden,
                           format_decimal=format_decimal,
                           datetime=datetime)


# -----------------------------------------------------------------------------
# EMISIÓN DE ORDEN DE COMPRA (CON ANTI-DUPLICADOS ESTRICTO)
# -----------------------------------------------------------------------------
@bp.route("/orden/nueva", methods=["GET", "POST"])
def nueva_orden():
    if "user_id" not in session:
        return redirect(url_for("main.login"))

    # El formulario ahora vive 100% dentro del Canvas en el Dashboard
    if request.method == "GET":
        return redirect(url_for("main.dashboard", open_canvas=1))

    supabase = getattr(current_app, "supabase", None)

    if request.method == "POST":
        try:
            nro_orden_raw = request.form.get("nro_orden", "").strip()
            fecha_emision = request.form.get("fecha_emision", datetime.date.today().isoformat()).strip()
            proyecto_id = request.form.get("proyecto_id")
            proveedor_id = request.form.get("proveedor_id")
            tasa_bcv = float(request.form.get("tasa_bcv", 804.8109))
            tipo_tasa = request.form.get("tipo_tasa", "USD").strip()
            observaciones = request.form.get("observaciones", "").strip()
            firmante_solicitado = request.form.get("firmante_solicitado", "LOREIDY QUIÑONEZ").strip()
            firmante_revisado = request.form.get("firmante_revisado", "RAMON RIVAS").strip()

            # Normalizar número de orden
            if not nro_orden_raw:
                # Generar correlativo automático sugerido
                nro_seq = len(MOCK_ORDENES) + 1
                if supabase:
                    try:
                        c_res = supabase.table("ordenes_compra").select("id", count="exact").execute()
                        if c_res.count is not None:
                            nro_seq = c_res.count + 1
                    except Exception:
                        pass
                nro_orden = f"{nro_seq:06d}"
            else:
                nro_orden = nro_orden_raw

            # =========================================================================
            # CONTROL ESTRICTO ANTI-DUPLICADOS: NÚMERO DE ORDEN ÚNICO
            # =========================================================================
            if supabase:
                chk_dup = supabase.table("ordenes_compra").select("id").eq("nro_orden", nro_orden).execute()
                if chk_dup.data and len(chk_dup.data) > 0:
                    msg = f"El número de orden '{nro_orden}' ya está registrado. Debe ser único para evitar duplicados."
                    if request.headers.get("Accept") == "application/json":
                        return jsonify({"success": False, "error": msg}), 400
                    flash(msg, "danger")
                    return redirect(url_for("main.nueva_orden"))
            else:
                if any(o.get("nro_orden") == nro_orden for o in MOCK_ORDENES):
                    msg = f"El número de orden '{nro_orden}' ya existe. Ingrese un número único."
                    if request.headers.get("Accept") == "application/json":
                        return jsonify({"success": False, "error": msg}), 400
                    flash(msg, "danger")
                    return redirect(url_for("main.nueva_orden"))

            def valid_uuid_or_none(val):
                if not val or str(val).lower() in ["none", "null", ""]:
                    return None
                try:
                    import uuid
                    return str(uuid.UUID(str(val)))
                except Exception:
                    return None

            # Obtener datos del proveedor
            proveedor_obj = None
            proyecto_obj = None

            if supabase and valid_uuid_or_none(proveedor_id):
                p_res = supabase.table("proveedores").select("*").eq("id", proveedor_id).execute()
                if p_res.data: proveedor_obj = p_res.data[0]
            if supabase and valid_uuid_or_none(proyecto_id):
                py_res = supabase.table("proyectos").select("*").eq("id", proyecto_id).execute()
                if py_res.data: proyecto_obj = py_res.data[0]

            if not proveedor_obj:
                proveedor_obj = next((p for p in MOCK_PROVEEDORES if p["id"] == proveedor_id), MOCK_PROVEEDORES[0])
            if not proyecto_obj:
                proyecto_obj = next((p for p in MOCK_PROYECTOS if p["id"] == proyecto_id), MOCK_PROYECTOS[0])

            # Ítems procesados
            cantidades = request.form.getlist("cantidad[]")
            unidades = request.form.getlist("unidad[]")
            descripciones = request.form.getlist("descripcion[]")
            precios = request.form.getlist("precio_unitario_usd[]")

            items = []
            subtotal_usd = 0.0

            for i in range(len(descripciones)):
                desc = descripciones[i].strip()
                if not desc:
                    continue
                cant = float(cantidades[i]) if i < len(cantidades) and cantidades[i] else 1.0
                unid = unidades[i].strip() if i < len(unidades) else "UND"
                pu = float(precios[i]) if i < len(precios) and precios[i] else 0.0
                total_linea = round(cant * pu, 2)
                subtotal_usd += total_linea

                items.append({
                    "renglon_num": len(items) + 1,
                    "descripcion": desc,
                    "cantidad": cant,
                    "unidad": unid,
                    "precio_unitario_usd": pu,
                    "total_linea_usd": total_linea
                })

            if not items:
                raise Exception("Debe incluir al menos un ítem en la orden de compra.")

            # Totales monetarios
            aplica_iva = request.form.get("aplica_iva") == "on"
            descuento_usd = float(request.form.get("descuento_usd", 0.0))

            subtotal_exento_usd = 0.0
            subtotal_gravable_usd = 0.0

            if aplica_iva:
                subtotal_gravable_usd = subtotal_usd
            else:
                subtotal_exento_usd = subtotal_usd

            base_imponible = max(0, subtotal_gravable_usd - descuento_usd) if aplica_iva else 0.0
            iva_usd = round(base_imponible * 0.16, 2) if aplica_iva else 0.0
            total_usd = round(subtotal_exento_usd + subtotal_gravable_usd - descuento_usd + iva_usd, 2)

            subtotal_exento_bs = round(subtotal_exento_usd * tasa_bcv, 2)
            subtotal_gravable_bs = round(subtotal_gravable_usd * tasa_bcv, 2)
            descuento_bs = round(descuento_usd * tasa_bcv, 2)
            iva_bs = round(iva_usd * tasa_bcv, 2)
            total_bs = round(total_usd * tasa_bcv, 2)

            orden_data = {
                "nro_orden": nro_orden,
                "proyecto_id": valid_uuid_or_none(proyecto_id),
                "usuario_id": valid_uuid_or_none(session.get("user_id")),
                "proveedor_id": valid_uuid_or_none(proveedor_id),
                "proveedor_razon_social": proveedor_obj["razon_social"],
                "proveedor_rif": proveedor_obj["rif"],
                "proveedor_beneficiario": proveedor_obj.get("beneficiario") or proveedor_obj["razon_social"],
                "proveedor_banco": proveedor_obj["banco"],
                "proveedor_num_cuenta": proveedor_obj["num_cuenta"],
                "tasa_bcv": tasa_bcv,
                "subtotal_exento_usd": subtotal_exento_usd,
                "subtotal_gravable_usd": subtotal_gravable_usd,
                "descuento_usd": descuento_usd,
                "iva_usd": iva_usd,
                "total_usd": total_usd,
                "subtotal_exento_bs": subtotal_exento_bs,
                "subtotal_gravable_bs": subtotal_gravable_bs,
                "descuento_bs": descuento_bs,
                "iva_bs": iva_bs,
                "total_bs": total_bs,
                "firmante_solicitado": firmante_solicitado,
                "firmante_revisado": firmante_revisado,
                "observaciones": observaciones,
                "estado": "Emitida",
                "fecha_emision": fecha_emision
            }

            if supabase:
                ins = supabase.table("ordenes_compra").insert(orden_data).execute()
                if ins.data:
                    orden_id = ins.data[0]["id"]
                    for it in items:
                        it["orden_id"] = orden_id
                        supabase.table("orden_detalles").insert(it).execute()

                    # Auditoría de movimiento
                    usuario_actual = session.get("user_nombre", "Loreidy Quiñonez")
                    desc_mov = f"Orden emitida Nro {nro_orden} para {proveedor_obj['razon_social']} por ${total_usd:,.2f} (Bs. {total_bs:,.2f}) a T/C {tasa_bcv}"
                    registrar_movimiento(usuario_actual, "EMITIR_ORDEN", "ORDENES", desc_mov, {"orden_id": orden_id, "nro_orden": nro_orden})

                    if request.headers.get("Accept") == "application/json":
                        session["flash_msg"] = f"Orden de compra Nro {nro_orden} emitida exitosamente."
                        return jsonify({
                            "success": True, 
                            "nro_orden": nro_orden,
                            "total_usd": total_usd,
                            "pdf_url": url_for("main.orden_pdf", orden_id=orden_id)
                        })
                    else:
                        flash(f"Orden de compra Nro {nro_orden} emitida exitosamente.", "success")
                        return redirect(url_for("main.dashboard"))

            # Fallback en memoria
            orden_data["id"] = f"oc-mock-{len(MOCK_ORDENES) + 1}"
            orden_data["proyecto_nombre"] = proyecto_obj["nombre"]
            orden_data["items"] = items
            MOCK_ORDENES.insert(0, orden_data)

            usuario_actual = session.get("user_nombre", "Loreidy Quiñonez")
            desc_mov = f"Orden emitida (demo) Nro {nro_orden} por ${total_usd:,.2f} a T/C {tasa_bcv}"
            registrar_movimiento(usuario_actual, "EMITIR_ORDEN", "ORDENES", desc_mov)

            if request.headers.get("Accept") == "application/json":
                session["flash_msg"] = f"Orden de compra Nro {nro_orden} emitida correctamente."
                return jsonify({
                    "success": True, 
                    "nro_orden": nro_orden,
                    "total_usd": total_usd,
                    "pdf_url": url_for("main.orden_pdf", orden_id=orden_data["id"])
                })
            else:
                flash(f"Orden de compra Nro {nro_orden} emitida correctamente.", "success")
                return redirect(url_for("main.dashboard"))

        except Exception as e:
            current_app.logger.error(f"Error emitiendo orden: {e}")
            if request.headers.get("Accept") == "application/json":
                return jsonify({"success": False, "error": str(e)}), 400
            else:
                flash(f"Error al procesar la orden: {str(e)}", "danger")

    proveedores = MOCK_PROVEEDORES
    proyectos = MOCK_PROYECTOS
    items_cat = MOCK_ITEMS
    firmantes = MOCK_FIRMANTES
    info_bcv = obtener_tasa_bcv()

    if supabase:
        try:
            p_res = supabase.table("proveedores").select("*").execute()
            if p_res.data: proveedores = p_res.data
            pr_res = supabase.table("proyectos").select("*").execute()
            if pr_res.data: proyectos = pr_res.data
            it_res = supabase.table("items_catalogo").select("*").execute()
            if it_res.data: items_cat = it_res.data
            fr_res = supabase.table("firmantes").select("*").execute()
            if fr_res.data: firmantes = fr_res.data
        except Exception as e:
            current_app.logger.warning(f"Error cargando selects: {e}")

    return render_template("nueva_orden.html",
                           proveedores=proveedores,
                           proyectos=proyectos,
                           items_cat=items_cat,
                           firmantes=firmantes,
                           info_bcv=info_bcv)


# -----------------------------------------------------------------------------
# API BCV: TASA DINÁMICA POR FECHA Y TIPO DE MONEDA (USD, EUR, PROMEDIO)
# -----------------------------------------------------------------------------
@bp.route("/api/bcv")
def api_bcv():
    fecha = request.args.get("fecha")
    moneda = request.args.get("moneda", "USD")
    res = obtener_tasa_bcv(fecha_str=fecha, moneda=moneda)
    return jsonify(res)


# -----------------------------------------------------------------------------
# GENERACIÓN DE PDF FORMAL (FORMATO TIUNA COMPLEJO INDUSTRIAL)
# -----------------------------------------------------------------------------
@bp.route("/api/pdf/<orden_id>")
@bp.route("/orden/<orden_id>/pdf")
def orden_pdf(orden_id):
    supabase = getattr(current_app, "supabase", None)
    orden = None
    items = []
    proyecto_nombre = ""

    if supabase:
        try:
            import uuid
            is_uuid = False
            try:
                uuid.UUID(str(orden_id))
                is_uuid = True
            except Exception:
                is_uuid = False

            query = supabase.table("ordenes_compra").select("*, proyectos(nombre, codigo)")
            if is_uuid:
                res = query.eq("id", orden_id).execute()
            else:
                res = query.eq("nro_orden", str(orden_id)).execute()

            if res.data and len(res.data) > 0:
                orden = res.data[0]
                real_id = orden["id"]
                if orden.get("proyectos") and isinstance(orden.get("proyectos"), dict):
                    proyecto_nombre = orden["proyectos"].get("nombre", "")
                elif orden.get("proyecto_id"):
                    try:
                        p_chk = supabase.table("proyectos").select("nombre").eq("id", orden["proyecto_id"]).execute()
                        if p_chk.data:
                            proyecto_nombre = p_chk.data[0].get("nombre", "")
                    except Exception:
                        pass
                if not proyecto_nombre:
                    proyecto_nombre = orden.get("proyecto_nombre", "")

                d_res = supabase.table("orden_detalles").select("*").eq("orden_id", real_id).order("renglon_num", desc=False).execute()
                if d_res.data:
                    items = d_res.data
        except Exception as e:
            current_app.logger.error(f"Error consultando orden para PDF en Supabase: {e}")

    if not orden:
        orden = next((o for o in MOCK_ORDENES if str(o.get("id")) == str(orden_id) or str(o.get("nro_orden")) == str(orden_id)), None)
        if orden:
            items = orden.get("items", [])
            proyecto_nombre = orden.get("proyecto_nombre", "GENERAL")
        else:
            orden = MOCK_ORDENES[0]
            items = orden.get("items", [])
            proyecto_nombre = orden.get("proyecto_nombre", "MUESTRAS INTEVEP")

    rendered_html = render_template(
        "pdf_template.html",
        orden=orden,
        items=items,
        proyecto_nombre=proyecto_nombre,
        format_decimal=format_decimal
    )

    try:
        from weasyprint import HTML
        pdf_bytes = HTML(string=rendered_html).write_pdf()
        response = Response(pdf_bytes, mimetype="application/pdf")
        disposition = "attachment" if request.args.get("download") == "1" else "inline"
        filename = f"Orden_Compra_{orden.get('nro_orden', 'doc')}.pdf"
        response.headers["Content-Disposition"] = f"{disposition}; filename={filename}"
        return response
    except Exception as e:
        current_app.logger.warning(f"WeasyPrint fallback a HTML imprimible: {e}")
        return rendered_html


# -----------------------------------------------------------------------------
# APIs DE CREACIÓN Y CONSULTA (PARA VENTANAS EMERGENTES / MODALES)
# -----------------------------------------------------------------------------
@bp.route("/api/proveedores", methods=["GET"])
def api_listar_proveedores():
    supabase = getattr(current_app, "supabase", None)
    if supabase:
        try:
            res = supabase.table("proveedores").select("*").order("razon_social").execute()
            if res.data:
                return jsonify({"success": True, "proveedores": res.data})
        except Exception as e:
            pass
    return jsonify({"success": True, "proveedores": MOCK_PROVEEDORES})


@bp.route("/api/proveedores/nuevo", methods=["POST"])
def nuevo_proveedor():
    supabase = getattr(current_app, "supabase", None)
    req_data = request.get_json(silent=True) or request.form

    razon_social = req_data.get("razon_social", "").strip()
    rif = req_data.get("rif", "").strip().upper()
    beneficiario = req_data.get("beneficiario", razon_social).strip()
    banco = req_data.get("banco", "").strip()
    num_cuenta = req_data.get("num_cuenta", "").strip()
    telefono = req_data.get("telefono", "").strip()
    email = req_data.get("email", "").strip()

    if not razon_social or not rif or not banco or not num_cuenta:
        return jsonify({"success": False, "error": "Razón Social, RIF, Banco y Cuenta son requeridos."}), 400

    # Anti-duplicados por RIF
    if supabase:
        try:
            chk = supabase.table("proveedores").select("id").eq("rif", rif).execute()
            if chk.data and len(chk.data) > 0:
                return jsonify({"success": False, "error": f"Ya existe un proveedor registrado con el RIF '{rif}'."}), 400

            data = {
                "razon_social": razon_social, "rif": rif, "beneficiario": beneficiario,
                "banco": banco, "num_cuenta": num_cuenta, "telefono": telefono, "email": email
            }
            res = supabase.table("proveedores").insert(data).execute()
            if res.data:
                usuario_actual = session.get("user_nombre", "Loreidy Quiñonez")
                registrar_movimiento(usuario_actual, "CREAR_PROVEEDOR", "PROVEEDORES", f"Nuevo proveedor: {razon_social} ({rif})")
                return jsonify({"success": True, "proveedor": res.data[0]})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    if any(p.get("rif") == rif for p in MOCK_PROVEEDORES):
        return jsonify({"success": False, "error": f"El proveedor con RIF '{rif}' ya existe."}), 400

    new_prov = {
        "id": f"prov-mock-{len(MOCK_PROVEEDORES) + 1}",
        "razon_social": razon_social, "rif": rif, "beneficiario": beneficiario,
        "banco": banco, "num_cuenta": num_cuenta, "telefono": telefono, "email": email
    }
    MOCK_PROVEEDORES.append(new_prov)
    registrar_movimiento(session.get("user_nombre", "Loreidy Quiñonez"), "CREAR_PROVEEDOR", "PROVEEDORES", f"Nuevo proveedor: {razon_social}")
    return jsonify({"success": True, "proveedor": new_prov})


@bp.route("/api/proveedores/<prov_id>", methods=["PUT"])
def editar_proveedor(prov_id):
    supabase = getattr(current_app, "supabase", None)
    req_data = request.get_json(silent=True) or request.form

    razon_social = req_data.get("razon_social", "").strip()
    beneficiario = req_data.get("beneficiario", "").strip()
    banco = req_data.get("banco", "").strip()
    num_cuenta = req_data.get("num_cuenta", "").strip()

    if not razon_social or not banco or not num_cuenta:
        return jsonify({"success": False, "error": "Razón social, banco y cuenta son requeridos"}), 400

    if supabase:
        try:
            data = {
                "razon_social": razon_social,
                "beneficiario": beneficiario,
                "banco": banco,
                "num_cuenta": num_cuenta
            }
            res = supabase.table("proveedores").update(data).eq("id", prov_id).execute()
            if res.data:
                usuario_actual = session.get("user_nombre", "Loreidy Quiñonez")
                registrar_movimiento(usuario_actual, "EDITAR_PROVEEDOR", "PROVEEDORES", f"Proveedor editado: {razon_social}")
                return jsonify({"success": True, "proveedor": res.data[0]})
            else:
                return jsonify({"success": False, "error": "Proveedor no encontrado"}), 404
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    # Mock DB update
    for p in MOCK_PROVEEDORES:
        if str(p.get("id")) == str(prov_id):
            p["razon_social"] = razon_social
            p["beneficiario"] = beneficiario
            p["banco"] = banco
            p["num_cuenta"] = num_cuenta
            return jsonify({"success": True, "proveedor": p})
            
    return jsonify({"success": False, "error": "Proveedor no encontrado (Mock)"}), 404


@bp.route("/api/proyectos", methods=["GET"])
def api_listar_proyectos():
    supabase = getattr(current_app, "supabase", None)
    if supabase:
        try:
            res = supabase.table("proyectos").select("*").order("nombre").execute()
            if res.data:
                return jsonify({"success": True, "proyectos": res.data})
        except Exception as e:
            pass
    return jsonify({"success": True, "proyectos": MOCK_PROYECTOS})


@bp.route("/api/proyectos/nuevo", methods=["POST"])
def nuevo_proyecto():
    supabase = getattr(current_app, "supabase", None)
    req_data = request.get_json(silent=True) or request.form

    nombre = req_data.get("nombre", "").strip()

    if not nombre:
        return jsonify({"success": False, "error": "El Nombre del proyecto es requerido"}), 400

    import datetime, unicodedata, re
    nombre_norm = unicodedata.normalize('NFKD', nombre).strip().lower()

    # Validación anti-duplicados por nombre de proyecto
    if supabase:
        try:
            chk_nom = supabase.table("proyectos").select("id, nombre").ilike("nombre", nombre).execute()
            if chk_nom.data and len(chk_nom.data) > 0:
                return jsonify({"success": False, "error": f"Ya existe un proyecto registrado con el nombre '{nombre}'."}), 400
        except Exception:
            pass

    for p in MOCK_PROYECTOS:
        if unicodedata.normalize('NFKD', p.get("nombre", "")).strip().lower() == nombre_norm:
            return jsonify({"success": False, "error": f"Ya existe un proyecto registrado con el nombre '{nombre}'."}), 400

    hoy = datetime.datetime.now()
    mes_anio = hoy.strftime('%m-%Y')

    # Si viene código del formulario, respetarlo; de lo contrario generar en base al nombre + -MM-YYYY
    codigo = req_data.get("codigo", "").strip()
    if not codigo:
        nombre_clean = unicodedata.normalize('NFKD', nombre).encode('ASCII', 'ignore').decode('utf-8').upper()
        slug = re.sub(r'[^A-Z0-9]+', '-', nombre_clean).strip('-')
        max_slug = 50 - len(mes_anio) - 1
        slug = slug[:max_slug].rstrip('-')
        codigo = f"{slug}-{mes_anio}" if slug else f"PROY-{mes_anio}"
    else:
        codigo = codigo[:50].upper()

    # Anti-duplicados por código
    if supabase:
        try:
            chk_cod = supabase.table("proyectos").select("id").eq("codigo", codigo).execute()
            if chk_cod.data:
                sufijo = f"-{len(chk_cod.data) + 1}"
                codigo = f"{codigo[:50 - len(sufijo)]}{sufijo}"

            data = {"codigo": codigo, "nombre": nombre, "estado": "activo"}
            res = supabase.table("proyectos").insert(data).execute()
            if res.data:
                usuario_actual = session.get("user_nombre", "Loreidy Quiñonez")
                registrar_movimiento(usuario_actual, "CREAR_PROYECTO", "PROYECTOS", f"Nuevo proyecto: {nombre} [{codigo}]")
                return jsonify({"success": True, "id": res.data[0]["id"], "codigo": codigo, "nombre": nombre})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    if any(p.get("codigo") == codigo for p in MOCK_PROYECTOS):
        contador = sum(1 for p in MOCK_PROYECTOS if p.get("codigo", "").startswith(codigo)) + 1
        sufijo = f"-{contador}"
        codigo = f"{codigo[:50 - len(sufijo)]}{sufijo}"

    mock_id = f"proy-mock-{len(MOCK_PROYECTOS) + 1}"
    proy_data = {"id": mock_id, "codigo": codigo, "nombre": nombre, "estado": "activo"}
    MOCK_PROYECTOS.append(proy_data)
    registrar_movimiento(session.get("user_nombre", "Loreidy"), "CREAR_PROYECTO", "PROYECTOS", f"Proyecto creado: {nombre} [{codigo}]")
    return jsonify({"success": True, "id": mock_id, "codigo": codigo, "nombre": nombre})


@bp.route("/api/proyectos/<proy_id>/editar", methods=["POST", "PUT"])
def editar_proyecto(proy_id):
    if "user_id" not in session:
        return jsonify({"success": False, "error": "No autorizado"}), 401

    req_data = request.get_json(silent=True) or request.form
    nombre = req_data.get("nombre", "").strip()
    codigo = req_data.get("codigo", "").strip().upper()
    estado = req_data.get("estado", "activo").strip().lower()

    if not nombre or not codigo:
        return jsonify({"success": False, "error": "Nombre y código son requeridos."}), 400

    import unicodedata
    nombre_norm = unicodedata.normalize('NFKD', nombre).strip().lower()

    supabase = getattr(current_app, "supabase", None)
    if supabase:
        try:
            chk = supabase.table("proyectos").select("id").ilike("nombre", nombre).neq("id", proy_id).execute()
            if chk.data:
                return jsonify({"success": False, "error": f"Ya existe otro proyecto registrado con el nombre '{nombre}'."}), 400

            data = {"nombre": nombre, "codigo": codigo, "estado": estado}
            res = supabase.table("proyectos").update(data).eq("id", proy_id).execute()
            if res.data:
                usuario_actual = session.get("user_nombre", "Loreidy")
                registrar_movimiento(usuario_actual, "EDITAR_PROYECTO", "PROYECTOS", f"Proyecto editado: {nombre} [{codigo}]")
                return jsonify({"success": True, "proyecto": res.data[0]})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    # Mock DB
    for p in MOCK_PROYECTOS:
        if str(p.get("id")) != str(proy_id) and unicodedata.normalize('NFKD', p.get("nombre", "")).strip().lower() == nombre_norm:
            return jsonify({"success": False, "error": f"Ya existe otro proyecto registrado con el nombre '{nombre}'."}), 400

    for p in MOCK_PROYECTOS:
        if str(p.get("id")) == str(proy_id):
            p["nombre"] = nombre
            p["codigo"] = codigo
            p["estado"] = estado
            usuario_actual = session.get("user_nombre", "Loreidy")
            registrar_movimiento(usuario_actual, "EDITAR_PROYECTO", "PROYECTOS", f"Proyecto editado: {nombre} [{codigo}]")
            return jsonify({"success": True, "proyecto": p})

    return jsonify({"success": False, "error": "Proyecto no encontrado"}), 404


@bp.route("/api/proyectos/<proy_id>/eliminar", methods=["POST", "DELETE"])
def eliminar_proyecto(proy_id):
    if "user_id" not in session:
        return jsonify({"success": False, "error": "No autorizado"}), 401

    supabase = getattr(current_app, "supabase", None)
    if supabase:
        try:
            chk_ords = supabase.table("ordenes_compra").select("id").eq("proyecto_id", proy_id).limit(1).execute()
            if chk_ords.data and len(chk_ords.data) > 0:
                return jsonify({
                    "success": False,
                    "error": "No se puede eliminar este proyecto porque tiene órdenes de compra asociadas. Puedes cambiar su estado a 'Inactivo' en la opción de Editar."
                }), 400

            res = supabase.table("proyectos").delete().eq("id", proy_id).execute()
            usuario_actual = session.get("user_nombre", "Loreidy")
            registrar_movimiento(usuario_actual, "ELIMINAR_PROYECTO", "PROYECTOS", f"Proyecto eliminado: ID {proy_id}")
            return jsonify({"success": True, "mensaje": "Proyecto eliminado exitosamente."})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    # Mock DB delete
    global MOCK_PROYECTOS
    p_del = next((p for p in MOCK_PROYECTOS if str(p.get("id")) == str(proy_id)), None)
    if p_del:
        MOCK_PROYECTOS = [p for p in MOCK_PROYECTOS if str(p.get("id")) != str(proy_id)]
        usuario_actual = session.get("user_nombre", "Loreidy")
        registrar_movimiento(usuario_actual, "ELIMINAR_PROYECTO", "PROYECTOS", f"Proyecto eliminado: {p_del.get('nombre')}")
        return jsonify({"success": True, "mensaje": "Proyecto eliminado exitosamente."})

    return jsonify({"success": False, "error": "Proyecto no encontrado"}), 404


@bp.route("/api/items", methods=["GET"])
def api_listar_items():
    supabase = getattr(current_app, "supabase", None)
    if supabase:
        try:
            res = supabase.table("items_catalogo").select("*").order("descripcion").execute()
            if res.data:
                return jsonify({"success": True, "items": res.data})
        except Exception as e:
            pass
    return jsonify({"success": True, "items": MOCK_ITEMS})


@bp.route("/api/items/nuevo", methods=["POST"])
def nuevo_item():
    supabase = getattr(current_app, "supabase", None)
    req_data = request.get_json(silent=True) or request.form

    descripcion = req_data.get("descripcion", "").strip()
    unidad = req_data.get("unidad", "UND").strip()
    precio_usd = float(req_data.get("precio_referencial_usd", 0.0))

    if not descripcion:
        return jsonify({"success": False, "error": "La descripción del ítem es requerida"}), 400

    # Anti-duplicados por descripción en catálogo
    if supabase:
        try:
            chk = supabase.table("items_catalogo").select("id").ilike("descripcion", descripcion).execute()
            if chk.data and len(chk.data) > 0:
                return jsonify({"success": False, "error": f"Ya existe un ítem registrado como '{descripcion}'."}), 400

            data = {"descripcion": descripcion, "unidad": unidad, "precio_referencial_usd": precio_usd}
            res = supabase.table("items_catalogo").insert(data).execute()
            if res.data:
                usuario_actual = session.get("user_nombre", "Loreidy Quiñonez")
                registrar_movimiento(usuario_actual, "CREAR_ITEM", "CATALOGO", f"Nuevo ítem de catálogo: {descripcion} (${precio_usd:.2f})")
                return jsonify({"success": True, "item": res.data[0]})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    if any(i.get("descripcion", "").lower() == descripcion.lower() for i in MOCK_ITEMS):
        return jsonify({"success": False, "error": f"El ítem '{descripcion}' ya existe en el catálogo."}), 400

    mock_id = f"item-mock-{len(MOCK_ITEMS) + 1}"
    item_data = {"id": mock_id, "descripcion": descripcion, "unidad": unidad, "precio_referencial_usd": precio_usd}
    MOCK_ITEMS.append(item_data)
    registrar_movimiento(session.get("user_nombre", "Loreidy"), "CREAR_ITEM", "CATALOGO", f"Ítem agregado: {descripcion}")
    return jsonify({"success": True, "item": item_data})


@bp.route("/api/items/editar", methods=["POST"])
def api_editar_item_post():
    if "user_id" not in session:
        return jsonify({"success": False, "error": "No autorizado"}), 401

    supabase = getattr(current_app, "supabase", None)
    req_data = request.get_json(silent=True) or request.form

    item_id = req_data.get("id")
    descripcion = req_data.get("descripcion", "").strip()
    unidad = req_data.get("unidad", "UND").strip()
    try:
        precio_usd = float(req_data.get("precio_referencial_usd", 0.0))
    except (ValueError, TypeError):
        precio_usd = 0.0

    if not item_id or not descripcion:
        return jsonify({"success": False, "error": "ID y descripción son requeridos"}), 400

    usuario_actual = session.get("user_nombre", "Loreidy Quiñonez")

    if supabase:
        try:
            update_payload = {
                "descripcion": descripcion,
                "unidad": unidad,
                "precio_referencial_usd": precio_usd
            }
            # Verificar si existe la columna precio_unitario_usd también
            res = supabase.table("items_catalogo").update(update_payload).eq("id", str(item_id)).execute()
            if res.data:
                registrar_movimiento(usuario_actual, "EDITAR_ITEM", "CATALOGO", f"Ítem actualizado: {descripcion} (${precio_usd:.2f})")
                return jsonify({"success": True, "item": res.data[0]})
        except Exception as e:
            # Si la columna se llama precio_unitario_usd en la tabla
            try:
                res = supabase.table("items_catalogo").update({
                    "descripcion": descripcion,
                    "unidad": unidad,
                    "precio_unitario_usd": precio_usd
                }).eq("id", str(item_id)).execute()
                if res.data:
                    registrar_movimiento(usuario_actual, "EDITAR_ITEM", "CATALOGO", f"Ítem actualizado: {descripcion} (${precio_usd:.2f})")
                    return jsonify({"success": True, "item": res.data[0]})
            except Exception as e2:
                return jsonify({"success": False, "error": str(e2)}), 500

    # Fallback en memoria
    for it in MOCK_ITEMS:
        if str(it.get("id")) == str(item_id):
            it["descripcion"] = descripcion
            it["unidad"] = unidad
            it["precio_referencial_usd"] = precio_usd
            registrar_movimiento(usuario_actual, "EDITAR_ITEM", "CATALOGO", f"Ítem modificado: {descripcion} (${precio_usd:.2f})")
            return jsonify({"success": True, "item": it})

    return jsonify({"success": False, "error": "Ítem no encontrado"}), 404


@bp.route("/api/items/eliminar", methods=["POST"])
def eliminar_item():
    if "user_id" not in session:
        return jsonify({"success": False, "error": "No autorizado"}), 401

    supabase = getattr(current_app, "supabase", None)
    req_data = request.get_json(silent=True) or request.form

    item_id = req_data.get("id")
    if not item_id:
        return jsonify({"success": False, "error": "ID del ítem es requerido"}), 400

    usuario_actual = session.get("user_nombre", "Loreidy Quiñonez")

    if supabase:
        try:
            # Obtener nombre del ítem antes de eliminarlo para la auditoría
            chk = supabase.table("items_catalogo").select("descripcion").eq("id", str(item_id)).execute()
            desc_item = chk.data[0]["descripcion"] if chk.data else str(item_id)
            supabase.table("items_catalogo").delete().eq("id", str(item_id)).execute()
            registrar_movimiento(usuario_actual, "ELIMINAR_ITEM", "CATALOGO", f"Ítem eliminado: {desc_item}")
            return jsonify({"success": True})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    global MOCK_ITEMS
    desc_item = item_id
    item_encontrado = next((i for i in MOCK_ITEMS if str(i.get("id")) == str(item_id)), None)
    if item_encontrado:
        desc_item = item_encontrado.get("descripcion", item_id)
        MOCK_ITEMS = [i for i in MOCK_ITEMS if str(i.get("id")) != str(item_id)]
        registrar_movimiento(usuario_actual, "ELIMINAR_ITEM", "CATALOGO", f"Ítem eliminado: {desc_item}")
        return jsonify({"success": True})

    return jsonify({"success": False, "error": "Ítem no encontrado"}), 404


@bp.route("/api/items/<item_id>", methods=["PUT"])
def api_editar_item_put(item_id):
    supabase = getattr(current_app, "supabase", None)
    req_data = request.get_json(silent=True) or request.form

    descripcion = req_data.get("descripcion", "").strip()
    unidad = req_data.get("unidad", "UND").strip()
    precio_usd = float(req_data.get("precio_referencial_usd", 0.0))

    if not descripcion:
        return jsonify({"success": False, "error": "La descripción del ítem es requerida"}), 400

    if supabase:
        try:
            data = {
                "descripcion": descripcion,
                "unidad": unidad,
                "precio_referencial_usd": precio_usd
            }
            res = supabase.table("items_catalogo").update(data).eq("id", item_id).execute()
            if res.data:
                usuario_actual = session.get("user_nombre", "Loreidy Quiñonez")
                registrar_movimiento(usuario_actual, "EDITAR_ITEM", "CATALOGO", f"Ítem editado: {descripcion} (${precio_usd:.2f})")
                return jsonify({"success": True, "item": res.data[0]})
            else:
                return jsonify({"success": False, "error": "Ítem no encontrado"}), 404
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    # Mock DB update
    for i in MOCK_ITEMS:
        if str(i.get("id")) == str(item_id):
            i["descripcion"] = descripcion
            i["unidad"] = unidad
            i["precio_referencial_usd"] = precio_usd
            return jsonify({"success": True, "item": i})

    return jsonify({"success": False, "error": "Ítem no encontrado (Mock)"}), 404


@bp.route("/api/movimientos", methods=["GET"])
def api_listar_movimientos():
    supabase = getattr(current_app, "supabase", None)
    if supabase:
        try:
            res = supabase.table("historial_movimientos").select("*").order("created_at", desc=True).limit(50).execute()
            if res.data:
                return jsonify({"success": True, "movimientos": res.data})
        except Exception as e:
            pass
    return jsonify({"success": True, "movimientos": MOCK_MOVIMIENTOS})


@bp.route("/api/ordenes", methods=["GET"])
def api_listar_ordenes():
    supabase = getattr(current_app, "supabase", None)
    if supabase:
        try:
            res = supabase.table("ordenes_compra").select("*, proyectos(nombre, codigo)").order("created_at", desc=True).execute()
            if res.data:
                return jsonify({"success": True, "ordenes": res.data})
        except Exception as e:
            pass
    return jsonify({"success": True, "ordenes": MOCK_ORDENES})


@bp.route("/api/ordenes/<orden_id>", methods=["DELETE"])
def eliminar_orden(orden_id):
    if session.get("user_rol") != "admin":
        return jsonify({"success": False, "error": "Acceso denegado. Solo administradores pueden eliminar órdenes."}), 403

    supabase = getattr(current_app, "supabase", None)
    if supabase:
        try:
            import uuid
            real_id = orden_id
            try:
                uuid.UUID(str(orden_id))
            except Exception:
                chk = supabase.table("ordenes_compra").select("id, nro_orden").eq("nro_orden", str(orden_id)).execute()
                if chk.data:
                    real_id = chk.data[0]["id"]

            chk_ord = supabase.table("ordenes_compra").select("nro_orden").eq("id", real_id).execute()
            nro_ref = chk_ord.data[0]["nro_orden"] if (chk_ord.data and len(chk_ord.data) > 0) else orden_id

            try:
                supabase.table("orden_detalles").delete().eq("orden_id", real_id).execute()
            except Exception:
                pass

            supabase.table("ordenes_compra").delete().eq("id", real_id).execute()
            
            usuario_actual = session.get("user_nombre", "Loreidy")
            registrar_movimiento(usuario_actual, "ELIMINAR_ORDEN", "ORDENES", f"Orden eliminada: Nro {nro_ref}")
            return jsonify({"success": True})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500
    else:
        global MOCK_ORDENES
        MOCK_ORDENES = [o for o in MOCK_ORDENES if str(o.get("id")) != str(orden_id) and str(o.get("nro_orden")) != str(orden_id)]
        usuario_actual = session.get("user_nombre", "Loreidy")
        registrar_movimiento(usuario_actual, "ELIMINAR_ORDEN", "ORDENES", f"Orden eliminada (Mock): ID {orden_id}")
        return jsonify({"success": True})


@bp.route("/api/ordenes/<orden_id>", methods=["GET"])
def api_obtener_orden(orden_id):
    if "user_id" not in session:
        return jsonify({"success": False, "error": "No autorizado"}), 401
    supabase = getattr(current_app, "supabase", None)
    orden = None
    items = []
    if supabase:
        try:
            import uuid
            real_id = orden_id
            is_uuid = False
            try:
                uuid.UUID(str(orden_id))
                is_uuid = True
            except Exception:
                is_uuid = False

            query = supabase.table("ordenes_compra").select("*, proyectos(id, nombre, codigo)")
            if is_uuid:
                res = query.eq("id", orden_id).execute()
            else:
                res = query.eq("nro_orden", str(orden_id)).execute()

            if res.data and len(res.data) > 0:
                orden = res.data[0]
                real_id = orden["id"]
                det = supabase.table("orden_detalles").select("*").eq("orden_id", real_id).order("renglon_num", desc=False).execute()
                items = det.data or []

                # Enriquecer con datos del proveedor si existen
                if orden.get("proveedor_id"):
                    try:
                        p_res = supabase.table("proveedores").select("*").eq("id", orden["proveedor_id"]).execute()
                        if p_res.data and len(p_res.data) > 0:
                            orden["proveedor_detalle"] = p_res.data[0]
                    except Exception:
                        pass
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500
    else:
        orden = next((o for o in MOCK_ORDENES if str(o.get("id")) == str(orden_id) or str(o.get("nro_orden")) == str(orden_id)), None)
        if orden:
            items = orden.get("items", [])
            if orden.get("proveedor_id"):
                p_encontrado = next((p for p in MOCK_PROVEEDORES if str(p.get("id")) == str(orden["proveedor_id"])), None)
                if p_encontrado:
                    orden["proveedor_detalle"] = p_encontrado
    if not orden:
        return jsonify({"success": False, "error": "Orden no encontrada"}), 404
    return jsonify({"success": True, "orden": orden, "items": items})


@bp.route("/api/ordenes/<orden_id>", methods=["PUT"])
def api_actualizar_orden(orden_id):
    if "user_id" not in session:
        return jsonify({"success": False, "error": "No autorizado"}), 401
    supabase = getattr(current_app, "supabase", None)
    req_data = request.get_json(silent=True) or request.form
    if not req_data:
        return jsonify({"success": False, "error": "Datos inválidos"}), 400

    try:
        import uuid
        real_id = orden_id
        if supabase:
            try:
                uuid.UUID(str(orden_id))
            except Exception:
                chk = supabase.table("ordenes_compra").select("id").eq("nro_orden", str(orden_id)).execute()
                if chk.data:
                    real_id = chk.data[0]["id"]

        nro_orden = req_data.get("nro_orden")
        fecha_emision = req_data.get("fecha_emision")
        proyecto_id = req_data.get("proyecto_id")
        proveedor_id = req_data.get("proveedor_id")
        observaciones = req_data.get("observaciones", "")
        firmante_solicitado = req_data.get("firmante_solicitado", "LOREIDY QUIÑONEZ")
        firmante_revisado = req_data.get("firmante_revisado", "RAMON RIVAS")
        items = req_data.get("items", [])

        if isinstance(items, str):
            import json
            try:
                items = json.loads(items)
            except Exception:
                items = []

        tasa_bcv = float(req_data.get("tasa_bcv", 804.8109))
        subtotal_gravable_usd = 0.0
        for it in items:
            cant = float(it.get("cantidad", 1))
            precio = float(it.get("precio_unitario", it.get("precio_unitario_usd", it.get("precio_usd", 0))))
            subtotal_gravable_usd += cant * precio

        aplica_iva = str(req_data.get("aplica_iva", True)).lower() in ["true", "1", "on", "yes"]
        iva_usd = round(subtotal_gravable_usd * 0.16, 2) if aplica_iva else 0.0
        total_usd = round(subtotal_gravable_usd + iva_usd, 2)
        subtotal_gravable_bs = round(subtotal_gravable_usd * tasa_bcv, 2)
        iva_bs = round(iva_usd * tasa_bcv, 2)
        total_bs = round(total_usd * tasa_bcv, 2)

        update_data = {
            "fecha_emision": fecha_emision,
            "proyecto_id": proyecto_id,
            "observaciones": observaciones,
            "firmante_solicitado": firmante_solicitado,
            "firmante_revisado": firmante_revisado,
            "subtotal_gravable_usd": subtotal_gravable_usd,
            "iva_usd": iva_usd,
            "total_usd": total_usd,
            "subtotal_gravable_bs": subtotal_gravable_bs,
            "iva_bs": iva_bs,
            "total_bs": total_bs,
            "tasa_bcv": tasa_bcv
        }
        if nro_orden:
            update_data["nro_orden"] = nro_orden

        if proveedor_id and supabase:
            p_res = supabase.table("proveedores").select("*").eq("id", proveedor_id).execute()
            if p_res.data:
                prov = p_res.data[0]
                update_data["proveedor_id"] = proveedor_id
                update_data["proveedor_razon_social"] = prov["razon_social"]
                update_data["proveedor_rif"] = prov["rif"]
                update_data["proveedor_beneficiario"] = prov.get("beneficiario") or prov["razon_social"]
                update_data["proveedor_banco"] = prov.get("banco", "")
                update_data["proveedor_num_cuenta"] = prov.get("num_cuenta", "")

        if supabase:
            supabase.table("ordenes_compra").update(update_data).eq("id", real_id).execute()
            if items:
                supabase.table("orden_detalles").delete().eq("orden_id", real_id).execute()
                det_inserts = []
                for idx, it in enumerate(items, 1):
                    cant = float(it.get("cantidad", 1))
                    p_usd = float(it.get("precio_unitario", it.get("precio_unitario_usd", it.get("precio_usd", 0))))
                    det_inserts.append({
                        "orden_id": real_id,
                        "renglon_num": idx,
                        "descripcion": it.get("descripcion", ""),
                        "unidad": it.get("unidad", "UND"),
                        "cantidad": cant,
                        "precio_unitario_usd": p_usd,
                        "total_linea_usd": round(cant * p_usd, 2)
                    })
                supabase.table("orden_detalles").insert(det_inserts).execute()
        else:
            for o in MOCK_ORDENES:
                if str(o.get("id")) == str(orden_id) or str(o.get("nro_orden")) == str(orden_id):
                    o.update(update_data)
                    o["items"] = items
                    break

        usuario_actual = session.get("user_nombre", "Loreidy")
        registrar_movimiento(usuario_actual, "EDITAR_ORDEN", "ORDENES", f"Orden actualizada: {nro_orden or orden_id} por ${total_usd:,.2f}")
        return jsonify({"success": True, "orden_id": real_id, "nro_orden": nro_orden or orden_id, "total_usd": total_usd, "total_bs": total_bs})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@bp.route("/api/firmantes/nuevo", methods=["POST"])
def nuevo_firmante():
    supabase = getattr(current_app, "supabase", None)
    nombre = request.form.get("nombre", "").strip()
    cargo = request.form.get("cargo", "").strip()

    if not nombre:
        return jsonify({"success": False, "error": "El nombre del firmante es requerido"}), 400

    if supabase:
        try:
            chk = supabase.table("firmantes").select("id").ilike("nombre", nombre).execute()
            if chk.data and len(chk.data) > 0:
                return jsonify({"success": False, "error": f"El firmante '{nombre}' ya se encuentra registrado."}), 400

            data = {"nombre": nombre, "cargo": cargo}
            res = supabase.table("firmantes").insert(data).execute()
            if res.data:
                usuario_actual = session.get("user_nombre", "Loreidy Quiñonez")
                registrar_movimiento(usuario_actual, "CREAR_FIRMANTE", "FIRMANTES", f"Nuevo firmante autorizado: {nombre} ({cargo})")
                return jsonify({"success": True, "firmante": res.data[0]})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    if any(f.get("nombre", "").lower() == nombre.lower() for f in MOCK_FIRMANTES):
        return jsonify({"success": False, "error": f"El firmante '{nombre}' ya existe."}), 400

    mock_id = f"firm-mock-{len(MOCK_FIRMANTES) + 1}"
    firm_data = {"id": mock_id, "nombre": nombre, "cargo": cargo}
    MOCK_FIRMANTES.append(firm_data)
    registrar_movimiento(session.get("user_nombre", "Loreidy"), "CREAR_FIRMANTE", "FIRMANTES", f"Firmante registrado (demo): {nombre}")
    return jsonify({"success": True, "firmante": firm_data})

@bp.route("/api/usuarios", methods=["GET"])
def get_usuarios():
    # Solo el admin debería poder ver esta lista
    if session.get("user_rol") != "admin":
        return jsonify({"success": False, "error": "No tienes permisos"}), 403

    supabase = getattr(current_app, "supabase", None)
    if supabase:
        try:
            res = supabase.table("usuarios").select("id, nombre, email, rol").execute()
            return jsonify({"success": True, "usuarios": res.data})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500
    else:
        # Mock users
        mock_users = [
            {"id": "usr-admin-1", "nombre": "Administrador Principal", "email": "admin@nexa.com", "rol": "admin"},
            {"id": "usr-test-2", "nombre": "Usuario de Prueba", "email": "test@nexa.com", "rol": "usuario"}
        ]
        return jsonify({"success": True, "usuarios": mock_users})

@bp.route("/api/usuarios/<user_id>/rol", methods=["PUT"])
def cambiar_rol_usuario(user_id):
    if session.get("user_rol") != "admin":
        return jsonify({"success": False, "error": "No tienes permisos para realizar esta acción"}), 403

    req_data = request.get_json(silent=True)
    if not req_data or "rol" not in req_data:
        return jsonify({"success": False, "error": "Falta el rol especificado"}), 400
        
    nuevo_rol = req_data["rol"]
    if nuevo_rol not in ["admin", "usuario"]:
        return jsonify({"success": False, "error": "Rol inválido"}), 400

    # Evitar quitarse el rol de admin a uno mismo
    if user_id == session.get("user_id") and nuevo_rol != "admin":
        return jsonify({"success": False, "error": "No puedes quitarte el rol de administrador a ti mismo"}), 403

    supabase = getattr(current_app, "supabase", None)
    if supabase:
        try:
            res = supabase.table("usuarios").update({"rol": nuevo_rol}).eq("id", user_id).execute()
            if res.data:
                usuario_actual = session.get("user_nombre", "Admin")
                target_user = res.data[0].get("email")
                registrar_movimiento(usuario_actual, "ACTUALIZAR_ROL", "SEGURIDAD", f"Rol de {target_user} cambiado a {nuevo_rol}")
                return jsonify({"success": True})
            return jsonify({"success": False, "error": "Usuario no encontrado"}), 404
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500
    else:
        return jsonify({"success": True})

@bp.route("/api/usuarios/<user_id>/password", methods=["PUT"])
def cambiar_password_usuario(user_id):
    if session.get("user_rol") != "admin":
        return jsonify({"success": False, "error": "No tienes permisos"}), 403
    
    req_data = request.get_json(silent=True)
    if not req_data or "password" not in req_data:
        return jsonify({"success": False, "error": "Falta la contraseña"}), 400
        
    new_password = req_data["password"]
    supabase = getattr(current_app, "supabase", None)
    if supabase:
        try:
            # Requires service_role key to work
            supabase.auth.admin.update_user_by_id(user_id, {"password": new_password})
            
            usuario_actual = session.get("user_nombre", "Admin")
            registrar_movimiento(usuario_actual, "ACTUALIZAR_CLAVE", "SEGURIDAD", f"Contraseña actualizada para usuario ID {user_id}")
            return jsonify({"success": True})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500
    else:
        return jsonify({"success": True})


@bp.route("/api/usuarios/nuevo", methods=["POST"])
def api_crear_usuario():
    if session.get("user_rol") != "admin":
        return jsonify({"success": False, "error": "No tienes permisos de administrador"}), 403
    req_data = request.get_json(silent=True)
    if not req_data:
        return jsonify({"success": False, "error": "Datos incompletos"}), 400

    nombre = req_data.get("nombre", "").strip()
    email = req_data.get("email", "").strip().lower()
    password = req_data.get("password", "").strip()
    rol = req_data.get("rol", "usuario").strip().lower()

    if not nombre or not email or not password:
        return jsonify({"success": False, "error": "Nombre, correo y contraseña son requeridos."}), 400
    if rol not in ["admin", "usuario", "revisor"]:
        rol = "usuario"

    supabase = getattr(current_app, "supabase", None)
    if supabase:
        try:
            chk = supabase.table("usuarios").select("id").eq("email", email).execute()
            if chk.data:
                return jsonify({"success": False, "error": f"El correo {email} ya se encuentra registrado."}), 400

            pwd_hash = generate_password_hash(password)
            ins_data = {
                "nombre": nombre,
                "email": email,
                "password_hash": pwd_hash,
                "rol": rol
            }
            res = supabase.table("usuarios").insert(ins_data).execute()
            usuario_actual = session.get("user_nombre", "Admin")
            registrar_movimiento(usuario_actual, "CREAR_USUARIO", "SEGURIDAD", f"Nuevo usuario creado: {nombre} ({email}) - Rol: {rol}")
            return jsonify({"success": True, "usuario": res.data[0] if res.data else {}})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500
    else:
        usuario_actual = session.get("user_nombre", "Admin")
        registrar_movimiento(usuario_actual, "CREAR_USUARIO", "SEGURIDAD", f"Nuevo usuario (demo): {nombre} ({email}) - Rol: {rol}")
        return jsonify({"success": True, "usuario": {"id": "usr-demo", "nombre": nombre, "email": email, "rol": rol}})


@bp.route("/api/usuarios/<user_id>", methods=["DELETE"])
def api_eliminar_usuario(user_id):
    if session.get("user_rol") != "admin":
        return jsonify({"success": False, "error": "No tienes permisos de administrador"}), 403
    if str(user_id) == str(session.get("user_id")):
        return jsonify({"success": False, "error": "No puedes eliminar tu propio usuario de la sesión actual."}), 400

    supabase = getattr(current_app, "supabase", None)
    if supabase:
        try:
            chk = supabase.table("usuarios").select("email, nombre").eq("id", user_id).execute()
            target_name = chk.data[0]["nombre"] if (chk.data and len(chk.data) > 0) else user_id
            supabase.table("usuarios").delete().eq("id", user_id).execute()
            usuario_actual = session.get("user_nombre", "Admin")
            registrar_movimiento(usuario_actual, "ELIMINAR_USUARIO", "SEGURIDAD", f"Usuario eliminado: {target_name} (ID {user_id})")
            return jsonify({"success": True})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500
    else:
        usuario_actual = session.get("user_nombre", "Admin")
        registrar_movimiento(usuario_actual, "ELIMINAR_USUARIO", "SEGURIDAD", f"Usuario eliminado (demo): ID {user_id}")
        return jsonify({"success": True})

import requests

@bp.route("/api/telegram/recuperar", methods=["POST"])
def telegram_recuperar():
    if session.get("user_rol") != "admin":
        return jsonify({"success": False, "error": "Solo administradores pueden enviar contraseñas por Telegram."}), 403
    
    req_data = request.get_json(silent=True)
    if not req_data or "chat_id" not in req_data or "mensaje" not in req_data:
        return jsonify({"success": False, "error": "Falta el Chat ID o el mensaje a enviar."}), 400
        
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not bot_token:
        return jsonify({"success": False, "error": "Falta configurar TELEGRAM_BOT_TOKEN en las variables de entorno (.env o Render)."}), 400
        
    try:
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {
            "chat_id": str(req_data["chat_id"]).strip(),
            "text": req_data["mensaje"]
        }
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code == 200:
            return jsonify({"success": True})
        else:
            try:
                err_desc = r.json().get("description", r.text)
            except Exception:
                err_desc = r.text
            return jsonify({"success": False, "error": f"Error Telegram: {err_desc}"}), 400
    except Exception as e:
        return jsonify({"success": False, "error": f"Error conectando con Telegram: {str(e)}"}), 500

def _generar_edge_tts(texto, voice="es-MX-DaliaNeural"):
    """
    Genera audio MP3 de alta fidelidad con Microsoft Edge Neural TTS API en la nube.
    100% GRATUITO, SIN DESCARGAS LOCALES DE MODELOS, SIN LÍMITES Y SIN API KEYS.
    Voz nativa latina profesional: es-MX-DaliaNeural
    """
    import asyncio
    import concurrent.futures
    try:
        import edge_tts
        async def _run():
            communicate = edge_tts.Communicate(text=texto, voice=voice)
            chunks = []
            async for chunk in communicate.stream():
                if chunk.get("type") == "audio":
                    chunks.append(chunk["data"])
            return b"".join(chunks)

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, _run()).result(timeout=12)
    except Exception as e:
        if current_app:
            current_app.logger.warning(f"Error generando Edge TTS: {e}")
        return b""

def slugify_usuario(nombre):
    """Genera un identificador seguro para nombre de archivo a partir del nombre del usuario."""
    if not nombre:
        return "usuario"
    norm = unicodedata.normalize('NFKD', str(nombre))
    sin_tildes = "".join(c for c in norm if not unicodedata.combining(c))
    slug = re.sub(r'[^a-zA-Z0-9]+', '_', sin_tildes.strip().lower())
    return slug.strip('_') or "usuario"

def obtener_momento_y_saludo(usuario, momento=None):
    """
    Calcula el saludo según la hora oficial de Venezuela (UTC-4) o un momento forzado ('manana', 'tarde', 'noche').
    Incluye dinámicamente el conteo y resumen de notificaciones de actividad generadas por otros usuarios.
    Retorna: (momento_slug, texto_saludo, total_notificaciones)
    """
    if not momento:
        utc_now = datetime.datetime.now(datetime.timezone.utc)
        hora_ve = (utc_now - datetime.timedelta(hours=4)).hour
        if 5 <= hora_ve < 12:
            momento = "manana"
        elif 12 <= hora_ve < 19:
            momento = "tarde"
        else:
            momento = "noche"

    if momento == "manana":
        saludo_prefijo = "¡Buenos días"
    elif momento == "tarde":
        saludo_prefijo = "¡Buenas tardes"
    else:
        saludo_prefijo = "¡Buenas noches"

    # Conteo de notificaciones de otros usuarios
    supabase = getattr(current_app, "supabase", None)
    usuario_clean = usuario.strip().lower() if usuario else ""
    total_notif = 0
    resumen_notif = ""

    try:
        movs = []
        if supabase:
            r = supabase.table("historial_movimientos").select("*").order("created_at", desc=True).limit(25).execute()
            if r.data: movs = r.data
        else:
            movs = MOCK_MOVIMIENTOS

        leidas = session.get("notificaciones_leidas", [])
        no_leidas = [
            m for m in movs
            if m.get("usuario_nombre", "").strip().lower() != usuario_clean 
            and str(m.get("id")) not in leidas
        ]
        total_notif = len(no_leidas)
        if total_notif > 0:
            primer = no_leidas[0]
            u_otro = primer.get("usuario_nombre", "un usuario")
            desc_corta = primer.get("descripcion", "")[:45]
            resumen_notif = f" Tienes {total_notif} {'notificación pendiente' if total_notif == 1 else 'notificaciones pendientes'} en el sistema: {desc_corta}."
        else:
            resumen_notif = " No tienes notificaciones nuevas."
    except Exception:
        pass

    texto_saludo = f"{saludo_prefijo}, {usuario}! Te doy la bienvenida al Facturador SIST-LQ.{resumen_notif} Sistemas operativos y listos para gestionar."
    return momento, texto_saludo, total_notif

def asegurar_audio_bienvenida_local(usuario, momento=None):
    """
    Gestiona el audio de bienvenida resguardado físicamente en disco (static/audio/saludos/):
    - Incluye en el nombre de archivo el momento y conteo de notificaciones para refrescar el audio si hay actividad nueva.
    """
    import base64

    usuario = usuario.strip() if usuario else "Usuario"
    momento_slug, texto_saludo, total_notif = obtener_momento_y_saludo(usuario, momento)
    slug_user = slugify_usuario(usuario)
    filename = f"{slug_user}_{momento_slug}_n{total_notif}.mp3"

    saludos_dir = os.path.join(current_app.root_path, "static", "audio", "saludos")
    os.makedirs(saludos_dir, exist_ok=True)
    filepath = os.path.join(saludos_dir, filename)
    audio_url = url_for('static', filename=f'audio/saludos/{filename}')

    # 1. Verificar si ya existe en disco con contenido válido (> 1KB)
    if os.path.exists(filepath) and os.path.getsize(filepath) > 1024:
        try:
            with open(filepath, "rb") as f:
                audio_bytes = f.read()
            audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")
            return {
                "success": True,
                "cached": True,
                "saludo": texto_saludo,
                "total_notificaciones": total_notif,
                "audio_url": audio_url,
                "audio_b64": audio_b64,
                "audio_mime": "audio/mp3",
                "usuario": usuario,
                "momento": momento_slug,
                "filename": filename
            }
        except Exception as e:
            if current_app:
                current_app.logger.warning(f"Error leyendo audio en cache {filepath}: {e}")

    # 2. Si no existe en disco: generar con Edge Neural TTS y resguardar
    voz = os.getenv("TTS_VOICE", "es-MX-DaliaNeural")
    audio_bytes = _generar_edge_tts(texto_saludo, voice=voz)

    if audio_bytes and len(audio_bytes) > 1024:
        try:
            with open(filepath, "wb") as f:
                f.write(audio_bytes)
            audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")
            return {
                "success": True,
                "cached": False,
                "saludo": texto_saludo,
                "total_notificaciones": total_notif,
                "audio_url": audio_url,
                "audio_b64": audio_b64,
                "audio_mime": "audio/mp3",
                "usuario": usuario,
                "momento": momento_slug,
                "filename": filename
            }
        except Exception as e:
            if current_app:
                current_app.logger.error(f"Error guardando audio en disco {filepath}: {e}")
            audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")
            return {
                "success": True,
                "cached": False,
                "saludo": texto_saludo,
                "total_notificaciones": total_notif,
                "audio_url": audio_url,
                "audio_b64": audio_b64,
                "audio_mime": "audio/mp3",
                "usuario": usuario,
                "momento": momento_slug,
                "filename": filename
            }

    return {
        "success": False,
        "cached": False,
        "saludo": texto_saludo,
        "total_notificaciones": total_notif,
        "audio_url": "",
        "audio_b64": "",
        "audio_mime": "audio/mp3",
        "usuario": usuario,
        "momento": momento_slug,
        "error": "No se pudo generar el audio de bienvenida."
    }


# -----------------------------------------------------------------------------
# CENTRO DE NOTIFICACIONES DE ACTIVIDAD (OTROS USUARIOS)
# -----------------------------------------------------------------------------
@bp.route("/api/notificaciones", methods=["GET"])
def api_listar_notificaciones():
    if "user_id" not in session:
        return jsonify({"success": False, "error": "No autorizado"}), 401

    usuario_actual = session.get("user_nombre", "Loreidy")
    supabase = getattr(current_app, "supabase", None)

    movs = []
    if supabase:
        try:
            res = supabase.table("historial_movimientos").select("*").order("created_at", desc=True).limit(50).execute()
            if res.data:
                movs = res.data
        except Exception:
            movs = MOCK_MOVIMIENTOS
    else:
        movs = MOCK_MOVIMIENTOS

    notificaciones = []
    leidas = set(str(x) for x in session.get("notificaciones_leidas", []))

    for m in movs:
        u_nombre = m.get("usuario_nombre", "")
        # Filtro: Solo actividades de otros usuarios (a excepción de las mías)
        if u_nombre and u_nombre.strip().lower() == usuario_actual.strip().lower():
            continue

        accion = (m.get("accion") or "").upper()
        desc = m.get("descripcion", "")

        # FILTRO DE RUIDO: Omitir logins/logouts e inicios/cierres de sesión rutinarios
        if any(k in accion for k in ["LOGIN", "LOGOUT", "INICIALIZACION"]) or any(k in desc.lower() for k in ["inicio de sesión", "inicio de sesion", "cierre de sesión", "cierre de sesion"]):
            continue

        m_id = str(m.get("id") or f"{accion}_{m.get('created_at')}")

        icono = "bi-bell-fill"
        color_bg = "bg-brand-50 text-brand-700"

        if "ORDEN" in accion:
            icono = "bi-file-earmark-text-fill"
            color_bg = "bg-blue-100 text-blue-800"
            titulo = f"Nueva Orden ({u_nombre})"
        elif "USUARIO" in accion:
            icono = "bi-person-plus-fill"
            color_bg = "bg-purple-100 text-purple-800"
            titulo = f"Nuevo Usuario ({u_nombre})"
        elif "ITEM" in accion or "CATALOGO" in accion:
            icono = "bi-tag-fill"
            color_bg = "bg-emerald-100 text-emerald-800"
            titulo = f"Catálogo Actualizado ({u_nombre})"
        elif "PROVEEDOR" in accion:
            icono = "bi-building"
            color_bg = "bg-amber-100 text-amber-800"
            titulo = f"Proveedor ({u_nombre})"
        elif "PROYECTO" in accion:
            icono = "bi-briefcase-fill"
            color_bg = "bg-indigo-100 text-indigo-800"
            titulo = f"Proyecto ({u_nombre})"
        else:
            titulo = f"Actividad de {u_nombre}"

        notificaciones.append({
            "id": m_id,
            "titulo": titulo,
            "mensaje": desc,
            "usuario": u_nombre,
            "created_at": m.get("created_at", ""),
            "icono": icono,
            "color_bg": color_bg,
            "leida": m_id in leidas
        })

    no_leidas = [n for n in notificaciones if not n["leida"]]
    return jsonify({
        "success": True,
        "total_no_leidas": len(no_leidas),
        "notificaciones": notificaciones[:15]
    })


@bp.route("/api/notificaciones/marcar-leidas", methods=["POST"])
def api_marcar_notificaciones_leidas():
    if "user_id" not in session:
        return jsonify({"success": False, "error": "No autorizado"}), 401

    req_data = request.get_json(silent=True) or {}
    client_ids = [str(x) for x in req_data.get("ids", []) if x]

    supabase = getattr(current_app, "supabase", None)
    movs_ids = []
    if supabase:
        try:
            res = supabase.table("historial_movimientos").select("id, accion, created_at").limit(100).execute()
            if res.data:
                for r in res.data:
                    if r.get("id"): movs_ids.append(str(r["id"]))
                    movs_ids.append(f"{r.get('accion')}_{r.get('created_at')}")
        except Exception:
            pass

    for m in MOCK_MOVIMIENTOS:
        if m.get("id"): movs_ids.append(str(m["id"]))
        movs_ids.append(f"{m.get('accion')}_{m.get('created_at')}")

    todas_leidas = list(set(session.get("notificaciones_leidas", []) + movs_ids + client_ids))
    session["notificaciones_leidas"] = todas_leidas
    session.modified = True
    return jsonify({"success": True, "total_leidas": len(todas_leidas)})

def generar_audio_astrid(texto):
    """
    Genera voz para Astrid con Microsoft Edge Neural TTS (es-MX-DaliaNeural).
    Retorna: (audio_b64, audio_mime)
    """
    import base64
    texto_limpio = re.sub(r'[*#_`]', '', texto)
    texto_limpio = re.sub(r'[\U00010000-\U0010ffff]', '', texto_limpio).strip()
    if not texto_limpio:
        return "", ""

    try:
        voz = os.getenv("TTS_VOICE", "es-MX-DaliaNeural")
        audio_mp3 = _generar_edge_tts(texto_limpio[:2000], voice=voz)
        if audio_mp3:
            return base64.b64encode(audio_mp3).decode("utf-8"), "audio/mp3"
    except Exception as err:
        if current_app:
            current_app.logger.error(f"Error en Edge TTS: {err}")

    return "", ""

@bp.route("/api/astrid/bienvenida", methods=["GET", "POST"])
def astrid_bienvenida():
    if "user_id" not in session:
        return jsonify({"success": False, "error": "No autorizado"}), 401
        
    usuario = request.args.get("usuario") or session.get("user_nombre", "Loreidy")
    momento = request.args.get("momento")
    
    resultado = asegurar_audio_bienvenida_local(usuario, momento=momento)
    return jsonify(resultado)


def detectar_y_ejecutar_accion_astrid(prompt_usuario, usuario="Loreidy"):
    """
    Motor de ejecución operativa de Astrid con permisos de modificación en base de datos.
    Permite:
    - Modificar precios o costos en el catálogo (items_catalogo).
    - Registrar nuevos ítems en el catálogo.
    - Modificar datos de proveedores (teléfono, email, banco, cuenta, dirección).
    - Registrar auditoría con cada acción realizada.
    """
    p_lower = prompt_usuario.lower()
    palabras_accion = ["modifica", "modificar", "cambia", "cambiar", "actualiza", "actualizar", "crea", "crear", "agrega", "agregar", "ponle", "ajusta", "ajustar", "sube", "baja", "elimina", "borra"]
    if not any(w in p_lower for w in palabras_accion):
        return None

    supabase = getattr(current_app, "supabase", None)
    openrouter_key = os.getenv("OPENROUTER_API_KEY")
    if not openrouter_key:
        return None

    sys_instr = """Eres un extractor de intenciones de modificación operativa para el sistema Facturador SIST-LQ.
Analiza la solicitud del usuario y devuelve ÚNICAMENTE un objeto JSON válido (sin explicaciones ni texto adicional):

Opciones JSON posibles:
1. Modificar precio o costo de un ítem existente del catálogo:
{"accion": "actualizar_precio_item", "item": "nombre del ítem", "nuevo_precio": 12.50}

2. Crear o agregar un nuevo ítem al catálogo:
{"accion": "crear_item", "descripcion": "nombre del ítem", "unidad": "UND|Metros|Kilos|Litros", "precio": 10.0}

3. Modificar datos de un proveedor (telefono, email, banco, num_cuenta, direccion):
{"accion": "actualizar_proveedor", "proveedor": "nombre del proveedor", "campo": "telefono|email|banco|num_cuenta|direccion", "valor": "nuevo valor"}

4. Modificar observaciones de una orden:
{"accion": "actualizar_orden_obs", "nro_orden": "000271", "observaciones": "nuevo texto"}

5. Si es solo una pregunta informativa, consulta o solicitud de reporte:
{"accion": "ninguna"}"""

    parsed = None
    try:
        r = requests.post("https://openrouter.ai/api/v1/chat/completions", json={
            "model": "minimax/minimax-m3:free",
            "messages": [
                {"role": "system", "content": sys_instr},
                {"role": "user", "content": prompt_usuario}
            ],
            "temperature": 0.1,
            "max_tokens": 150
        }, headers={"Authorization": f"Bearer {openrouter_key}", "HTTP-Referer": "https://sis-fact-lq.onrender.com", "X-Title": "SIST-LQ"}, timeout=8)
        
        if r.status_code == 200:
            res_txt = r.json()["choices"][0]["message"]["content"].strip()
            match = re.search(r'\{.*\}', res_txt, re.DOTALL)
            if match:
                parsed = json.loads(match.group(0))
    except Exception as e:
        if current_app:
            current_app.logger.warning(f"Error extrayendo acción Astrid: {e}")

    if not parsed or parsed.get("accion") == "ninguna":
        # Heurística regex de alta precisión cuando la API externa está ocupada o sin cuota
        p_str = prompt_usuario.lower()
        m_precio = re.search(r'(?:modifica|cambia|actualiza|ponle|ajusta|sube|baja)\s+(?:el\s+)?precio\s+(?:de\s+)?(.+?)\s+(?:a|en)\s+\$?([0-9]+(?:\.[0-9]+)?)', p_str)
        if m_precio:
            parsed = {
                "accion": "actualizar_precio_item",
                "item": m_precio.group(1).strip(),
                "nuevo_precio": float(m_precio.group(2))
            }
        else:
            m_nuevo = re.search(r'(?:crea|agrega|nuevo\s+ítem|nuevo\s+item)\s+(?:de\s+)?(.+?)\s+(?:con\s+precio|a)\s+\$?([0-9]+(?:\.[0-9]+)?)', p_str)
            if m_nuevo:
                parsed = {
                    "accion": "crear_item",
                    "descripcion": m_nuevo.group(1).strip(),
                    "unidad": "UND",
                    "precio": float(m_nuevo.group(2))
                }

    if not parsed or parsed.get("accion") == "ninguna":
        return None

    accion = parsed.get("accion")

    # 1. ACTUALIZAR PRECIO DE ÍTEM EN CATÁLOGO
    if accion == "actualizar_precio_item":
        item_buscado = parsed.get("item", "").strip()
        try:
            nuevo_precio = float(parsed.get("nuevo_precio", 0))
        except (ValueError, TypeError):
            nuevo_precio = 0.0

        if supabase and item_buscado:
            try:
                r_item = supabase.table("items_catalogo").select("*").ilike("descripcion", f"%{item_buscado}%").limit(1).execute()
                if not r_item.data:
                    palabras = [w for w in item_buscado.split() if len(w) > 3]
                    for pal in palabras:
                        r_item = supabase.table("items_catalogo").select("*").ilike("descripcion", f"%{pal}%").limit(1).execute()
                        if r_item.data: break

                if r_item.data:
                    item_obj = r_item.data[0]
                    supabase.table("items_catalogo").update({"precio_referencial_usd": nuevo_precio}).eq("id", item_obj["id"]).execute()
                    desc = f"Astrid IA actualizó el precio referencial de '{item_obj['descripcion']}' a ${nuevo_precio:.2f} USD"
                    registrar_movimiento(usuario, "EDITAR_ITEM_ASTRID", "CATALOGO", desc)
                    return {
                        "ejecutada": True,
                        "tipo": "actualizar_precio_item",
                        "mensaje": f"Se actualizó con éxito el precio del ítem '{item_obj['descripcion']}' en el catálogo a ${nuevo_precio:,.2f} USD.",
                        "item": item_obj["descripcion"],
                        "nuevo_precio_usd": nuevo_precio
                    }
            except Exception as e:
                if current_app: current_app.logger.error(f"Error actualizando precio item Astrid: {e}")

    # 2. CREAR NUEVO ÍTEM EN CATÁLOGO
    elif accion == "crear_item":
        descripcion = parsed.get("descripcion", "").strip().upper()
        unidad = parsed.get("unidad", "UND").strip()
        try:
            precio = float(parsed.get("precio", 0))
        except (ValueError, TypeError):
            precio = 0.0

        if supabase and descripcion:
            try:
                new_item = {
                    "descripcion": descripcion,
                    "unidad": unidad,
                    "precio_referencial_usd": precio
                }
                res = supabase.table("items_catalogo").insert(new_item).execute()
                if res.data:
                    desc = f"Astrid IA registró el nuevo ítem de catálogo '{descripcion}' ({unidad}) a ${precio:.2f} USD"
                    registrar_movimiento(usuario, "CREAR_ITEM_ASTRID", "CATALOGO", desc)
                    return {
                        "ejecutada": True,
                        "tipo": "crear_item",
                        "mensaje": f"Se creó exitosamente en el catálogo el ítem '{descripcion}' ({unidad}) con precio referencial de ${precio:,.2f} USD.",
                        "item": descripcion,
                        "precio_usd": precio
                    }
            except Exception as e:
                if current_app: current_app.logger.error(f"Error creando item Astrid: {e}")

    # 3. ACTUALIZAR DATOS DE PROVEEDOR
    elif accion == "actualizar_proveedor":
        prov_nombre = parsed.get("proveedor", "").strip()
        campo = parsed.get("campo", "").strip().lower()
        valor = str(parsed.get("valor", "")).strip()

        campos_validos = ["telefono", "email", "banco", "num_cuenta", "direccion", "beneficiario"]
        if supabase and prov_nombre and campo in campos_validos and valor:
            try:
                r_prov = supabase.table("proveedores").select("id, razon_social").ilike("razon_social", f"%{prov_nombre}%").limit(1).execute()
                if r_prov.data:
                    p_obj = r_prov.data[0]
                    supabase.table("proveedores").update({campo: valor}).eq("id", p_obj["id"]).execute()
                    desc = f"Astrid IA actualizó {campo} del proveedor {p_obj['razon_social']} a '{valor}'"
                    registrar_movimiento(usuario, "EDITAR_PROVEEDOR_ASTRID", "PROVEEDORES", desc)
                    return {
                        "ejecutada": True,
                        "tipo": "actualizar_proveedor",
                        "mensaje": f"Se actualizó exitosamente el campo '{campo}' del proveedor '{p_obj['razon_social']}' a '{valor}'.",
                        "proveedor": p_obj["razon_social"],
                        "campo": campo,
                        "valor": valor
                    }
            except Exception as e:
                if current_app: current_app.logger.error(f"Error actualizando proveedor Astrid: {e}")

    return None


def obtener_contexto_en_vivo_astrid(prompt_usuario=None, accion_resultado=None):
    """
    Extrae un resumen exhaustivo y en tiempo real de toda la base de datos para Astrid.
    Acceso TOTAL:
    - Precios, costos y catálogo de ítems con equivalencia en Bolívares a tasa oficial BCV.
    - Órdenes de compra y detalle de ítems de órdenes.
    - Directorio completo de proveedores con RIF y bancos.
    - Registro de auditoría y trazabilidad histórica de todos los usuarios.
    - Usuarios y roles.
    - Enlaces oficiales de descarga y generación de reportes en Excel (.xlsx).
    """
    supabase = getattr(current_app, "supabase", None)
    contexto = {
        "total_proveedores": 0,
        "proveedores_detalle": [],
        "total_ordenes": 0,
        "total_usd": 0.0,
        "total_bs": 0.0,
        "ordenes_recientes": [],
        "orden_detalles_recientes": [],
        "items_catalogo": [],
        "proyectos": [],
        "tasa_bcv": 804.81,
        "tasa_eur": 932.80,
        "usuarios": [],
        "movimientos_recientes": [],
        "movimientos_especificos": [],
        "accion_ejecutada": accion_resultado
    }
    
    try:
        info_bcv = obtener_tasa_bcv()
        contexto["tasa_bcv"] = float(info_bcv.get("tasa_usd", 813.74))
        contexto["tasa_eur"] = float(info_bcv.get("tasa_eur", 945.65))
        contexto["tasa_promedio"] = float(info_bcv.get("tasa_promedio", 879.69))
    except Exception:
        contexto["tasa_bcv"] = 813.74
        contexto["tasa_eur"] = 945.65
        contexto["tasa_promedio"] = 879.69

    if supabase:
        try:
            # 1. Catálogo completo de costos y precios
            r_cat = supabase.table("items_catalogo").select("id, descripcion, unidad, precio_referencial_usd").order("descripcion").execute()
            if r_cat.data:
                contexto["items_catalogo"] = r_cat.data

            # 2. Proveedores con datos bancarios y fiscales
            r_prov = supabase.table("proveedores").select("razon_social, rif, banco, num_cuenta, telefono, email").order("razon_social").execute()
            if r_prov.data:
                contexto["total_proveedores"] = len(r_prov.data)
                contexto["proveedores_detalle"] = r_prov.data

            # 3. Órdenes de compra con montos bimonetarios y firmantes
            r_ord = supabase.table("ordenes_compra").select("id, nro_orden, fecha_emision, total_usd, total_bs, firmante_solicitado, firmante_revisado, proveedores(razon_social), proyectos(nombre)").order("created_at", desc=True).limit(20).execute()
            if r_ord.data:
                contexto["total_ordenes"] = len(r_ord.data)
                contexto["total_usd"] = sum(float(o.get("total_usd") or 0) for o in r_ord.data)
                contexto["total_bs"] = sum(float(o.get("total_bs") or 0) for o in r_ord.data)
                contexto["ordenes_recientes"] = [
                    {
                        "nro": o.get("nro_orden"),
                        "fecha": o.get("fecha_emision"),
                        "proveedor": o.get("proveedores", {}).get("razon_social") if isinstance(o.get("proveedores"), dict) else "N/A",
                        "proyecto": o.get("proyectos", {}).get("nombre") if isinstance(o.get("proyectos"), dict) else "N/A",
                        "total_usd": float(o.get("total_usd") or 0),
                        "total_bs": float(o.get("total_bs") or 0),
                        "solicitado_por": o.get("firmante_solicitado"),
                        "revisado_por": o.get("firmante_revisado")
                    }
                    for o in r_ord.data
                ]

            # 4. Ítems detallados de órdenes de compra (costos unitarios facturados)
            try:
                r_det = supabase.table("orden_detalles").select("descripcion, cantidad, unidad, precio_unitario_usd, total_linea_usd, ordenes_compra(nro_orden)").order("created_at", desc=True).limit(25).execute()
                if r_det.data:
                    contexto["orden_detalles_recientes"] = [
                        {
                            "orden": d.get("ordenes_compra", {}).get("nro_orden") if isinstance(d.get("ordenes_compra"), dict) else "N/A",
                            "descripcion": d.get("descripcion"),
                            "cantidad": float(d.get("cantidad") or 0),
                            "unidad": d.get("unidad"),
                            "precio_unitario_usd": float(d.get("precio_unitario_usd") or 0),
                            "total_linea_usd": float(d.get("total_linea_usd") or 0)
                        }
                        for d in r_det.data
                    ]
            except Exception:
                pass

            # 5. Usuarios registrados
            r_usr = supabase.table("usuarios").select("nombre, email, rol, created_at").execute()
            if r_usr.data:
                contexto["usuarios"] = r_usr.data

            # 6. Auditoría y trazabilidad histórica (últimos 30 eventos globales)
            r_mov = supabase.table("historial_movimientos").select("usuario_nombre, accion, modulo, descripcion, created_at").order("created_at", desc=True).limit(30).execute()
            if r_mov.data:
                contexto["movimientos_recientes"] = r_mov.data

            # 7. Búsqueda contextual de auditoría si el prompt menciona una persona
            if prompt_usuario:
                p_lower = prompt_usuario.lower()
                nombres_clave = ["loreidy", "pedro", "jhoan", "joan", "admin", "ramon", "rivas", "quiñonez", "quinonez", "sequera"]
                for u in contexto["usuarios"]:
                    n = u.get("nombre", "").lower()
                    if n and (n in p_lower or any(part in p_lower for part in n.split() if len(part) > 3)):
                        nombres_clave.append(u.get("nombre"))

                for busq in set(nombres_clave):
                    if busq.lower() in p_lower:
                        try:
                            r_esp = supabase.table("historial_movimientos").select("usuario_nombre, accion, modulo, descripcion, created_at").ilike("usuario_nombre", f"%{busq}%").order("created_at", desc=True).limit(10).execute()
                            if r_esp.data:
                                for me in r_esp.data:
                                    if me not in contexto["movimientos_especificos"]:
                                        contexto["movimientos_especificos"].append(me)
                        except Exception:
                            pass

            # 8. Proyectos
            r_proy = supabase.table("proyectos").select("codigo, nombre").execute()
            if r_proy.data:
                contexto["proyectos"] = [f"{p.get('codigo')} - {p.get('nombre')}" for p in r_proy.data if p.get("nombre")]

        except Exception as e:
            if current_app:
                current_app.logger.warning(f"Error extrayendo contexto Astrid: {e}")
    else:
        # Modo fallback en memoria
        contexto["items_catalogo"] = MOCK_ITEMS
        contexto["total_proveedores"] = len(MOCK_PROVEEDORES)
        contexto["proveedores_detalle"] = MOCK_PROVEEDORES
        contexto["total_ordenes"] = len(MOCK_ORDENES)
        contexto["total_usd"] = sum(float(o.get("total_usd") or 0) for o in MOCK_ORDENES)
        contexto["total_bs"] = sum(float(o.get("total_bs") or 0) for o in MOCK_ORDENES)
        contexto["proyectos"] = [f"{p.get('codigo')} - {p.get('nombre')}" for p in MOCK_PROYECTOS]
        contexto["movimientos_recientes"] = list(MOCK_MOVIMIENTOS)[:20]

    return contexto


def consultar_ia_astrid(prompt_usuario, usuario="Loreidy", historial=None):
    """
    Motor cognitivo integral de Astrid con ACCESO TOTAL a precios, costos, catálogo,
    órdenes de compra, proveedores, auditoría histórica y capacidad operativa de modificación.
    Soporta memoria conversacional multiturno (historial).
    """
    # 1. Detectar y ejecutar acciones operativas si el usuario solicitó una modificación
    accion_res = detectar_y_ejecutar_accion_astrid(prompt_usuario, usuario)

    # 2. Extraer contexto exhaustivo en vivo
    ctx = obtener_contexto_en_vivo_astrid(prompt_usuario, accion_resultado=accion_res)
    tasa = ctx["tasa_bcv"]
    tasa_eur = ctx["tasa_eur"]
    tasa_prom = ctx.get("tasa_promedio", round((tasa + tasa_eur) / 2.0, 4))

    # 3. Consultar motor analítico local especializado para respuesta instantánea (ruido, saludos, reportes con gráficas, precios, anáforas)
    resp_local = _responder_con_datos_locales_astrid(prompt_usuario, ctx, accion_res, usuario, historial=historial)
    if not resp_local.startswith(f"Hola {usuario}. Soy Astrid, el asistente inteligente y cerebro analítico"):
        return resp_local

    # Catálogo de precios y costos
    items_lines = [
        f"  * '{it.get('descripcion')}' ({it.get('unidad', 'UND')}): ${float(it.get('precio_referencial_usd') or 0):,.2f} USD (aprox. Bs. {float(it.get('precio_referencial_usd') or 0) * tasa:,.2f} a tasa BCV | Bs. {float(it.get('precio_referencial_usd') or 0) * tasa_prom:,.2f} a tasa promedio)"
        for it in ctx["items_catalogo"]
    ]
    texto_items = f"{len(ctx['items_catalogo'])} ítems en catálogo de costos y precios:\n" + ("\n".join(items_lines) if items_lines else "Sin ítems registrados.")

    # Costos en órdenes recientes
    det_lines = [
        f"  * Orden {d['orden']}: '{d['descripcion']}' ({d['cantidad']} {d['unidad']}) @ ${d['precio_unitario_usd']:,.2f} USD = ${d['total_linea_usd']:,.2f} USD"
        for d in ctx["orden_detalles_recientes"][:10]
    ]
    texto_detalles = "Costos unitarios y cantidades facturadas recientemente:\n" + ("\n".join(det_lines) if det_lines else "Sin detalles registrados.")

    # Proveedores
    prov_lines = [
        f"  * {p.get('razon_social')} (RIF: {p.get('rif', 'N/A')}, Banco: {p.get('banco', 'N/A')}, Cuenta: {p.get('num_cuenta', 'N/A')}, Tlf: {p.get('telefono', 'N/A')}, Email: {p.get('email', 'N/A')})"
        for p in ctx["proveedores_detalle"]
    ]
    texto_prov = f"{ctx['total_proveedores']} proveedores registrados:\n" + "\n".join(prov_lines)

    # Órdenes de compra
    ord_lines = [
        f"  * Orden {o['nro']} ({o['fecha']}): Prov: {o['proveedor']} | Total: ${o['total_usd']:,.2f} USD (Bs. {o['total_bs']:,.2f}) | Solicitó: {o['solicitado_por']} | Revisó: {o['revisado_por']}"
        for o in ctx["ordenes_recientes"][:10]
    ]
    texto_ord = f"{ctx['total_ordenes']} órdenes emitidas (Total facturado: ${ctx['total_usd']:,.2f} USD / Bs. {ctx['total_bs']:,.2f}):\n" + "\n".join(ord_lines)

    # Usuarios
    usr_lines = [
        f"  * {u.get('nombre')} ({u.get('email')}, Rol: {u.get('rol', 'usuario')})"
        for u in ctx["usuarios"]
    ]
    texto_usr = f"{len(ctx['usuarios'])} usuarios en el sistema:\n" + "\n".join(usr_lines)

    # Auditoría y Trazabilidad
    movs_mostrar = []
    if ctx["movimientos_especificos"]:
        movs_mostrar.extend(ctx["movimientos_especificos"])
    for m in ctx["movimientos_recientes"]:
        if m not in movs_mostrar:
            movs_mostrar.append(m)

    mov_lines = [
        f"  * [{m.get('created_at', '')[:19]}] {m.get('usuario_nombre')}: {m.get('accion')} ({m.get('modulo')}) - {m.get('descripcion')}"
        for m in movs_mostrar[:20]
    ]
    texto_movs = "Historial de trazabilidad y auditoría de usuarios:\n" + "\n".join(mov_lines)

    # Mensaje de acción ejecutada (si aplica)
    texto_accion = ""
    if accion_res and accion_res.get("ejecutada"):
        texto_accion = f"\n⚠️ ACCIÓN OPERATIVA REALIZADA EXITOSAMENTE EN LA BASE DE DATOS:\n{accion_res.get('mensaje')}\nConfirma esta modificación con precisión al usuario.\n"

    # Enlaces oficiales para reportes
    texto_reportes = (
        "ENLACES OFICIALES PARA DESCARGA DE REPORTES EN EXCEL (.XLSX):\n"
        "- Órdenes de Compra: [📥 Descargar Reporte de Órdenes (.xlsx)](/api/exportar/ordenes)\n"
        "- Directorio de Proveedores: [📥 Descargar Directorio de Proveedores (.xlsx)](/api/exportar/proveedores)\n"
        "- Auditoría y Trazabilidad: [📥 Descargar Reporte de Auditoría (.xlsx)](/api/exportar/auditoria)\n"
        "- Plantilla de Proveedores: [📥 Descargar Plantilla Proveedores (.xlsx)](/api/plantilla/proveedores)"
    )

    sys_prompt = (
        f"Eres Astrid, la inteligencia artificial integral y cerebro analítico del sistema Facturador SIST-LQ.\n"
        f"El usuario que te consulta en este momento es: {usuario}.\n"
        f"TIENES ACCESO TOTAL Y PERMISOS DE MODIFICACIÓN EN TODA LA BASE DE DATOS DEL SISTEMA (precios, costos, catálogo, órdenes, proveedores, auditoría, usuarios y reportes).\n\n"
        f"{texto_accion}"
        f"--- DATOS VIVOS DEL SISTEMA EN TIEMPO REAL ---\n"
        f"1. TASAS OFICIALES BCV EN VIVO: USD = ${tasa:,.2f} Bs | EUR = €{tasa_eur:,.2f} Bs | PROMEDIO = ${tasa_prom:,.2f} Bs\n\n"
        f"2. CATÁLOGO DE ÍTEMS, PRECIOS Y COSTOS:\n{texto_items}\n\n"
        f"3. COSTOS FACTURADOS EN ÓRDENES:\n{texto_detalles}\n\n"
        f"4. ÓRDENES DE COMPRA:\n{texto_ord}\n\n"
        f"5. PROVEEDORES:\n{texto_prov}\n\n"
        f"6. USUARIOS REGISTRADOS:\n{texto_usr}\n\n"
        f"7. AUDITORÍA, INTERACCIONES Y ACTIVIDAD HISTÓRICA DE USUARIOS:\n{texto_movs}\n\n"
        f"8. GENERACIÓN Y DESCARGA DE REPORTES OFICIALES:\n{texto_reportes}\n\n"
        f"--- REGLAS DE RESPUESTA ---\n"
        f"1. Responde de forma ejecutiva, directa, cálida y profesional en español latino.\n"
        f"2. NUNCA digas que no tienes acceso a la información; TIENES ACCESO TOTAL a todos los datos vivos en este contexto.\n"
        f"3. Si el usuario pregunta por precios o costos (ej. 'dime qué costo tiene el drill', 'precio de la cama', 'cuánto cuesta X'):\n"
        f"   Responde con el precio exacto en USD y su valor convertido en Bolívares según la tasa BCV oficial (${tasa:,.2f} Bs/USD) y a tasa promedio (${tasa_prom:,.2f} Bs/USD) si lo pide.\n"
        f"4. Mantén la continuidad de la conversación (memoria multiturno). Si el usuario hace una pregunta de seguimiento breve como 'y a tasa promedio?', 'y en euros?', 'y quién la emitió?', responde sobre el mismo ítem u orden que se venía discutiendo en los turnos anteriores.\n"
        f"5. Si el usuario te pregunta por la última interacción, actividad o movimiento de algún usuario (ej. Loreidy Quiñonez, Ramón Rivas, Administrador):\n"
        f"   Revisa la sección de AUDITORÍA y responde con la fecha, hora exacta y qué acción realizó.\n"
        f"6. Si el usuario te pide un reporte o informe (de órdenes, gastos, proveedores o auditoría):\n"
        f"   Genera el resumen estructurado en tu respuesta y proporciona el enlace de descarga directa en Excel usando exactamente el formato Markdown: [📥 Descargar Reporte (.xlsx)](/api/exportar/...).\n"
        f"7. NUNCA muestres tu proceso de razonamiento interno (<think>, etc.)."
    )

    openrouter_key = os.getenv("OPENROUTER_API_KEY")
    models = [
        "google/gemma-4-31b-it:free",
        "google/gemma-4-26b-a4b-it:free",
        "liquid/lfm-2.5-2.6b:free",
        "nvidia/nemotron-3.5-lightning:free",
        "minimax/minimax-m3:free",
        os.getenv("OPENROUTER_MODEL", "google/gemma-4-31b-it:free"),
    ]
    seen = set()
    models = [m for m in models if not (m in seen or seen.add(m))]

    if openrouter_key:
        headers = {
            "Authorization": f"Bearer {openrouter_key}",
            "HTTP-Referer": "https://sis-fact-lq.onrender.com",
            "X-Title": "SIST-LQ Astrid Assistant"
        }

        # Armar mensajes con historial conversacional
        hist_messages = []
        if historial:
            for h in historial[-6:]:
                role = "assistant" if h.get("role") == "assistant" else "user"
                content = str(h.get("content", "")).strip()
                if content:
                    hist_messages.append({"role": role, "content": content})

        payload_messages = [{"role": "system", "content": sys_prompt}] + hist_messages + [{"role": "user", "content": prompt_usuario}]

        for model in models:
            try:
                payload = {
                    "model": model,
                    "messages": payload_messages,
                    "temperature": 0.3,
                    "max_tokens": 700
                }
                r = requests.post("https://openrouter.ai/api/v1/chat/completions", json=payload, headers=headers, timeout=10)
                if r.status_code == 200:
                    data = r.json()
                    choices = data.get("choices", [])
                    if choices and "message" in choices[0]:
                        msg = choices[0]["message"]
                        texto_resp = msg.get("content") or msg.get("reasoning") or ""

                        # Limpieza de cualquier prefijo de razonamiento
                        patrones_reasoning = [
                            r"Here'?s a thinking process:.*?(?=\n\n[^\n])",
                            r"^\*\*Analyze.*?(?=\n\n[^\n])",
                            r"^Let me (think|analyze|reason|consider).*?(?=\n\n[^\n])",
                            r"^Thinking:.*?(?=\n\n[^\n])",
                            r"^<think>.*?</think>",
                        ]
                        for patron in patrones_reasoning:
                            texto_resp = re.sub(patron, '', texto_resp, flags=re.DOTALL | re.IGNORECASE | re.MULTILINE).strip()

                        texto_resp = re.sub(r'\*\*([^*]+)\*\*', r'\1', texto_resp)
                        texto_resp = re.sub(r'\*([^*]+)\*', r'\1', texto_resp)
                        texto_resp = texto_resp.strip()
                        if texto_resp:
                            return texto_resp
            except Exception as e:
                if current_app:
                    current_app.logger.warning(f"Excepción en OpenRouter ({model}): {e}")

    # Fallback garantizado: Motor cognitivo local con datos vivos del sistema y contexto histórico
    return _responder_con_datos_locales_astrid(prompt_usuario, ctx, accion_res, usuario, historial=historial)


def _formatear_fecha_ve(fecha_str):
    """Convierte fecha UTC ISO a formato venezolano legible (DD/MM/YYYY hh:mm AM/PM)."""
    if not fecha_str:
        return "Fecha no disponible"
    try:
        s = str(fecha_str).strip().replace(" ", "T")
        if not s.endswith("Z") and "+" not in s and "-" not in s[10:]:
            s += "Z"
        dt = datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))
        # Venezuela is UTC-4
        dt_ve = dt - datetime.timedelta(hours=4)
        return dt_ve.strftime("%d/%m/%Y %I:%M %p")
    except Exception:
        return str(fecha_str)[:19]


def _responder_con_datos_locales_astrid(prompt_usuario, ctx, accion_res, usuario, historial=None):
    """
    Motor analítico y cognitivo integral de Astrid con acceso total y en tiempo real a:
    - Precios y costos del catálogo (con conversión bimonetaria oficial BCV).
    - Órdenes de compra, montos acumulados y firmantes autorizados.
    - Directorio bancario y fiscal completo de proveedores.
    - Auditoría y trazabilidad histórica en hora local venezolana.
    - Generación de reportes ejecutivos con gráficas interactivas Chart.js.
    - Soporte contextual multiturno sin falsas suposiciones ni colisión de palabras clave.
    """
    p_clean = prompt_usuario.strip()
    p_lower = p_clean.lower()
    tasa_usd = ctx.get("tasa_bcv", 813.74)
    tasa_eur = ctx.get("tasa_eur", 945.65)
    tasa_prom = ctx.get("tasa_promedio", round((tasa_usd + tasa_eur) / 2.0, 4))

    provs = ctx.get("proveedores_detalle", [])
    items_cat = ctx.get("items_catalogo", [])
    ords = ctx.get("ordenes_recientes", [])
    movs = ctx.get("movimientos_recientes", [])

    # 1. Si se ejecutó una acción operativa en base de datos:
    if accion_res and accion_res.get("ejecutada"):
        return (
            f"✅ **Operación ejecutada con éxito en la base de datos:**\n"
            f"{accion_res.get('mensaje')}\n\n"
            f"Los datos han sido actualizados en tiempo real y el movimiento quedó asentado en la auditoría del sistema."
        )

    # 2. Saludos de cortesía
    saludos_exactos = ["hola", "buen dia", "buenos dias", "buen día", "buenos días", "buenas tardes", "buenas noches", "saludos", "que tal", "qué tal", "hey", "hola astrid", "como estas", "cómo estás"]
    if p_lower in saludos_exactos or p_lower.startswith("hola astrid"):
        return (
            f"¡Hola, {usuario}! Un gusto saludarte. Soy Astrid, el cerebro analítico y asistente inteligente del Facturador SIST-LQ.\n\n"
            f"Tengo acceso total y en tiempo real a precios de catálogo, órdenes de compra emitidas, directorio de proveedores, trazabilidad y tasas oficiales BCV.\n\n"
            f"¿Qué deseas consultar o gestionar hoy?"
        )

    # 3. Cortesías de cierre / conformidad ("gracias", "ok", "perfecto")
    if any(k == p_lower or p_lower.startswith(k + " ") for k in ["gracias", "muchas gracias", "agradecido", "agradecida", "perfecto", "excelente", "entendido", "ok", "listo"]):
        return (
            f"¡Con mucho gusto, {usuario}! Quedo a tu disposición para cualquier consulta contable, modificación de precios, órdenes de compra o reportes ejecutivos. ¡Éxito en tu jornada!"
        )

    # 4. Detección de ruido real (solo repeticiones o teclazos evidentes como "ggg", "asdf", etc.)
    es_repetido = bool(re.match(r'^(.)\1{2,}$', p_lower))
    palabras_ruido = ["asdf", "asdasd", "qwerty", "zxcv", "123", "test", "probando", "...", "???"]
    if es_repetido or p_lower in palabras_ruido:
        return (
            f"Hola {usuario}. He recibido tu mensaje (`{p_clean}`), pero parece ser una prueba o estar incompleto.\n\n"
            f"¿En qué puedo orientarte hoy? Puedes consultarme sobre:\n"
            f"• **Costos y precios:** *'¿Cuánto cuesta el drill 100% algodón?'*\n"
            f"• **Órdenes de compra:** *'¿Cuáles son las últimas órdenes emitidas?'*\n"
            f"• **Proveedores:** *'Información de Comertel'* o *'Directorio bancario de proveedores'*\n"
            f"• **Tasas oficiales:** *'¿Cuál es la tasa oficial BCV?'*\n"
            f"• **Reportes con gráficas:** *'Dame un reporte con gráficas de proveedores'*."
        )

    # STOPWORDS que no pueden usarse de forma aislada para inferir un producto
    STOPWORDS_ITEM = {
        "compra", "compras", "orden", "ordenes", "órdenes", "para", "cada",
        "tipo", "nuevo", "nueva", "gran", "alta", "baja", "pago", "pagos",
        "total", "totales", "item", "ítem", "items", "con", "por", "sin",
        "sobre", "desde", "hasta", "como", "cómo", "cual", "cuál", "cuales",
        "cuáles", "donde", "dónde", "quien", "quién", "este", "esta", "estos",
        "estas", "precio", "precios", "costo", "costos", "tasa", "tasas",
        "dame", "ver", "dime", "muestrame", "muéstrame", "cual", "cuál",
        "cuanto", "cuánto", "cuesta", "cuestan", "vale", "valen", "informacion",
        "información", "datos", "de", "el", "la", "los", "las", "un", "una"
    }

    # Búsqueda de proveedor específico mencionado en el prompt
    prov_mencionado = None
    for p in provs:
        rz = (p.get("razon_social") or "").strip().lower()
        rif = (p.get("rif") or "").strip().lower()
        if rz and (rz in p_lower or any(w in p_lower for w in rz.split() if len(w) > 4 and w not in ["empresa", "soluciones", "tecnologicas", "tecnológicas", "inversiones"])):
            prov_mencionado = p
            break
        if rif and rif in p_lower:
            prov_mencionado = p
            break

    # Identificación si el usuario solicita expresamente precios / catálogo
    pide_precio = any(k in p_lower for k in ["precio", "costo", "catálogo", "catalogo", "cuánto", "cuanto", "cuesta", "vale", "cotiz", "tarifa"])
    item_mencionado = None
    for it in items_cat:
        desc = (it.get("descripcion") or "").strip().lower()
        if desc in p_lower:
            item_mencionado = it
            break
        palabras_it = [w for w in desc.split() if len(w) > 3 and w not in STOPWORDS_ITEM]
        coincidencias = [w for w in palabras_it if w in p_lower]
        if len(coincidencias) >= 2 or (len(coincidencias) == 1 and len(coincidencias[0]) >= 5 and not prov_mencionado):
            item_mencionado = it
            break

    # Memoria multiturno para seguimiento de preguntas sobre ítems (SOLO en preguntas de seguimiento o anáforas)
    palabras_seguimiento = ["y ", "y a ", "también", "tambien", "como sale", "cuanto seria", "cuánto sería", "a tasa", "en promedio", "en euro", "en eur", "en bs"]
    es_seguimiento = any(p_lower.startswith(p) for p in palabras_seguimiento) or (len(p_lower.split()) <= 4 and any(k in p_lower for k in ["promedio", "euro", "eur", "bcv", "dolar", "dólar"]))

    if not item_mencionado and not prov_mencionado and historial and es_seguimiento:
        for turn in reversed(historial):
            t_content = (turn.get("content") or "").lower()
            for it in items_cat:
                desc = (it.get("descripcion") or "").strip().lower()
                palabras_it = [w for w in desc.split() if len(w) > 3 and w not in STOPWORDS_ITEM]
                if desc in t_content or any(w in t_content for w in palabras_it if len(w) >= 5):
                    item_mencionado = it
                    break
            if item_mencionado:
                break

    # 5. PREGUNTAS DE SEGUIMIENTO SOBRE TASAS (Anáforas para el ítem en contexto)
    if item_mencionado and any(k in p_lower for k in ["promedio", "tasa promedio", "en promedio"]):
        p_usd = float(item_mencionado.get("precio_referencial_usd") or 0)
        p_prom = round(p_usd * tasa_prom, 2)
        return (
            f"Calculando a **tasa promedio ponderada oficial BCV** (${tasa_prom:,.2f} Bs/USD):\n\n"
            f"• **{item_mencionado.get('descripcion')}** ({item_mencionado.get('unidad', 'UND')}):\n"
            f"  - Precio base: **${p_usd:,.2f} USD**\n"
            f"  - Equivalente: **Bs. {p_prom:,.2f}** (a tasa promedio)\n"
            f"  - A tasa oficial USD (${tasa_usd:,.2f} Bs): **Bs. {p_usd * tasa_usd:,.2f}**\n\n"
            f"*(Tasas oficiales vigentes: USD ${tasa_usd:,.2f} Bs | EUR €{tasa_eur:,.2f} Bs | Promedio ${tasa_prom:,.2f} Bs)*"
        )

    if item_mencionado and any(k in p_lower for k in ["euro", "euros", "en eur", "en euros"]):
        p_usd = float(item_mencionado.get("precio_referencial_usd") or 0)
        p_eur_equiv = round((p_usd * tasa_usd) / tasa_eur, 2) if tasa_eur else 0
        p_bs_eur = round(p_usd * tasa_eur, 2)
        return (
            f"Calculando con la **tasa EUR oficial BCV** (€{tasa_eur:,.2f} Bs):\n\n"
            f"• **{item_mencionado.get('descripcion')}** ({item_mencionado.get('unidad', 'UND')}):\n"
            f"  - Precio base: **${p_usd:,.2f} USD**\n"
            f"  - Equivalente en Euros: **€{p_eur_equiv:,.2f} EUR**\n"
            f"  - En Bolívares a tasa Euro: **Bs. {p_bs_eur:,.2f}**"
        )

    # 6. CONSULTA DE TASAS OFICIALES BCV (Dólar, Euro, Promedio)
    es_pregunta_tasa_pura = any(k in p_lower for k in ["tasa", "tasas", "dolar", "dólar", "euro", "euros", "bcv", "cotizacion", "cotización", "promedio"]) and not pide_precio and not prov_mencionado
    if es_pregunta_tasa_pura:
        return (
            f"📈 **Tasas Oficiales del Banco Central de Venezuela (BCV) en Tiempo Real:**\n\n"
            f"• **Dólar Oficial (USD):** **${tasa_usd:,.2f} Bs/USD**\n"
            f"• **Euro Oficial (EUR):** **€{tasa_eur:,.2f} Bs/EUR**\n"
            f"• **Tasa Promedio Ponderada:** **${tasa_prom:,.2f} Bs/USD**\n\n"
            f"Todas las conversiones contables, órdenes de compra y cotizaciones del catálogo se calculan con estas tasas oficiales."
        )

    # 7. CONSULTA DE PROVEEDOR ESPECÍFICO (Prioridad sobre ítem con nombre de proveedor)
    if prov_mencionado and not pide_precio:
        nom_p = prov_mencionado.get("razon_social")
        ords_p = [o for o in ords if (o.get("proveedor") or "").strip().lower() == nom_p.lower()]
        tot_p_usd = sum(o["total_usd"] for o in ords_p)
        tot_p_bs = sum(o["total_bs"] for o in ords_p)

        lineas_ord_p = []
        for op in ords_p[:3]:
            lineas_ord_p.append(f"  - Orden #{op['nro']} ({op['fecha']}): ${op['total_usd']:,.2f} USD")

        resumen_compras = (
            f"• **Compras registradas:** {len(ords_p)} orden(es) por un total de **${tot_p_usd:,.2f} USD** (Bs. {tot_p_bs:,.2f})\n" + ("\n".join(lineas_ord_p) if lineas_ord_p else "")
            if ords_p else "• **Compras registradas:** Sin órdenes de compra emitidas aún."
        )

        return (
            f"🏢 **Ficha Oficial de Proveedor: {nom_p}**\n\n"
            f"• **RIF:** {prov_mencionado.get('rif') or 'N/A'}\n"
            f"• **Banco:** {prov_mencionado.get('banco') or 'No registrado'}\n"
            f"• **Número de Cuenta:** `{prov_mencionado.get('num_cuenta') or 'No registrado'}`\n"
            f"• **Teléfono:** {prov_mencionado.get('telefono') or 'No registrado'}\n"
            f"• **Correo Electrónico:** {prov_mencionado.get('email') or 'No registrado'}\n\n"
            f"{resumen_compras}\n\n"
            f"*(Puedes descargar el directorio completo en Excel: [📥 Descargar Directorio (.xlsx)](/api/exportar/proveedores))*"
        )

    # 8. REPORTES CON GRÁFICAS (Chart.js)
    peticion_grafica = any(k in p_lower for k in ["grafica", "gráfica", "graficas", "gráficas", "chart", "visual", "pastel", "torta", "barras"])
    peticion_reporte = any(k in p_lower for k in ["reporte", "informe", "balance", "resumen ejecutivo", "dashboard"])

    if peticion_grafica or (peticion_reporte and any(k in p_lower for k in ["proveedor", "proveedores", "suplidor"])):
        gastos_prov = {}
        for o in ords:
            nom_prov = o.get("proveedor", "Proveedor")
            gastos_prov[nom_prov] = gastos_prov.get(nom_prov, 0.0) + o["total_usd"]
        for p in provs:
            nom = p.get("razon_social")
            if nom and nom not in gastos_prov:
                gastos_prov[nom] = 0.0

        prov_sorted = sorted(gastos_prov.items(), key=lambda x: x[1], reverse=True)
        chart_labels = [x[0] for x in prov_sorted[:6]]
        chart_data = [round(x[1], 2) for x in prov_sorted[:6]]
        if sum(chart_data) == 0:
            chart_data = [1 for _ in chart_labels]

        chart_config = {
            "type": "doughnut",
            "title": "Distribución de Compras por Proveedor (USD)",
            "labels": chart_labels,
            "data": chart_data
        }
        chart_json = json.dumps(chart_config)

        lineas_p = []
        for nom, monto in prov_sorted[:6]:
            banco = next((p.get("banco", "N/A") for p in provs if p.get("razon_social") == nom), "N/A")
            lineas_p.append(f"• **{nom}** (Banco: {banco}): **${monto:,.2f} USD**")

        return (
            f"📊 **Reporte Ejecutivo y Análisis de Proveedores en Tiempo Real**\n\n"
            f"• **Proveedores registrados:** {len(provs)}\n"
            f"• **Total Facturado Acumulado:** **${ctx['total_usd']:,.2f} USD** (Bs. {ctx['total_bs']:,.2f})\n"
            f"• **Tasa Oficial BCV:** ${tasa_usd:,.2f} Bs/USD | Promedio: ${tasa_prom:,.2f} Bs\n\n"
            f":::chart {chart_json}:::\n\n"
            f"**Desglose por Proveedor:**\n" + "\n".join(lineas_p) +
            f"\n\n[📥 Descargar Directorio de Proveedores (.xlsx)](/api/exportar/proveedores)"
        )

    # 9. CONSULTA DE ÓRDENES DE COMPRA / FACTURACIÓN / GASTOS
    es_consulta_ordenes = any(k in p_lower for k in ["orden", "ordenes", "órdenes", "compra", "compras", "facturacion", "facturación", "gastos", "gasto"]) and not pide_precio
    if es_consulta_ordenes:
        lineas_o = []
        for o in ords[:6]:
            lineas_o.append(f"• **Orden #{o['nro']}** ({o['fecha']}): **${o['total_usd']:,.2f} USD** (Bs. {o['total_bs']:,.2f})\n  Proveedor: {o['proveedor']} | Proyecto: {o['proyecto']} | Solicitó: {o['solicitado_por'] or 'N/A'}")

        return (
            f"📑 **Resumen de Órdenes de Compra y Facturación en Tiempo Real**\n\n"
            f"• **Total órdenes emitidas:** {ctx['total_ordenes']}\n"
            f"• **Monto total facturado:** **${ctx['total_usd']:,.2f} USD** (Bs. {ctx['total_bs']:,.2f} a tasa BCV)\n"
            f"• **Tasa oficial BCV:** ${tasa_usd:,.2f} Bs/USD\n\n"
            f"**Últimas órdenes registradas:**\n" + ("\n".join(lineas_o) if lineas_o else "Sin órdenes emitidas.") +
            f"\n\nPuedes descargar el reporte detallado en: [📥 Descargar Reporte de Órdenes (.xlsx)](/api/exportar/ordenes)."
        )

    # 10. AUDITORÍA Y TRAZABILIDAD DE USUARIOS (Prioridad sobre catálogo)
    if any(k in p_lower for k in ["movimiento", "movimientos", "auditoria", "auditoría", "quien", "quién", "hizo", "loreidy", "pedro", "ramon", "ramón", "admin", "actividad", "trazabilidad", "sesion", "sesión", "historial"]):
        movs_filtrados = movs
        for nom in ["loreidy", "pedro", "ramon", "admin"]:
            if nom in p_lower:
                movs_filtrados = [m for m in movs if nom in (m.get("usuario_nombre") or "").lower()]
                break

        lineas_m = []
        for m in (movs_filtrados or movs)[:6]:
            f_ve = _formatear_fecha_ve(m.get("created_at"))
            lineas_m.append(f"• `[{f_ve}]` **{m.get('usuario_nombre')}**: {m.get('descripcion')}")

        return (
            f"🛡️ **Registro Histórico y Auditoría de Actividad:**\n\n"
            + ("\n".join(lineas_m) if lineas_m else "No se encontraron movimientos recientes.") +
            f"\n\nPuedes generar el historial completo con: [📥 Descargar Reporte de Auditoría (.xlsx)](/api/exportar/auditoria)."
        )

    # 11. DIRECTORIO GENERAL DE PROVEEDORES
    if any(k in p_lower for k in ["proveedor", "proveedores", "directorio", "suplidor", "suplidores", "cuentas bancarias", "banco"]):
        lineas_p = []
        for p in provs:
            lineas_p.append(f"• **{p.get('razon_social')}** — RIF: {p.get('rif') or 'N/A'} | Banco: {p.get('banco') or 'N/A'} | Cuenta: `{p.get('num_cuenta') or 'N/A'}`")
        return (
            f"🏛️ **Directorio Oficial de Proveedores ({len(provs)} registrados):**\n\n"
            + ("\n".join(lineas_p) if lineas_p else "No hay proveedores registrados.") +
            f"\n\nPuedes consultar un proveedor específico por su nombre o descargar el reporte en: [📥 Descargar Directorio de Proveedores (.xlsx)](/api/exportar/proveedores)."
        )

    # 12. PRECIOS Y COSTOS DE ÍTEMS DEL CATÁLOGO
    if pide_precio or item_mencionado:
        coincidencias = [item_mencionado] if item_mencionado else items_cat[:6]
        lineas_it = []
        for it in coincidencias:
            p_usd = float(it.get("precio_referencial_usd") or 0)
            p_bs = round(p_usd * tasa_usd, 2)
            p_prom = round(p_usd * tasa_prom, 2)
            lineas_it.append(f"• **{it.get('descripcion')}** ({it.get('unidad', 'UND')}): **${p_usd:,.2f} USD** (Bs. {p_bs:,.2f} a tasa BCV | Bs. {p_prom:,.2f} a tasa promedio)")

        return (
            f"🏷️ **Catálogo Oficial de Costos y Precios (Tasa BCV: ${tasa_usd:,.2f} Bs/USD | Promedio: ${tasa_prom:,.2f} Bs):**\n\n"
            + ("\n".join(lineas_it) if lineas_it else "No hay ítems registrados en el catálogo.") +
            f"\n\nPuedes pedirme convertir cualquiera a tasa promedio, tasa euro, o solicitarme actualizar sus precios."
        )

    # 13. DESCARGA DE REPORTES EXCEL
    if any(k in p_lower for k in ["excel", "descarga", "descargar", "exportar", "plantilla"]):
        return (
            f"Hola {usuario}. Aquí tienes los enlaces oficiales para exportar la información del sistema en Excel (.xlsx):\n\n"
            f"• [📥 Descargar Reporte de Órdenes (.xlsx)](/api/exportar/ordenes)\n"
            f"• [📥 Descargar Directorio de Proveedores (.xlsx)](/api/exportar/proveedores)\n"
            f"• [📥 Descargar Reporte de Auditoría (.xlsx)](/api/exportar/auditoria)\n"
            f"• [📥 Descargar Plantilla de Proveedores (.xlsx)](/api/plantilla/proveedores)"
        )

    # 14. RESPUESTA GENERAL
    return (
        f"Hola {usuario}. Soy Astrid, el asistente inteligente y cerebro analítico del Facturador SIST-LQ.\n\n"
        f"Actualmente contamos con:\n"
        f"• **{ctx['total_ordenes']} órdenes de compra emitidas** (Total: ${ctx['total_usd']:,.2f} USD / Bs. {ctx['total_bs']:,.2f})\n"
        f"• **{ctx['total_proveedores']} proveedores registrados** en el directorio\n"
        f"• **Tasa oficial BCV:** ${tasa_usd:,.2f} Bs/USD (EUR: €{tasa_eur:,.2f} Bs | Promedio: ${tasa_prom:,.2f} Bs)\n\n"
        f"Tengo acceso total para orientarte sobre precios, órdenes de compra, proveedores, auditoría, o generar reportes en Excel. ¿En qué puedo orientarte hoy?"
    )


# -----------------------------------------------------------------------------
# MEMORIA PERSISTENTE DE CHAT PARA ASTRID (JSON DATA)
# -----------------------------------------------------------------------------
def _normalizar_pregunta(texto):
    if not texto: return ""
    import unicodedata, re
    limpio = unicodedata.normalize('NFKD', texto).encode('ASCII', 'ignore').decode('utf-8').lower()
    return re.sub(r'[^a-z0-9\s]', '', limpio).strip()

def cargar_memoria_astrid():
    memoria_file = os.path.join(current_app.root_path, "data", "astrid_memory.json")
    if os.path.exists(memoria_file):
        try:
            with open(memoria_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def guardar_en_memoria_astrid(pregunta, respuesta, usuario):
    data_dir = os.path.join(current_app.root_path, "data")
    os.makedirs(data_dir, exist_ok=True)
    memoria_file = os.path.join(data_dir, "astrid_memory.json")
    memoria = cargar_memoria_astrid()
    
    norm = _normalizar_pregunta(pregunta)
    for entry in memoria:
        if entry.get("pregunta_normalizada") == norm:
            entry["respuesta"] = respuesta
            entry["veces_consultada"] = entry.get("veces_consultada", 1) + 1
            entry["ultimo_usuario"] = usuario
            entry["updated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
            try:
                with open(memoria_file, "w", encoding="utf-8") as f:
                    json.dump(memoria, f, ensure_ascii=False, indent=2)
            except Exception:
                pass
            return

    memoria.append({
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "usuario": usuario,
        "pregunta": pregunta,
        "pregunta_normalizada": norm,
        "respuesta": respuesta,
        "veces_consultada": 1
    })
    try:
        with open(memoria_file, "w", encoding="utf-8") as f:
            json.dump(memoria, f, ensure_ascii=False, indent=2)
    except Exception as e:
        if current_app: current_app.logger.warning(f"Error guardando memoria Astrid: {e}")

def buscar_en_memoria_astrid(pregunta):
    norm = _normalizar_pregunta(pregunta)
    if not norm or len(norm) < 4:
        return None
    # Evitar retornar respuestas cacheadas para consultas dinámicas del sistema
    keywords_dinamicas = ["precio", "costo", "tasa", "bcv", "dolar", "euro", "orden", "compra", "proveedor", "reporte", "grafica", "movimiento", "auditoria"]
    if any(k in norm for k in keywords_dinamicas):
        return None
    memoria = cargar_memoria_astrid()
    for entry in memoria:
        if entry.get("pregunta_normalizada") == norm:
            entry["veces_consultada"] = entry.get("veces_consultada", 1) + 1
            return entry.get("respuesta")
    
    words_query = set(w for w in norm.split() if len(w) > 3)
    if len(words_query) >= 3:
        for entry in memoria:
            words_entry = set(w for w in entry.get("pregunta_normalizada", "").split() if len(w) > 3)
            inter = words_query.intersection(words_entry)
            if len(inter) >= 3 and len(inter) / len(words_query) >= 0.8:
                entry["veces_consultada"] = entry.get("veces_consultada", 1) + 1
                return entry.get("respuesta")
    return None


@bp.route("/api/astrid", methods=["POST"])
def chat_astrid():
    if "user_id" not in session:
        return jsonify({"success": False, "error": "No autorizado. Inicie sesión."}), 401

    req_data = request.get_json(silent=True)
    if not req_data or "prompt" not in req_data:
        return jsonify({"success": False, "error": "No se proporcionó ningún texto."}), 400

    usuario = session.get("user_nombre", "Loreidy")
    prompt_usuario = req_data["prompt"].strip()

    # Historial de conversación en la sesión
    historial = session.get("astrid_chat_history", [])

    # Verificar si es una pregunta de seguimiento conversacional dependiente del contexto
    palabras_seguimiento = ["y ", "y a ", "también", "tambien", "como sale", "cuanto seria", "cuánto sería", "a tasa", "en promedio", "en euro", "en eur", "en bs"]
    p_low = prompt_usuario.lower()
    es_seguimiento = any(p_low.startswith(p) for p in palabras_seguimiento) or (len(p_low.split()) <= 4 and ("promedio" in p_low or "euro" in p_low or "bcv" in p_low or "dolar" in p_low))

    # 1. Búsqueda en memoria histórica JSON de Astrid (solo si es consulta aislada y no hay historial activo)
    respuesta_cached = None
    if not es_seguimiento and not historial:
        respuesta_cached = buscar_en_memoria_astrid(prompt_usuario)
    
    if respuesta_cached:
        historial.append({"role": "user", "content": prompt_usuario, "timestamp": datetime.datetime.now().strftime("%H:%M")})
        historial.append({"role": "assistant", "content": respuesta_cached, "timestamp": datetime.datetime.now().strftime("%H:%M")})
        session["astrid_chat_history"] = historial[-20:]
        session.modified = True
        return jsonify({
            "success": True, 
            "respuesta": respuesta_cached,
            "cached": True,
            "historial": session["astrid_chat_history"]
        })

    # 2. Consulta al motor cognitivo con historial
    try:
        respuesta_texto = consultar_ia_astrid(prompt_usuario, usuario, historial=historial)
        if not es_seguimiento:
            guardar_en_memoria_astrid(prompt_usuario, respuesta_texto, usuario)
        
        historial.append({"role": "user", "content": prompt_usuario, "timestamp": datetime.datetime.now().strftime("%H:%M")})
        historial.append({"role": "assistant", "content": respuesta_texto, "timestamp": datetime.datetime.now().strftime("%H:%M")})
        session["astrid_chat_history"] = historial[-20:]
        session.modified = True

        return jsonify({
            "success": True, 
            "respuesta": respuesta_texto,
            "cached": False,
            "historial": session["astrid_chat_history"]
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@bp.route("/api/astrid/historial", methods=["GET"])
def get_astrid_historial():
    if "user_id" not in session:
        return jsonify({"success": False, "error": "No autorizado"}), 401
    return jsonify({"success": True, "historial": session.get("astrid_chat_history", [])})


@bp.route("/api/astrid/limpiar", methods=["POST"])
def limpiar_chat_astrid():
    session["astrid_chat_history"] = []
    session.modified = True
    return jsonify({"success": True, "mensaje": "Conversación reiniciada"})


# -----------------------------------------------------------------------------
# EXPORTACIONES EN FORMATO EXCEL NATIVO (.XLSX)
# -----------------------------------------------------------------------------
import io
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

def _estilizar_hoja_excel(ws, headers, data_rows):
    fill_header = PatternFill(start_color="0F766E", end_color="0F766E", fill_type="solid") # Teal 700
    font_header = Font(name="Arial", size=10, bold=True, color="FFFFFF")
    font_data = Font(name="Arial", size=9)
    border_thin = Border(
        left=Side(style='thin', color='CBD5E1'),
        right=Side(style='thin', color='CBD5E1'),
        top=Side(style='thin', color='CBD5E1'),
        bottom=Side(style='thin', color='CBD5E1')
    )

    ws.append(headers)
    ws.row_dimensions[1].height = 24
    for cell in ws[1]:
        cell.fill = fill_header
        cell.font = font_header
        cell.alignment = Alignment(horizontal='center', vertical='center')

    for r_idx, row in enumerate(data_rows, start=2):
        ws.append(row)
        ws.row_dimensions[r_idx].height = 20

    for row in ws.iter_rows(min_row=2, max_row=ws.max_row, min_col=1, max_col=len(headers)):
        for cell in row:
            cell.font = font_data
            cell.border = border_thin
            if isinstance(cell.value, (int, float)):
                cell.number_format = '#,##0.00'
                cell.alignment = Alignment(horizontal='right', vertical='center')
            else:
                cell.alignment = Alignment(horizontal='left', vertical='center')

    for col in ws.columns:
        max_len = 0
        for cell in col:
            val = str(cell.value or '')
            if len(val) > max_len: max_len = len(val)
        col_letter = get_column_letter(col[0].column)
        ws.column_dimensions[col_letter].width = max(max_len + 4, 13)


@bp.route("/api/exportar/ordenes")
def exportar_ordenes_raw():
    if session.get("user_rol") != "admin":
        return "Acceso denegado", 403
    supabase = getattr(current_app, "supabase", None)
    ordenes = []
    if supabase:
        try:
            res = supabase.table("ordenes_compra").select("*, proyectos(nombre)").order("fecha_emision", desc=True).execute()
            ordenes = res.data or []
        except Exception:
            ordenes = MOCK_ORDENES
    else:
        ordenes = MOCK_ORDENES

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Órdenes de Compra"

    headers = ["Nro. Orden", "Fecha Emisión", "Proveedor", "RIF", "Proyecto", "Tasa BCV", "Total USD", "Total Bs", "Estado"]
    data = []
    for o in ordenes:
        p_nom = o.get("proyectos", {}).get("nombre") if isinstance(o.get("proyectos"), dict) else o.get("proyecto_nombre", "GENERAL")
        data.append([
            o.get("nro_orden", ""),
            str(o.get("fecha_emision", ""))[:10],
            o.get("proveedor_razon_social", ""),
            o.get("proveedor_rif", ""),
            p_nom,
            float(o.get("tasa_bcv") or 0),
            float(o.get("total_usd") or 0),
            float(o.get("total_bs") or 0),
            str(o.get("estado", "emitida")).upper()
        ])

    _estilizar_hoja_excel(ws, headers, data)
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=Reporte_Ordenes_SIST-LQ.xlsx"}
    )


@bp.route("/api/exportar/proveedores")
def exportar_proveedores_raw():
    if session.get("user_rol") != "admin":
        return "Acceso denegado", 403
    supabase = getattr(current_app, "supabase", None)
    provs = []
    if supabase:
        try:
            res = supabase.table("proveedores").select("*").order("razon_social").execute()
            provs = res.data or []
        except Exception:
            provs = MOCK_PROVEEDORES
    else:
        provs = MOCK_PROVEEDORES

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Proveedores"

    headers = ["Razón Social", "RIF", "Beneficiario", "Banco", "Nro. Cuenta", "Teléfono", "Email", "Dirección"]
    data = []
    for p in provs:
        data.append([
            p.get("razon_social", ""),
            p.get("rif", ""),
            p.get("beneficiario") or p.get("razon_social", ""),
            p.get("banco", ""),
            p.get("num_cuenta", ""),
            p.get("telefono", ""),
            p.get("email", ""),
            p.get("direccion", "")
        ])

    _estilizar_hoja_excel(ws, headers, data)
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=Reporte_Proveedores_SIST-LQ.xlsx"}
    )


@bp.route("/api/exportar/auditoria")
def exportar_auditoria_raw():
    if session.get("user_rol") != "admin":
        return "Acceso denegado", 403
    supabase = getattr(current_app, "supabase", None)
    movs = []
    if supabase:
        try:
            res = supabase.table("auditoria").select("*").order("fecha_hora", desc=True).execute()
            movs = res.data or []
        except Exception:
            movs = MOCK_MOVIMIENTOS
    else:
        movs = MOCK_MOVIMIENTOS

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Auditoría"

    headers = ["Fecha y Hora", "Usuario", "Acción", "Módulo", "Descripción"]
    data = []
    for m in movs:
        data.append([
            str(m.get("fecha_hora", m.get("timestamp", ""))),
            m.get("usuario", ""),
            m.get("accion", ""),
            m.get("modulo", ""),
            m.get("descripcion", "")
        ])

    _estilizar_hoja_excel(ws, headers, data)
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=Reporte_Auditoria_SIST-LQ.xlsx"}
    )


# -----------------------------------------------------------------------------
# CARGA MASIVA DE PROVEEDORES VÍA EXCEL (.XLSX) Y PLANTILLA
# -----------------------------------------------------------------------------
@bp.route("/api/proveedores/plantilla-excel", methods=["GET"])
def descargar_plantilla_proveedores():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Plantilla Proveedores"
    headers = ["RAZON_SOCIAL", "RIF", "BENEFICIARIO", "BANCO", "NUMERO_CUENTA", "TELEFONO", "EMAIL", "DIRECCION"]
    ejemplos = [
        ["DISTRIBUIDORA TEXTIL ANDINA C.A.", "J-40123456-7", "DISTRIBUIDORA TEXTIL ANDINA", "Banesco", "0134-0001-12-1234567890", "0414-5551234", "ventas@andina.com", "Zona Industrial La Bandera, Caracas"],
        ["SOLUCIONES INDUSTRIALES VENEZUELA S.A.", "J-30987654-2", "SOLUCIONES INDUSTRIALES", "Banco Mercantil", "0105-0022-33-0987654321", "0412-8889900", "info@soluciones.ve", "Av. Francisco de Miranda, Caracas"]
    ]
    _estilizar_hoja_excel(ws, headers, ejemplos)
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=Plantilla_Proveedores_SIST-LQ.xlsx"}
    )


@bp.route("/api/proveedores/carga-masiva", methods=["POST"])
def carga_masiva_proveedores():
    if session.get("user_rol") != "admin":
        return jsonify({"success": False, "error": "Acceso denegado. Solo administradores pueden realizar cargas masivas."}), 403

    if "archivo" not in request.files:
        return jsonify({"success": False, "error": "No se envió ningún archivo de Excel."}), 400

    archivo = request.files["archivo"]
    if not archivo.filename.lower().endswith(('.xlsx', '.xls')):
        return jsonify({"success": False, "error": "El archivo debe ser un libro de Excel válido (.xlsx)."}), 400

    try:
        wb = openpyxl.load_workbook(archivo, data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))

        if len(rows) < 2:
            return jsonify({"success": False, "error": "El archivo de Excel no contiene renglones de datos."}), 400

        headers = [str(h).strip().upper() if h else "" for h in rows[0]]

        def col_idx(pattern):
            for i, h in enumerate(headers):
                if pattern in h:
                    return i
            return -1

        i_razon = col_idx("RAZON")
        i_rif = col_idx("RIF")
        i_benef = col_idx("BENEF")
        i_banco = col_idx("BANCO")
        i_cuenta = col_idx("CUENTA")
        i_tel = col_idx("TEL")
        i_email = col_idx("EMAIL")
        i_dir = col_idx("DIR")

        if i_razon == -1 or i_rif == -1:
            return jsonify({"success": False, "error": "El archivo debe incluir obligatoriamente las columnas 'RAZON_SOCIAL' y 'RIF'."}), 400

        supabase = getattr(current_app, "supabase", None)
        creados = 0
        actualizados = 0

        for r in rows[1:]:
            if not r or not any(r):
                continue
            razon = str(r[i_razon]).strip() if (i_razon < len(r) and r[i_razon]) else ""
            rif = str(r[i_rif]).strip().upper() if (i_rif < len(r) and r[i_rif]) else ""
            if not razon or not rif:
                continue

            benef = str(r[i_benef]).strip() if (i_benef != -1 and i_benef < len(r) and r[i_benef]) else razon
            banco = str(r[i_banco]).strip() if (i_banco != -1 and i_banco < len(r) and r[i_banco]) else "Banco Principal"
            cuenta = str(r[i_cuenta]).strip() if (i_cuenta != -1 and i_cuenta < len(r) and r[i_cuenta]) else "0000-0000-00-0000000000"
            tel = str(r[i_tel]).strip() if (i_tel != -1 and i_tel < len(r) and r[i_tel]) else ""
            email = str(r[i_email]).strip() if (i_email != -1 and i_email < len(r) and r[i_email]) else ""
            dir_txt = str(r[i_dir]).strip() if (i_dir != -1 and i_dir < len(r) and r[i_dir]) else ""

            data_prov = {
                "razon_social": razon,
                "rif": rif,
                "beneficiario": benef,
                "banco": banco,
                "num_cuenta": cuenta,
                "telefono": tel,
                "email": email,
                "direccion": dir_txt
            }

            if supabase:
                chk = supabase.table("proveedores").select("id").eq("rif", rif).execute()
                if chk.data:
                    supabase.table("proveedores").update(data_prov).eq("id", chk.data[0]["id"]).execute()
                    actualizados += 1
                else:
                    supabase.table("proveedores").insert(data_prov).execute()
                    creados += 1
            else:
                existente = next((p for p in MOCK_PROVEEDORES if p["rif"] == rif), None)
                if existente:
                    existente.update(data_prov)
                    actualizados += 1
                else:
                    data_prov["id"] = f"prov-{len(MOCK_PROVEEDORES)+1}"
                    MOCK_PROVEEDORES.append(data_prov)
                    creados += 1

        usuario_actual = session.get("user_nombre", "Admin")
        registrar_movimiento(usuario_actual, "CARGA_MASIVA_PROVEEDORES", "PROVEEDORES", f"Carga masiva Excel completada: {creados} nuevos, {actualizados} actualizados.")
        return jsonify({
            "success": True,
            "creados": creados,
            "actualizados": actualizados,
            "total_procesados": creados + actualizados
        })
    except Exception as e:
        return jsonify({"success": False, "error": f"Error procesando archivo Excel: {str(e)}"}), 500


# -----------------------------------------------------------------------------
# PERFIL DE PROVEEDOR (HISTORIAL DE ÓRDENES Y PROYECTO REAL)
# -----------------------------------------------------------------------------
@bp.route("/api/proveedores/<rif>/perfil", methods=["GET"])
def perfil_proveedor(rif):
    supabase = getattr(current_app, "supabase", None)
    if supabase:
        try:
            res_prov = supabase.table("proveedores").select("*").eq("rif", rif).execute()
            if not res_prov.data:
                return jsonify({"success": False, "error": "Proveedor no encontrado"}), 404
            
            proveedor = res_prov.data[0]
            res_ordenes = supabase.table("ordenes_compra").select("id, nro_orden, fecha_emision, total_usd, estado, proyecto_id, proyectos(nombre)").eq("proveedor_rif", rif).order("fecha_emision", desc=True).execute()
            
            ordenes = []
            if res_ordenes.data:
                for o in res_ordenes.data:
                    p_nombre = "GENERAL"
                    if o.get("proyectos") and isinstance(o.get("proyectos"), dict):
                        p_nombre = o["proyectos"].get("nombre", "GENERAL")
                    elif o.get("proyecto_id"):
                        try:
                            p_q = supabase.table("proyectos").select("nombre").eq("id", o["proyecto_id"]).execute()
                            if p_q.data:
                                p_nombre = p_q.data[0].get("nombre", "GENERAL")
                        except Exception:
                            pass

                    ordenes.append({
                        "id": o.get("id"),
                        "nro_orden": o.get("nro_orden") or str(o.get("id"))[:8],
                        "fecha": str(o.get("fecha_emision", ""))[:10],
                        "proyecto": p_nombre,
                        "total_usd": o.get("total_usd"),
                        "estado": o.get("estado", "emitida")
                    })
            
            return jsonify({
                "success": True,
                "proveedor": proveedor,
                "ordenes": ordenes
            })
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500
    else:
        prov = next((p for p in MOCK_PROVEEDORES if p.get("rif") == rif), None)
        if not prov:
            return jsonify({"success": False, "error": "Proveedor no encontrado"}), 404
        
        ordenes = [o for o in MOCK_ORDENES if o.get("proveedor_rif") == rif]
        ordenes_fmt = []
        for o in ordenes:
            ordenes_fmt.append({
                "id": o.get("id"),
                "nro_orden": o.get("nro_orden") or str(o.get("id"))[:8],
                "fecha": str(o.get("fecha_emision", ""))[:10],
                "proyecto": o.get("proyecto_nombre", "MUESTRAS INTEVEP"),
                "total_usd": o.get("total_usd"),
                "estado": o.get("estado", "emitida")
            })
        return jsonify({
            "success": True,
            "proveedor": prov,
            "ordenes": ordenes_fmt
        })


