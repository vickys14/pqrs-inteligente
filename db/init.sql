-- Tabla principal: una fila por cada PQRS procesada
CREATE TABLE IF NOT EXISTS pqrs_casos (
    id              SERIAL PRIMARY KEY,
    archivo_origen  TEXT UNIQUE NOT NULL,   -- ruta del archivo en MinIO (ej. pqrs-raw/audios/caso_001.mp3)
    canal           TEXT NOT NULL CHECK (canal IN ('texto', 'audio', 'foto')),
    texto_extraido  TEXT,                   -- texto original, transcripción u OCR
    tipo            TEXT CHECK (tipo IN ('peticion', 'queja', 'reclamo', 'sugerencia')),
    tema            TEXT,                   -- notas, finanzas, infraestructura, bienestar, etc.
    urgencia        TEXT CHECK (urgencia IN ('baja', 'media', 'alta')),
    area_destino    TEXT,                   -- area responsable (Tesoreria, Registro, etc.)
    clasificador    TEXT,                   -- 'ollama' o 'claude'
    fecha_recepcion DATE,                   -- fecha en que llego la PQRS
    creado_en       TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pqrs_tipo ON pqrs_casos (tipo);
CREATE INDEX IF NOT EXISTS idx_pqrs_tema ON pqrs_casos (tema);
CREATE INDEX IF NOT EXISTS idx_pqrs_urgencia ON pqrs_casos (urgencia);
