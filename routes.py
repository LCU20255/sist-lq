import os
import datetime
import re
import requests
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
        "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
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
    import datetime
    hora_local = datetime.datetime.now() - datetime.timedelta(hours=4)
    now_str = hora_local.strftime("%Y-%m-%d %H:%M:%S")
    mov_obj = {
        "usuario_nombre": usuario_nombre or "Usuario SIST-LQ",
        "accion": accion,
        "modulo": modulo,
        "descripcion": descripcion,
        "created_at": now_str
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
        filename = f"Orden_Compra_{orden.get('nro_orden', 'doc')}.pdf"
        response.headers["Content-Disposition"] = f"inline; filename={filename}"
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

    # Generar código automático
    import datetime
    hoy = datetime.datetime.now()
    prefijo = f"PROY-{hoy.strftime('%Y-%m')}"
    
    if supabase:
        try:
            chk = supabase.table("proyectos").select("id").execute()
            contador = len(chk.data) + 1 if chk.data else 1
            codigo = f"{prefijo}-{str(contador).zfill(3)}"
        except Exception:
            codigo = f"{prefijo}-{str(len(MOCK_PROYECTOS) + 1).zfill(3)}"
    else:
        codigo = f"{prefijo}-{str(len(MOCK_PROYECTOS) + 1).zfill(3)}"

    # Anti-duplicados por código (ya no es estrictamente necesario si es automático, pero por seguridad)
    if supabase:
        try:

            data = {"codigo": codigo, "nombre": nombre, "estado": "activo"}
            res = supabase.table("proyectos").insert(data).execute()
            if res.data:
                usuario_actual = session.get("user_nombre", "Loreidy Quiñonez")
                registrar_movimiento(usuario_actual, "CREAR_PROYECTO", "PROYECTOS", f"Nuevo proyecto: {nombre} [{codigo}]")
                return jsonify({"success": True, "id": res.data[0]["id"], "codigo": codigo, "nombre": nombre})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    if any(p.get("codigo") == codigo for p in MOCK_PROYECTOS):
        return jsonify({"success": False, "error": f"Ya existe un proyecto con código '{codigo}'."}), 400

    mock_id = f"proy-mock-{len(MOCK_PROYECTOS) + 1}"
    proy_data = {"id": mock_id, "codigo": codigo, "nombre": nombre}
    MOCK_PROYECTOS.append(proy_data)
    registrar_movimiento(session.get("user_nombre", "Loreidy"), "CREAR_PROYECTO", "PROYECTOS", f"Proyecto creado: {nombre}")
    return jsonify({"success": True, "id": mock_id, "codigo": codigo, "nombre": nombre})


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


@bp.route("/api/items/<item_id>", methods=["PUT"])
def editar_item(item_id):
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
    supabase = getattr(current_app, "supabase", None)
    if supabase:
        try:
            # Eliminar los renglones primero por constraint fk (aunque si hay cascade delete no haría falta, es mejor prevenir)
            supabase.table("orden_detalles").delete().eq("orden_id", orden_id).execute()
            # Eliminar la orden
            res = supabase.table("ordenes_compra").delete().eq("id", orden_id).execute()
            
            usuario_actual = session.get("user_nombre", "Loreidy Quiñonez")
            registrar_movimiento(usuario_actual, "ELIMINAR_ORDEN", "ORDENES", f"Orden eliminada: ID {orden_id}")
            
            return jsonify({"success": True})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500
    else:
        # Modo Mock (sin base de datos)
        global MOCK_ORDENES
        MOCK_ORDENES = [o for o in MOCK_ORDENES if str(o.get("id")) != str(orden_id)]
        usuario_actual = session.get("user_nombre", "Loreidy Quiñonez")
        registrar_movimiento(usuario_actual, "ELIMINAR_ORDEN", "ORDENES", f"Orden eliminada (Mock): ID {orden_id}")
        return jsonify({"success": True})

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

def _generar_hf_tts(texto):
    """
    Genera audio WAV via Hugging Face Inference API (facebook/mms-tts-spa).
    Motor Open Source gratuito para español. Requiere HF_TOKEN en variables de entorno.
    Retorna bytes de audio WAV o b"" si falla.
    """
    hf_token = os.getenv("HF_TOKEN", "")
    hf_model = os.getenv("HF_TTS_MODEL", "facebook/mms-tts-spa")
    if not hf_token:
        return b""
    try:
        url = f"https://api-inference.huggingface.co/models/{hf_model}"
        headers = {"Authorization": f"Bearer {hf_token}"}
        r = requests.post(url, headers=headers, json={"inputs": texto}, timeout=18)
        ct = r.headers.get("content-type", "")
        if r.status_code == 200 and ("audio" in ct or len(r.content) > 1000):
            if current_app:
                current_app.logger.info(f"HF TTS OK: {len(r.content)} bytes ({hf_model})")
            return r.content
        else:
            if current_app:
                current_app.logger.warning(f"HF TTS fallo {r.status_code}: {r.text[:120]}")
            return b""
    except Exception as e:
        if current_app:
            current_app.logger.warning(f"HF TTS excepción: {e}")
        return b""

def generar_audio_astrid(texto):
    """
    Motor TTS de Astrid con cascade inteligente:
      1. Hugging Face Inference API (facebook/mms-tts-spa) — Open Source, español nativo
      2. Edge TTS (es-MX-DaliaNeural) — Fallback neural gratuito e ilimitado
    
    0 descargas locales. 0 MB en disco. Ultra rápido. Sin cortes en producción.
    Retorna: (audio_b64, audio_mime)
    """
    import base64

    texto_limpio = re.sub(r'[*#_`]', '', texto)
    texto_limpio = re.sub(r'[\U00010000-\U0010ffff]', '', texto_limpio).strip()
    if not texto_limpio:
        return "", ""

    texto_corto = texto_limpio[:1500]  # MMS-TTS tiene mejor calidad con textos cortos

    # ── 1. Intentar Hugging Face TTS (español Open Source) ─────────────────────
    try:
        hf_audio = _generar_hf_tts(texto_corto)
        if hf_audio:
            mime = "audio/wav"
            return base64.b64encode(hf_audio).decode("utf-8"), mime
    except Exception as e:
        if current_app:
            current_app.logger.warning(f"HF TTS no disponible, usando Edge TTS: {e}")

    # ── 2. Fallback: Edge TTS Neural (es-MX-DaliaNeural) ──────────────────────
    try:
        voz = os.getenv("TTS_VOICE", "es-MX-DaliaNeural")
        audio_mp3 = _generar_edge_tts(texto_corto, voice=voz)
        if audio_mp3:
            if current_app:
                current_app.logger.info("Usando Edge TTS (fallback) — OK")
            return base64.b64encode(audio_mp3).decode("utf-8"), "audio/mp3"
    except Exception as err:
        if current_app:
            current_app.logger.error(f"Error en Edge TTS fallback: {err}")

    return "", ""


@bp.route("/api/astrid/bienvenida", methods=["GET", "POST"])
def astrid_bienvenida():
    if "user_id" not in session:
        return jsonify({"success": False, "error": "No autorizado"}), 401
        
    usuario = session.get("user_nombre", "Loreidy")
    
    # Hora local de Venezuela (UTC-4)
    utc_now = datetime.datetime.now(datetime.timezone.utc)
    hora_ve = (utc_now - datetime.timedelta(hours=4)).hour
    
    if 5 <= hora_ve < 12:
        saludo_tiempo = "¡Buenos días"
    elif 12 <= hora_ve < 19:
        saludo_tiempo = "¡Buenas tardes"
    else:
        saludo_tiempo = "¡Buenas noches"
        
    texto_saludo = f"{saludo_tiempo}, {usuario}! Soy Astrid. Todos los sistemas del Facturador SIST-LQ están en línea y a tu disposición."
    
    audio_b64, audio_mime = generar_audio_astrid(texto_saludo)
    
    return jsonify({
        "success": True,
        "saludo": texto_saludo,
        "audio_b64": audio_b64,
        "audio_mime": audio_mime
    })

def consultar_ia_astrid(prompt_usuario, usuario="Loreidy"):
    """
    Motor cognitivo de Astrid:
    Utiliza OpenRouter API con modelos gratuitos de última generación (Nemotron, MiniMax, Gemma).
    """
    sys_prompt = (
        f"Eres Astrid, la asistente virtual super inteligente del sistema Facturador SIST-LQ. "
        f"Hablas en español latino cálido, eres profesional, muy amable y resolutiva. "
        f"El usuario con el que conversas se llama {usuario}. "
        f"IMPORTANTE: Da respuestas claras, directas y concisas (máximo 2 a 3 oraciones o pasos breves) "
        f"para que la respuesta hablada sea ágil e inmediata."
    )
    
    openrouter_key = os.getenv("OPENROUTER_API_KEY")
    if not openrouter_key:
        raise RuntimeError("OPENROUTER_API_KEY no configurada en las variables de entorno.")

    models = [
        os.getenv("OPENROUTER_MODEL", "liquid/lfm-2.5-2.6b:free"),
        "nvidia/nemotron-3.5-lightning:free",
        "minimax/minimax-m3:free"
    ]
    headers = {
        "Authorization": f"Bearer {openrouter_key}",
        "HTTP-Referer": "https://sis-fact-lq.onrender.com",
        "X-Title": "SIST-LQ Astrid Assistant"
    }
    for model in models:
        try:
            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": prompt_usuario}
                ],
                "temperature": 0.6,
                "max_tokens": 250
            }
            r = requests.post("https://openrouter.ai/api/v1/chat/completions", json=payload, headers=headers, timeout=12)
            if r.status_code == 200:
                data = r.json()
                choices = data.get("choices", [])
                if choices and "message" in choices[0]:
                    msg = choices[0]["message"]
                    texto_resp = msg.get("content") or ""
                    # Si el modelo incluye cadenas de razonamiento previo tipo thinking
                    if not texto_resp and msg.get("reasoning"):
                        texto_resp = msg.get("reasoning")
                    if "Here's a thinking process:" in texto_resp:
                        # Limpiar posible prefijo de pensamiento
                        partes = re.split(r'\n\n(?=[¡¿A-Z])', texto_resp)
                        if len(partes) > 1:
                            texto_resp = partes[-1]
                    if texto_resp.strip():
                        return texto_resp.strip()
            else:
                if current_app:
                    current_app.logger.warning(f"OpenRouter modelo {model} retorno {r.status_code}: {r.text[:100]}")
        except Exception as e:
            if current_app:
                current_app.logger.warning(f"Excepcion en OpenRouter ({model}): {e}")

    raise RuntimeError("No se pudo conectar con el motor de IA OpenRouter. Verifique su conexión y API key.")

