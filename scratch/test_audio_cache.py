import os
import sys
import time

sys.path.insert(0, r"c:\Users\user\Pictures\FACTURADOR_LORE")
from app import create_app

app = create_app()

print("=" * 60)
print("TEST 1: BIENVENIDA AUDIO CACHING / RESGUARDO EN DISCO")
print("=" * 60)

with app.test_client() as client:
    with client.session_transaction() as sess:
        sess["user_id"] = "usr-test-1"
        sess["user_nombre"] = "Joan Sequera"

    saludos_dir = os.path.join(app.root_path, "static", "audio", "saludos")
    print(f"Directorio de resguardo: {saludos_dir}")

    # Momento mañana
    t0 = time.time()
    r1 = client.get("/api/astrid/bienvenida?usuario=Joan%20Sequera&momento=manana")
    t1 = time.time()
    d1 = r1.get_json()
    print(f"\n[1ra Ejecución - Joan Sequera (Mañana)]:")
    print(f"  Status: {r1.status_code}")
    print(f"  Cached: {d1.get('cached')} (Debe ser False si se generó por primera vez)")
    print(f"  Filename: {d1.get('filename')}")
    print(f"  Saludo: {d1.get('saludo')}")
    print(f"  Audio URL: {d1.get('audio_url')}")
    print(f"  Audio b64 size: {len(d1.get('audio_b64', ''))} chars")
    print(f"  Tiempo: {t1 - t0:.2f}s")

    filepath = os.path.join(saludos_dir, d1.get("filename", ""))
    print(f"  Archivo en disco existe: {os.path.exists(filepath)} (Tamaño: {os.path.getsize(filepath) if os.path.exists(filepath) else 0} bytes)")

    # 2da Ejecución: Debe ser instantáneo desde el disco (CACHED)
    t2 = time.time()
    r2 = client.get("/api/astrid/bienvenida?usuario=Joan%20Sequera&momento=manana")
    t3 = time.time()
    d2 = r2.get_json()
    print(f"\n[2da Ejecución - Joan Sequera (Mañana - Cache Hit)]:")
    print(f"  Status: {r2.status_code}")
    print(f"  Cached: {d2.get('cached')} (DEBE SER TRUE - 0 llamadas API)")
    print(f"  Audio URL: {d2.get('audio_url')}")
    print(f"  Tiempo: {t3 - t2:.4f}s (Instantáneo desde disco)")
    assert d2.get("cached") == True, "ERROR: La 2da ejecución debió venir de disco"

    # Probar otros momentos: tarde y noche
    for mom in ["tarde", "noche"]:
        rx = client.get(f"/api/astrid/bienvenida?usuario=Joan%20Sequera&momento={mom}")
        dx = rx.get_json()
        print(f"\n[Generado Joan Sequera ({mom})]:")
        print(f"  Filename: {dx.get('filename')}")
        print(f"  Saludo: {dx.get('saludo')}")
        print(f"  Cached: {dx.get('cached')}")

    # Probar Loreidy
    r_loreidy = client.get("/api/astrid/bienvenida?usuario=Loreidy&momento=tarde")
    d_loreidy = r_loreidy.get_json()
    print(f"\n[Generado Loreidy (tarde)]:")
    print(f"  Filename: {d_loreidy.get('filename')}")
    print(f"  Saludo: {d_loreidy.get('saludo')}")
    print(f"  Cached: {d_loreidy.get('cached')}")

    print("\n" + "=" * 60)
    print("TEST 2: ASTRID IA CHAT SILENCIOSO (TEXTO PURO, SIN VOZ)")
    print("=" * 60)

    # Simular consulta al chat de Astrid
    r_chat = client.post("/api/astrid", json={"prompt": "¿Cuántos proveedores tenemos?"})
    print(f"Status POST /api/astrid: {r_chat.status_code}")
    d_chat = r_chat.get_json()
    print(f"Respuesta keys: {list(d_chat.keys())}")
    print(f"Tiene 'audio_b64'?: {'audio_b64' in d_chat} (Debe ser False)")
    print(f"Respuesta texto: {d_chat.get('respuesta', d_chat.get('error'))}")
    assert 'audio_b64' not in d_chat, "ERROR: Astrid chat no debe generar audio!"

    print("\nTODAS LAS PRUEBAS DE AUDIO Y ASTRID SILENCIOSA PASARON EXITOSAMENTE.")
