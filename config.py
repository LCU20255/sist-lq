import os
from pathlib import Path
from dotenv import load_dotenv

# Directorio base resuelto dinámicamente
BASE_DIR = Path(__file__).resolve().parent

# Cargar .env de forma dinámica y absoluta desde BASE_DIR
env_file = BASE_DIR / ".env"
if env_file.exists():
    load_dotenv(env_file)
else:
    load_dotenv()

class Config:
    BASE_DIR = str(BASE_DIR)
    SECRET_KEY = os.getenv("SECRET_KEY", "super-secret-key-sist-lq-2026")
    SUPABASE_URL = os.getenv("SUPABASE_URL", "")
    SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")
    
    # Detección inteligente de entorno de producción / desarrollo
    FLASK_ENV = os.getenv("FLASK_ENV", "production" if (os.getenv("RENDER") or os.getenv("HEROKU") or os.getenv("RAILWAY_ENVIRONMENT")) else "development")
    DEBUG = os.getenv("DEBUG", "False").lower() in ("true", "1", "t")
    
    # Puertos y Host dinámicos para despliegue en cualquier servidor cloud o local
    PORT = int(os.getenv("PORT", 5000))
    HOST = os.getenv("HOST", "0.0.0.0")