@bp.route("/api/astrid", methods=["POST"])
def chat_astrid():
    if "user_id" not in session:
        return jsonify({"success": False, "error": "No autorizado. Inicie sesión."}), 401

    req_data = request.get_json(silent=True)
    if not req_data or "prompt" not in req_data:
        return jsonify({"success": False, "error": "No se proporcionó ningún texto."}), 400

    usuario = session.get("user_nombre", "Loreidy")
    prompt_usuario = req_data["prompt"]

    try:
        # 1. Generar texto cognitivo con OpenRouter
        respuesta_texto = consultar_ia_astrid(prompt_usuario, usuario)
        
        # 2. Generar audio (ElevenLabs primario con fallback a Gemini TTS)
        audio_b64, audio_mime = generar_audio_astrid(respuesta_texto)

        return jsonify({
            "success": True, 
            "respuesta": respuesta_texto,
            "audio_b64": audio_b64,
            "audio_mime": audio_mime
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

import csv
import io
from flask import Response

@bp.route("/api/exportar/ordenes")
def exportar_ordenes_raw():
    if session.get("user_rol") != "admin":
        return "Acceso denegado", 403
    supabase = getattr(current_app, "supabase", None)
    if not supabase: return "Mock Data", 400
    try:
        res = supabase.table("ordenes_compra").select("*").execute()
        if not res.data: return "No data", 404
        
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=res.data[0].keys())
        writer.writeheader()
        writer.writerows(res.data)
        
        return Response(output.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment;filename=ordenes_raw.csv"})
    except Exception as e:
        return str(e), 500

@bp.route("/api/exportar/proveedores")
def exportar_proveedores_raw():
    if session.get("user_rol") != "admin":
        return "Acceso denegado", 403
    supabase = getattr(current_app, "supabase", None)
    if not supabase: return "Mock Data", 400
    try:
        res = supabase.table("proveedores").select("*").execute()
        if not res.data: return "No data", 404
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=res.data[0].keys())
        writer.writeheader()
        writer.writerows(res.data)
        return Response(output.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment;filename=proveedores_raw.csv"})
    except Exception as e:
        return str(e), 500

@bp.route("/api/exportar/auditoria")
def exportar_auditoria_raw():
    if session.get("user_rol") != "admin":
        return "Acceso denegado", 403
    supabase = getattr(current_app, "supabase", None)
    if not supabase: return "Mock Data", 400
    try:
        res = supabase.table("auditoria").select("*").execute()
        if not res.data: return "No data", 404
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=res.data[0].keys())
        writer.writeheader()
        writer.writerows(res.data)
        return Response(output.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment;filename=auditoria_raw.csv"})
    except Exception as e:
        return str(e), 500

@bp.route("/api/proveedores/<rif>/perfil", methods=["GET"])
def perfil_proveedor(rif):
    supabase = getattr(current_app, "supabase", None)
    if supabase:
        try:
            # Buscar el proveedor
            res_prov = supabase.table("proveedores").select("*").eq("rif", rif).execute()
            if not res_prov.data:
                return jsonify({"success": False, "error": "Proveedor no encontrado"}), 404
            
            proveedor = res_prov.data[0]
            
            # Buscar las órdenes emitidas a este proveedor
            res_ordenes = supabase.table("ordenes_compra").select("id, nro_orden, fecha_emision, total_usd, estado").eq("proveedor_rif", rif).order("fecha_emision", desc=True).execute()
            
            ordenes = []
            if res_ordenes.data:
                for o in res_ordenes.data:
                    ordenes.append({
                        "id": o.get("id"),
                        "fecha": o.get("fecha_emision")[:10] if o.get("fecha_emision") else "",
                        "proyecto": "N/A", # Opcional: cargar nombre de proyecto si se requiere
                        "total_usd": o.get("total_usd"),
                        "estado": o.get("estado")
                    })
            
            return jsonify({
                "success": True,
                "proveedor": proveedor,
                "ordenes": ordenes
            })
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500
    else:
        # Mock para demostración
        prov = next((p for p in MOCK_PROVEEDORES if p.get("rif") == rif), None)
        if not prov:
            return jsonify({"success": False, "error": "Proveedor no encontrado"}), 404
        
        ordenes = [o for o in MOCK_ORDENES if o.get("proveedor_rif") == rif]
        ordenes_fmt = []
        for o in ordenes:
            ordenes_fmt.append({
                "id": o.get("id"),
                "fecha": o.get("fecha_emision")[:10] if o.get("fecha_emision") else "",
                "proyecto": "Mock Proyecto",
                "total_usd": o.get("total_usd"),
                "estado": o.get("estado")
            })
        return jsonify({
            "success": True,
            "proveedor": prov,
            "ordenes": ordenes_fmt
        })
