import os
from flask import Flask
from config import Config
from supabase import create_client, Client

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # Inicializar cliente de Supabase dinámico
    supabase_url = app.config.get("SUPABASE_URL")
    supabase_key = app.config.get("SUPABASE_KEY")
    
    supabase: Client = None
    if supabase_url and supabase_key and "your-supabase" not in supabase_url:
        try:
            supabase = create_client(supabase_url, supabase_key)
        except Exception as e:
            app.logger.warning(f"No se pudo conectar a Supabase: {e}")

    app.supabase = supabase

    # Registrar Blueprints
    from routes import bp as main_bp, format_decimal, obtener_tasa_bcv
    app.register_blueprint(main_bp)

    # Cargar logo corporativo cit.png en Base64 para WeasyPrint (rutas dinámicas)
    import base64
    logo_b64 = ""
    rutas_logo = [
        os.path.join(app.root_path, "cit.png"),
        os.path.join(app.root_path, "static", "img", "cit.png")
    ]
    for ruta in rutas_logo:
        if os.path.exists(ruta):
            try:
                with open(ruta, "rb") as f:
                    logo_b64 = base64.b64encode(f.read()).decode("utf-8")
                break
            except Exception as e:
                app.logger.warning(f"No se pudo cargar {ruta}: {e}")

    # Inyectar format_decimal, info_bcv y logo_b64 globalmente a todas las plantillas Jinja2
    @app.context_processor
    def inject_globals():
        return {
            "format_decimal": format_decimal,
            "info_bcv": obtener_tasa_bcv(),
            "logo_b64": logo_b64
        }

    app.jinja_env.filters["format_decimal"] = format_decimal

    return app

# Instancia WSGI para servidores de producción (Gunicorn, Waitress, uWSGI, Docker)
app = create_app()

if __name__ == "__main__":
    host = app.config.get("HOST", "0.0.0.0")
    port = app.config.get("PORT", 5000)
    debug = app.config.get("DEBUG", False)
    app.run(host=host, port=port, debug=debug)
