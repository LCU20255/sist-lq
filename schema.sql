-- =============================================================================
-- SCRIPT SQL PARA SUPABASE (POSTGRESQL)
-- Sistema de Generación y Gestión de Órdenes de Compra
-- =============================================================================

-- Habilitar extensión uuid-ossp para generar UUIDs automáticamente
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- -----------------------------------------------------------------------------
-- 1. TABLA: usuarios
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS usuarios (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    nombre VARCHAR(150) NOT NULL,
    rol VARCHAR(50) DEFAULT 'usuario' CHECK (rol IN ('admin', 'usuario', 'revisor')),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- -----------------------------------------------------------------------------
-- 2. TABLA: proveedores
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS proveedores (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    razon_social VARCHAR(255) NOT NULL,
    rif VARCHAR(50) UNIQUE NOT NULL,
    beneficiario VARCHAR(255) NOT NULL,
    banco VARCHAR(100) NOT NULL,
    num_cuenta VARCHAR(50) NOT NULL,
    telefono VARCHAR(50),
    email VARCHAR(255),
    direccion TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- -----------------------------------------------------------------------------
-- 3. TABLA: proyectos
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS proyectos (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    codigo VARCHAR(50) UNIQUE NOT NULL,
    nombre VARCHAR(255) NOT NULL,
    descripcion TEXT,
    estado VARCHAR(50) DEFAULT 'activo' CHECK (estado IN ('activo', 'inactivo', 'completado')),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- -----------------------------------------------------------------------------
-- 3b. TABLA: items_catalogo
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS items_catalogo (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    descripcion TEXT NOT NULL,
    unidad VARCHAR(50) NOT NULL DEFAULT 'UND',
    precio_referencial_usd NUMERIC(14, 2) DEFAULT 0.00,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- -----------------------------------------------------------------------------
-- 3c. TABLA: firmantes (Personal Autorizado)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS firmantes (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    nombre VARCHAR(150) NOT NULL,
    cargo VARCHAR(150),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- -----------------------------------------------------------------------------
-- 4. TABLA: ordenes_compra
-- Importante: Guarda los datos del proveedor textualmente para inmutabilidad histórica.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ordenes_compra (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    nro_orden VARCHAR(50) UNIQUE NOT NULL,
    proyecto_id UUID REFERENCES proyectos(id) ON DELETE SET NULL,
    usuario_id UUID REFERENCES usuarios(id) ON DELETE SET NULL,
    
    -- Inmutabilidad Histórica del Proveedor (Snapshot)
    proveedor_id UUID REFERENCES proveedores(id) ON DELETE SET NULL,
    proveedor_razon_social VARCHAR(255) NOT NULL,
    proveedor_rif VARCHAR(50) NOT NULL,
    proveedor_beneficiario VARCHAR(255) NOT NULL,
    proveedor_banco VARCHAR(100) NOT NULL,
    proveedor_num_cuenta VARCHAR(50) NOT NULL,
    
    -- Tasa de Cambio (BCV)
    tasa_bcv NUMERIC(12, 4) NOT NULL,
    
    -- Montos en USD
    subtotal_exento_usd NUMERIC(14, 2) NOT NULL DEFAULT 0.00,
    subtotal_gravable_usd NUMERIC(14, 2) NOT NULL DEFAULT 0.00,
    iva_usd NUMERIC(14, 2) NOT NULL DEFAULT 0.00,
    descuento_usd NUMERIC(14, 2) NOT NULL DEFAULT 0.00,
    total_usd NUMERIC(14, 2) NOT NULL DEFAULT 0.00,
    
    -- Montos en Bolívares (Bs)
    subtotal_exento_bs NUMERIC(16, 2) NOT NULL DEFAULT 0.00,
    subtotal_gravable_bs NUMERIC(16, 2) NOT NULL DEFAULT 0.00,
    iva_bs NUMERIC(16, 2) NOT NULL DEFAULT 0.00,
    descuento_bs NUMERIC(16, 2) NOT NULL DEFAULT 0.00,
    total_bs NUMERIC(16, 2) NOT NULL DEFAULT 0.00,
    
    -- Firmantes (Inmutabilidad Textual)
    firmante_solicitado VARCHAR(150) NOT NULL DEFAULT 'LOREIDY QUIÑONEZ',
    firmante_revisado VARCHAR(150) NOT NULL DEFAULT 'RAMON RIVAS',
    
    observaciones TEXT,
    estado VARCHAR(50) DEFAULT 'Emitida' CHECK (estado IN ('Borrador', 'Emitida', 'Aprobada', 'Anulada')),
    fecha_emision DATE NOT NULL DEFAULT CURRENT_DATE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- -----------------------------------------------------------------------------
-- 5. TABLA: orden_detalles (Ítems de la orden de compra)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS orden_detalles (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    orden_id UUID NOT NULL REFERENCES ordenes_compra(id) ON DELETE CASCADE,
    renglon_num INT NOT NULL,
    descripcion TEXT NOT NULL,
    cantidad NUMERIC(12, 2) NOT NULL CHECK (cantidad > 0),
    unidad VARCHAR(50) NOT NULL,
    precio_unitario_usd NUMERIC(14, 2) NOT NULL CHECK (precio_unitario_usd >= 0),
    total_linea_usd NUMERIC(14, 2) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- -----------------------------------------------------------------------------
-- DATOS DE PRUEBA (SEED DATA)
-- -----------------------------------------------------------------------------

-- Insertar usuario por defecto (Contraseña: admin123)
INSERT INTO usuarios (email, password_hash, nombre, rol)
VALUES ('admin@nexa.com', 'scrypt:32768:8:1$u7xV4z...$admin123hash', 'Administrador Principal', 'admin')
ON CONFLICT (email) DO NOTHING;

-- Insertar Proveedores de Prueba
INSERT INTO proveedores (razon_social, rif, beneficiario, banco, num_cuenta, telefono, email, direccion)
VALUES 
('Suministros Industriales C.A.', 'J-12345678-9', 'Suministros Industriales C.A.', 'Banco Mercantil', '0105-0012-34-1234567890', '0414-1234567', 'ventas@suministros.com', 'Av. Principal Colinas de Bello Monte, Caracas'),
('Soluciones Tecnológicas R&M S.R.L.', 'J-98765432-1', 'Soluciones Tecnológicas R&M', 'Banesco', '0134-0987-65-0987654321', '0424-9876543', 'contacto@solutec.com', 'Zona Industrial II, Barquisimeto')
ON CONFLICT (rif) DO NOTHING;

-- Insertar Proyectos de Prueba
INSERT INTO proyectos (codigo, nombre, descripcion, estado)
VALUES 
('PROY-2026-01', 'Modernización de Infraestructura de Redes', 'Actualización de cableado estructurado y servidores centralizados', 'activo'),
('PROY-2026-02', 'Mantenimiento Preventivo Planta Alfa', 'Servicio técnico trimestral de maquinaria pesada', 'activo')
ON CONFLICT (codigo) DO NOTHING;

-- Insertar Items de Prueba
INSERT INTO items_catalogo (descripcion, unidad, precio_referencial_usd)
VALUES
('COMPRA DE DRILL 100% ALGODON ROJO', 'Metros', 5.31),
('Servidor Rack 2U Intel Xeon 64GB RAM', 'UND', 1200.00),
('Switch Administrable 24 Puertos Gigabit', 'UND', 300.00);

-- Insertar Firmantes de Prueba
INSERT INTO firmantes (nombre, cargo)
VALUES
('LOREIDY QUIÑONEZ', 'Departamento de Compras'),
('RAMON RIVAS', 'Gerencia de Administración / Finanzas');

-- -----------------------------------------------------------------------------
-- 6. TABLA: historial_movimientos (Auditoría y Trazabilidad en tiempo real)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS historial_movimientos (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    usuario_id UUID REFERENCES usuarios(id) ON DELETE SET NULL,
    usuario_nombre VARCHAR(150) NOT NULL,
    accion VARCHAR(50) NOT NULL,
    modulo VARCHAR(50) NOT NULL,
    descripcion TEXT NOT NULL,
    detalles JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Insertar movimiento inicial de bienvenida
INSERT INTO historial_movimientos (usuario_nombre, accion, modulo, descripcion)
VALUES ('Sistema SIST-LQ', 'INICIALIZACION', 'SISTEMA', 'Sistema SIST-LQ inicializado correctamente con base de datos en la nube.');

